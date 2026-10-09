# -*- coding: utf-8 -*-
"""YINN 成本后净收益取证 —— 第 12.35 条**检验 2**：成本后净收益（§12.37 口径）。

================================================================================
这是否证性取证，**不授权**任何实施（第 13.4 条）
================================================================================
1. 检验的是：§12.35 检验 1（动量方向稳定，120 日 IC 样本外 +0.114）所反映的
   **价差**，在扣掉 3× 杠杆损耗与双边交易成本后，是否仍**为正**。
2. **判定用「净价差」而非 IC**（§12.37 裁决）：IC 是 **Spearman 秩相关**，
   成本近似为「对所有样本的同向平移」时**秩不变** ⇒ IC 几乎不变 ⇒
   用 IC 判成本会给出**假通过**。故改用净值量纲的价差。
3. 方法**零参数**（§12.37）：不发明仓位规则、不设阈值、不挑 horizon
   （120 日由 §12.36 的符号稳定性**唯一确定**，不是搜索）。
4. **负面结果 = 永久关闭该问题**；**正面结果也不授权**新建市场 / 改规则 ——
   按第 13.4 条第 1 款，须来自**真实操作的复盘**。结论只能进「待观察」清单。

口径（§12.37，逐字）：
  步 1 损耗标定：**复用** `fg_system/leverage.py::decompose(FXI 日收益, YINN 日收益, n=3)`
     ⇒ `vol_decay_annual` / `product_cost_annual` / `total_annual`（均为年化）。
  步 2 信号价差：**复用** `screening.bucket_table`，`价差 = 最贪婪组均值 − 最恐惧组均值`
     （组号 n-1 减组号 0；注意是**动量**口径，期望**为正**）。
     因子与 horizon 复用 `scripts/screen_yinn_momentum.py` 的 `CANDIDATES["kweb_price"]`
     与 `HORIZONS`；收益目标用**无杠杆底层** FXI（§4.5 约束 1）。
  步 3 成本折算：`120 日成本 = total_annual × (120/252)`，
     另加双边交易成本 `config.COMMISSION + config.SLIPPAGE`（一次进出）。
  步 4 判定：`净价差 = 价差 − 120 日成本 − 双边交易成本 > 0`。

⚠️ **一阶近似声明**：损耗率按年化**线性**折算到 120 日，**未建模路径依赖**
   （波动率拖累真实形态 ≈ N(N−1)/2 × σ²，随 σ 与持有期变化）。
   ⇒ 结论只能作**量级判断**，**不是**精确收益预测（同 §12.23 的纪律）。

用法：`python scripts/yinn_cost_after.py`
"""
import importlib.util
import os
import pathlib
import sys

# 输出统一 UTF-8。**为什么必须**：定时任务 / `>` 重定向会把 stdout 写进文件，
# 而 Windows 默认 cp936 ⇒ `⚠️` / `⇒` / `—` 全部变成 `??`，日志事后不可读。
# 同 `scripts/screen_yinn_momentum.py` 的做法；`hasattr` 守卫兼容被包装过的 stdout。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# `python scripts/xxx.py` 时 sys.path[0] 是 `scripts/`，**不含**仓库根 ⇒ 必须显式注入，
# 否则 `from fg_system import config` 直接 ModuleNotFoundError（实测踩到）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd                                        # noqa: E402

from fg_system import config                               # noqa: E402
from fg_system import leverage                             # noqa: E402
from fg_system.data import loader                          # noqa: E402
from fg_system.factors import screening                    # noqa: E402

# 复用 §12.35 检验 1 的因子定义、horizon 与切点。`scripts/` 不是包（无 `__init__.py`），
# 且本文件既可能被 `python scripts/...` 跑、也可能被 pytest 用 importlib 加载，
# 故按**路径**加载，不依赖 sys.path。
_SPEC = importlib.util.spec_from_file_location(
    "screen_yinn_momentum", pathlib.Path(__file__).with_name("screen_yinn_momentum.py"))
screen_yinn_momentum = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(screen_yinn_momentum)

SPLITS = screen_yinn_momentum.SPLITS

# §4.5 约束 1：收益目标与因子输入都必须是**无杠杆底层**（YINN = 3× FXI）。
UNDERLYING = config.SIGNAL_UNDERLYING_MAP["YINN"]

# 本轮只用 horizon = 120（由 §12.36 的符号稳定性**唯一确定**，不是搜索）。
HORIZON = 120

# 一次进出的双边交易成本（佣金 + 滑点），来自生产 config（不新造参数）。
def _trade_cost():
    return float(config.COMMISSION + config.SLIPPAGE)


def factor(close):
    """因子序列：**复用** §12.35 检验 1 的首选信号 `kweb_price`（同一定义才可比）。"""
    return screen_yinn_momentum.CANDIDATES[screen_yinn_momentum.PRIMARY](close)


def signal_spread(close, a=None, b=None):
    """信号价差 = 最贪婪组均值 − 最恐惧组均值（动量口径，期望**为正**）。

    `a` / `b` 给定时只用 `[a, b]` 区间内的样本（分样本内 / 外单独重算）。
    ⚠️ `screening.bucket_table` 的组号 0 = 最恐惧 … n−1 = 最贪婪；
       故 `spread` = 组号 n−1 减组号 0（**与 `screening.screen` 的 `spread` 符号相反**）。
    没有足够分组（含空组）时返回 NaN —— 退化时禁止下结论。
    """
    f = factor(close)
    fwd = screening.forward_return(close[UNDERLYING], HORIZON)
    idx = f.index
    if a is not None and b is not None:
        m = (idx >= a) & (idx <= b)
        f, fwd = f[m], fwd[m]
    tbl = screening.bucket_table(f, fwd, n_buckets=5)
    occ = tbl["n"].fillna(0) if len(tbl) else pd.Series(dtype=float)
    if len(occ) != 5 or (occ == 0).any():
        return float("nan")
    return float(tbl["mean"].iloc[-1] - tbl["mean"].iloc[0])


def net_spread(spread, total_annual, trade_cost):
    """净价差 = 价差 − 年化损耗的 120 日线性折算 − 双边交易成本。

    `120 日成本 = total_annual × (120/252)`（§12.37 步 3，**一阶近似**）。
    """
    return float(spread - total_annual * (HORIZON / 252.0) - trade_cost)


def judge(spread, total_annual, trade_cost):
    """判定：`净价差 > 0` 才算通过（要求**严格**大于 0）。

    返回 dict：`spread` / `total_annual` / `cost_120d` / `trade_cost` /
    `net_spread` / `passed`。
    """
    cost_120d = float(total_annual * (HORIZON / 252.0))
    net = net_spread(spread, total_annual, trade_cost)
    return {"spread": float(spread), "total_annual": float(total_annual),
            "cost_120d": cost_120d, "trade_cost": float(trade_cost),
            "net_spread": net, "passed": bool(net > 0)}


def _segment(und_ret, lev_ret, close, name, a=None, b=None):
    """对一段日期区间**分别**做损耗标定（步 1）与净价差判定（步 2-4）。

    §12.37 风险 2：子区间损耗不同 ⇒ 必须分样本内 / 外**分别标定**，
    只看全样本会掩盖。切点在收益序列与收盘价上**同一口径**截取。
    """
    if a is not None and b is not None:
        um = (und_ret.index >= a) & (und_ret.index <= b)
        lm = (lev_ret.index >= a) & (lev_ret.index <= b)
        und_s, lev_s = und_ret[um], lev_ret[lm]
    else:
        und_s, lev_s = und_ret, lev_ret
    loss = leverage.decompose(und_s, lev_s, n=3)
    spread = signal_spread(close, a, b)
    out = judge(spread, loss["total_annual"], _trade_cost())
    out.update({"name": name, "sigma": loss["sigma"],
                "vol_decay_annual": loss["vol_decay_annual"],
                "product_cost_annual": loss["product_cost_annual"]})
    return out


def main():
    prices = loader.load_prices(os.path.join(config.RAW_DIR, "prices.csv"))
    wide = loader.to_wide_ohlcv(prices)
    close = pd.DataFrame({s: wide[(s, "close")] for s in wide.columns.levels[0]})

    # 3× 杠杆损耗标定用的日收益：标的 FXI 与产品 YINN 各自对齐。
    und_ret = close[UNDERLYING].pct_change().dropna()
    lev_ret = close["YINN"].pct_change().dropna()

    print("=" * 100)
    print("YINN 成本后净收益取证（第 12.35 条**检验 2**：成本后净收益，§12.37 口径）")
    print("判定口径：**净价差** = 价差 − 120 日损耗 − 双边成本 > 0  "
          "（**不是** IC —— IC 是秩相关，对成本不敏感，会假通过）")
    print("信号：%s（复用 §12.35 检验 1 的定义）；horizon = %d 日（由 §12.36 符号稳定性唯一确定）"
          % (screen_yinn_momentum.PRIMARY, HORIZON))
    print("收益目标：无杠杆底层 %s（**不是** 3× 的 YINN，§4.5 约束 1）" % UNDERLYING)
    print("损耗标定：decompose(%s 日收益, YINN 日收益, n=3)" % UNDERLYING)
    print("双边交易成本（一次进出）= 佣金 %.4f + 滑点 %.4f = %.4f"
          % (config.COMMISSION, config.SLIPPAGE, _trade_cost()))
    print("数据：%s ~ %s，%d 个交易日" % (close.index.min().date(),
                                        close.index.max().date(), len(close)))
    print("=" * 100)
    print("⚠️ **一阶近似声明**：损耗按年化**线性**折算到 %d 日，未建模路径依赖"
          % HORIZON)
    print("   （波动率拖累真实形态 ≈ N(N−1)/2 × σ²，随 σ 与持有期变化）")
    print("   ⇒ 结论只作**量级判断**，**不是**精确收益预测（同 §12.23 纪律）。")
    print("=" * 100)

    segments = [("全样本", None, None)] + [(n, a, b) for n, a, b in SPLITS]
    rows = [_segment(und_ret, lev_ret, close, n, a, b) for n, a, b in segments]

    print()
    print("【步 1：杠杆损耗标定】年化（%s / YINN，n=3）" % UNDERLYING)
    print("%-8s %12s %14s %16s %14s"
          % ("区间", "σ(FXI 年化)", "波动率拖累", "产品损耗", "合计 total"))
    for r in rows:
        print("%-8s %11.2f%% %13.2f%% %15.2f%% %13.2f%%"
              % (r["name"], r["sigma"] * 100, r["vol_decay_annual"] * 100,
                 r["product_cost_annual"] * 100, r["total_annual"] * 100))

    print()
    print("【步 2-4：净价差判定】价差 = 最贪婪组均值 − 最恐惧组均值（动量口径，期望为正）")
    print("%-8s %10s %12s %12s %12s %6s"
          % ("区间", "价差", "120日成本", "双边成本", "净价差", "判定"))
    for r in rows:
        print("%-8s %9.2f%% %11.2f%% %11.4f%% %11.2f%%  %s"
              % (r["name"], r["spread"] * 100, r["cost_120d"] * 100,
                 r["trade_cost"] * 100, r["net_spread"] * 100,
                 "通过" if r["passed"] else "不通过"))

    print()
    print("【检验 2 判定】全样本与样本外**两条都过才算通过**（§12.37 判定标准）")
    full = rows[0]
    oos = rows[-1]
    if full["passed"] and oos["passed"]:
        print("  ✓ 通过：全样本净价差 %+.2f%%，样本外净价差 %+.2f%%（均 > 0）"
              % (full["net_spread"] * 100, oos["net_spread"] * 100))
    else:
        bad = [r["name"] for r in (full, oos) if not r["passed"]]
        print("  ✗ 不通过：%s 的净价差 <= 0" % "、".join(bad))
        print("    ⇒ §12.35 风险 3「3× 杠杆放大一切」**未能被价差覆盖**。")

    print()
    print("=" * 100)
    print("⚠️ 本脚本只做**检验 2**。检验 3（组合层面）/ 4（与 A2 对接）**未做**，")
    print("   故本结论**不构成**「YINN 可以纳入」。")
    print("⚠️ 正面结果**也不授权**新建市场或改规则（第 13.4 条第 1 款）—— "
          "须来自真实操作复盘。结论只能进「待观察」清单。")
    print("=" * 100)


if __name__ == "__main__":
    main()
