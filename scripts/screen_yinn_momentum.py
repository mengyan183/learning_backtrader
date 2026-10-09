# -*- coding: utf-8 -*-
"""YINN 动量取证 —— 第 12.35 条**检验 1**：方向反转的稳定性。

================================================================================
这不是参数搜索，也**不授权**任何实现（第 13.4 条）
================================================================================
1. 检验的是**先验的反面**：§12.17 用「情绪高 → 未来收益低」（逆向）否证了中国股票；
   本轮改测「**情绪高 → 未来收益高**」（动量），即期望 **IC > 0**。
2. 判定口径：**全样本 + 样本内 + 样本外三段 IC 全为正**，且**非退化**。
   重点看**样本外**（2023-01 起）—— §12.17 已知弱点：`kweb_price` 样本外仅 +0.109。
3. **负面结果 = 永久关闭该问题**；**正面结果也不授权新建市场 / 改规则** ——
   按第 13.4 条第 1 款，须来自**真实操作的复盘**。本条结论只能进「待观察」清单。
4. 本轮**只做检验 1**。检验 2（成本后净收益）/ 3（组合层面）/ 4（与 A2 对接）**未做**，
   故本脚本的正面结论**不构成**「YINN 可以纳入」的结论。

工具复用：因子定义、horizon、子区间切点**直接取自** `scripts/screen_factors.py` ——
换定义或换切点会让数字与 §12.17 **不可比**（**不要**复制一份到本文件）。

用法：`python scripts/screen_yinn_momentum.py`
"""
import importlib.util
import os
import pathlib
import sys

# 输出统一 UTF-8。**为什么必须**：定时任务 / `>` 重定向会把 stdout 写进文件，
# 而 Windows 默认 cp936 ⇒ `⚠️` / `⇒` / `—` 全部变成 `??`，日志事后不可读。
# 同 `scripts/analyze_shoutu_variants.py` 的做法；`hasattr` 守卫兼容被包装过的 stdout。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# `python scripts/xxx.py` 时 sys.path[0] 是 `scripts/`，**不含**仓库根 ⇒ 必须显式注入，
# 否则 `from fg_system import config` 直接 ModuleNotFoundError（实测踩到）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd                                        # noqa: E402

from fg_system import config                               # noqa: E402
from fg_system.data import loader                          # noqa: E402
from fg_system.factors import screening                    # noqa: E402

# 复用 §12.17 的因子定义与切点。`scripts/` 不是包（无 `__init__.py`），
# 且本文件既可能被 `python scripts/...` 跑、也可能被 pytest 用 importlib 加载，
# 故按**路径**加载，不依赖 sys.path。
_SPEC = importlib.util.spec_from_file_location(
    "screen_factors", pathlib.Path(__file__).with_name("screen_factors.py"))
screen_factors = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(screen_factors)

HORIZONS = screen_factors.HORIZONS
SPLITS = screen_factors.SPLITS

# §4.5 约束 1：收益目标与因子输入都必须是**无杠杆底层**（YINN = 3× FXI）。
UNDERLYING = config.SIGNAL_UNDERLYING_MAP["YINN"]

# §12.35「候选信号」列出的三个，**只此三个**（再扩就是参数搜索）。
CANDIDATES = {
    "kweb_price": lambda c: screen_factors.price_composite(c["KWEB"]),
    "mchi_price": lambda c: screen_factors.price_composite(c["MCHI"]),
    "fxi_price": lambda c: screen_factors.price_composite(c["FXI"]),
}
# §12.35 的首选信号（由 §12.17 的历史数据选定，**不是**本脚本挑选的）。
PRIMARY = "kweb_price"


def momentum_screen(factor, fwd, splits=None, n_buckets=5):
    """动量方向判定：把 `screening.screen` 的同一批数字换成**期望符号为正**。

    通过条件（`passed`）**两条同时成立**：
    1. `stable_positive` —— 全样本与**每个**子区间的 IC 都**非 NaN 且 > 0**
       （§12.35 检验 1：符号稳定性，重点在样本外）；
    2. **非退化** —— 有组为空时 IC 是伪影（`screening.screen` 已记录该陷阱），
       方向再"对"也不能算通过。

    返回 dict：
    - `ic` / `ic_splits`  全样本 IC；`ic_splits` = [("全样本", IC), (区间名, IC), ...]
      （「全样本」也在其中，符号稳定性是**三段一起**判的）
    - `stable_positive`   三段是否全为正
    - `degenerate`        是否退化（有组为空）
    - `passed`            `stable_positive and not degenerate`
    - `mono` / `spread` / `hit` / `n` / `table`   沿用 `screening.screen` 的口径。
      ⚠️ 动量口径下 `spread`（恐惧组 − 贪婪组）期望 **< 0**，
      `hit`（P(恐惧 > 贪婪)）期望 **< 0.5** —— 与逆向口径**符号相反**。

    ⚠️ 幅度**不是**显著性：horizon > 1 时样本高度重叠。本函数只回答方向问题。
    """
    splits = SPLITS if splits is None else splits
    out = screening.screen(factor, fwd, n_buckets=n_buckets)
    ics = [("全样本", out["ic"])]
    for name, a, b in splits:
        m = (factor.index >= a) & (factor.index <= b)
        ics.append((name, screening.spearman_ic(factor[m], fwd[m])))
    vals = [ic for _, ic in ics]
    stable_positive = bool(vals) and all(
        (not pd.isna(v)) and v > 0 for v in vals)
    return {"ic": out["ic"], "ic_splits": ics,
            "stable_positive": stable_positive,
            "degenerate": out["degenerate"],
            "passed": bool(stable_positive and not out["degenerate"]),
            "mono": out["mono"], "spread": out["spread"], "hit": out["hit"],
            "n": out["n"],
            "table": out["table"]}


def _verdict(out):
    if out["degenerate"]:
        return "不通过（退化：有组为空 ⇒ IC 是伪影）"
    if not out["stable_positive"]:
        bad = [n for n, ic in out["ic_splits"] if pd.isna(ic) or ic <= 0]
        return "不通过（符号不稳定：%s）" % "、".join(bad)
    return "通过（三段全为正）"


def main():
    prices = loader.load_prices(os.path.join(config.RAW_DIR, "prices.csv"))
    wide = loader.to_wide_ohlcv(prices)
    close = pd.DataFrame({s: wide[(s, "close")] for s in wide.columns.levels[0]})

    print("=" * 100)
    print("YINN 动量取证（第 12.35 条**检验 1**：方向反转的稳定性）")
    print("先验（与 §12.17 相反）：因子高（贪婪）→ 未来 N 日收益**高**"
          "  ⇒  期望 IC > 0、spread < 0、hit < 0.5")
    print("收益目标：无杠杆底层 %s（**不是** 3× 的 YINN，§4.5 约束 1）" % UNDERLYING)
    print("数据：%s ~ %s，%d 个交易日；滚动分位窗口 %d 日；horizon %s 日"
          % (close.index.min().date(), close.index.max().date(), len(close),
             config.RANK_WINDOW, HORIZONS))
    print("=" * 100)

    rows = []
    print("%-12s %5s %9s %9s %9s %7s %9s %7s %6s  %s"
          % ("因子", "horiz", "IC", SPLITS[0][0], SPLITS[1][0],
             "单调", "spread", "hit", "n", "判定"))
    for fname, fn in CANDIDATES.items():
        f = fn(close)
        for h in HORIZONS:
            fwd = screening.forward_return(close[UNDERLYING], h)
            out = momentum_screen(f, fwd)
            ics = dict(out["ic_splits"])
            print("%-12s %5d %9.3f %9.3f %9.3f %7.2f %8.2f%% %7.3f %6d  %s"
                  % (fname, h, out["ic"], ics[SPLITS[0][0]], ics[SPLITS[1][0]],
                     out["mono"], out["spread"] * 100, out["hit"], out["n"],
                     _verdict(out)))
            rows.append((fname, h, out))

    print()
    print("【检验 1 汇总】")
    ok = [(f, h, o) for f, h, o in rows if o["passed"]]
    if ok:
        for f, h, o in ok:
            ics = dict(o["ic_splits"])
            print("  ✓ %s / %d 日：全样本 %+.3f，样本外 %+.3f（= 全样本的 %.0f%%）"
                  % (f, h, o["ic"], ics[SPLITS[1][0]],
                     100.0 * ics[SPLITS[1][0]] / o["ic"] if o["ic"] else float("nan")))
    else:
        print("  ✗ 无候选通过 —— 按 §12.17「两个负面结论 = 永久关闭该问题」处理")

    print()
    print("【首选 %s 的分组明细】horizon 120 日（首选由 §12.17 选定，非本轮挑选）"
          % PRIMARY)
    f = CANDIDATES[PRIMARY](close)
    out = momentum_screen(f, screening.forward_return(close[UNDERLYING], 120))
    print("  组号 0 = 最恐惧 … 4 = 最贪婪；动量口径下组均值应**递增**")
    print("  " + out["table"].to_string().replace("\n", "\n  "))

    print()
    print("=" * 100)
    print("⚠️ 本脚本只做**检验 1**（方向稳定性）。检验 2（成本后净收益）/ 3（组合层面）"
          "/ 4（与 A2 对接）**未做**。")
    print("⚠️ 正面结论**不授权**新建市场或改规则（第 13.4 条第 1 款）—— "
          "须来自真实操作复盘。结论只能进「待观察」清单。")
    print("=" * 100)


if __name__ == "__main__":
    main()
