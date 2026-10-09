# -*- coding: utf-8 -*-
"""YINN 组合层面取证 —— 第 12.35 条**检验 3**（口径见第 12.38 条）。

================================================================================
这不是参数搜索，也**不授权**任何实现（第 13.4 条）
================================================================================
本脚本只做**三件事**，全部**零参数**（第 12.38 条「方法」表）：

1. **相关性矩阵** —— YINN（3× FXI）与现有持仓
   `GDXU / CONL / CRCG / AXTX / BTC` 的**日收益**相关；
   报告**两两相关系数**与**共同重叠区间**的起止日期与长度。
2. **边际风险贡献** —— 在**既有**权重规则 `config.WEIGHTING = "inv_vol"`
   （反比波动率 / 风险平价）下，把 YINN 作为**第 N 个资产**加进来，按**同一份预算
   归一化重新分配**（权重**由 inv_vol 自动决定**，**禁止手挑 sleeve 大小**），
   比较组合的年化波动 / 最大回撤 / Calmar。
   ⇒ 波动率用**无杠杆底层**计算（`config.SIGNAL_UNDERLYING_MAP`；YINN 的底层是
   FXI），§4C.4 纪律。底层列由 `pipeline.signal_wide` 补齐（**复用**，不重造）。
3. **对照** —— 同时报告「**不加 YINN**」的同一组指标、**同一段区间**。

**只报告，不判定**（第 12.38 条「判定」）：「是否改善组合」含**价值判断**，
归入 §12.35 检验 4（开关设计，**默认关**）。故：
  - **禁止**给出「最优权重」「Calmar 最高的组合」之类结论；
  - 本脚本的任何数字**不构成**「YINN 应当纳入」的结论。

数据缺口（第 12.38 条「数据缺口」，**先声明、不臆造**）：
  - `GDXU / AXTX / CRCG / YINN` 在 `Data/raw/prices.csv`；
  - `CONL` 在 `config.CRYPTO_PRICES_PATH`、`BTC` 在 `config.CRYPTO_UNDERLYING_PATH`；
  - 若某序列在**可用区间**不足，报告里**如实写明缺失**，**不得**用替代序列冒充；
  - `BTC` 是 7×24 现货（`crypto_underlying.csv`），与美股有约 1 交易日**相位差**
    （见 `loader.to_crypto_wide` docstring）⇒ 若相关因此失真，报告中**标注**，
    **不做相位 shift**（后移一天构成前视偏差，§10 红线）。

用法：`python scripts/yinn_portfolio_check.py`
"""
import os
import sys

# 输出统一 UTF-8。**为什么必须**：定时任务 / `>` 重定向会把 stdout 写进文件，
# 而 Windows 默认 cp936 ⇒ `⇒` / `ρ` / `—` 全部变成 `??`，日志事后不可读。
# 同 `scripts/screen_yinn_momentum.py` 的做法；`hasattr` 守卫兼容被包装过的 stdout。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# `python scripts/xxx.py` 时 sys.path[0] 是 `scripts/`，**不含**仓库根 ⇒ 必须显式注入，
# 否则 `from fg_system import config` 直接 ModuleNotFoundError（实测踩到）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                          # noqa: E402
import pandas as pd                                         # noqa: E402

from fg_system import config                                # noqa: E402
from fg_system import pipeline                              # noqa: E402
from fg_system.backtest import runner                       # noqa: E402

# 复用生产的权重函数（**禁止重造**）。此处显式绑定，便于测试断言「确为同一函数」。
risk_weight_series = pipeline.risk_weight_series

# 现有持仓（第 12.38 条第 1 步列出的五个）。**逐字照抄，不增不减。**
EXISTING_HOLDINGS = ["GDXU", "CONL", "CRCG", "AXTX", "BTC"]
# 待检验加入的标的（3× FXI）。
NEW_SYMBOL = "YINN"


def research_underlying_map():
    """研究用**无杠杆底层**映射：`config.SIGNAL_UNDERLYING_MAP` + BTC 自身。

    **为什么复用 config**：§4C.4 要求 σ 用无杠杆底层算（杠杆 ETF 自身波动含
    损耗噪声）。生产 `UNDERLYING_MAP` 只覆盖系统三个标的，故研究标的只能取
    `config.SIGNAL_UNDERLYING_MAP`（同 `analyze_shoutu_variants` 的口径）。

    `BTC` 现货杠杆的底层就是 BTC 自身（同 `config.CRYPTO_UNDERLYING["BTC"]`），
    该键不在 `SIGNAL_UNDERLYING_MAP` 里 ⇒ 在此补一条。**只补一条、不改原表。**
    """
    um = dict(config.SIGNAL_UNDERLYING_MAP)
    for s in EXISTING_HOLDINGS + [NEW_SYMBOL]:
        if s in config.CRYPTO_UNDERLYING:      # BTC ⇒ "BTC"
            um[s] = config.CRYPTO_UNDERLYING[s]
    return um


def _crypto_close(symbol, path, col="close"):
    """从加密 CSV 取单标的 close（币股 / BTC 现货**不在** `prices.csv` 里）。

    复用 `loader.to_crypto_wide` 的思路，但只取**一列**——本脚本不需要其他字段。
    两种表都支持（与 loader 一致）：
      - `crypto_prices.csv`：`date,symbol,open,...`（**长表**，按 symbol 过滤）；
      - `crypto_underlying.csv`：`date,close`（**单序列**，无 symbol 列 ⇒ 直接取）。
    """
    df = pd.read_csv(path, parse_dates=["date"])
    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str)
        sub = df[df["symbol"] == symbol]
    else:
        sub = df
    if sub.empty or col not in sub.columns:
        return pd.Series(dtype=float)
    return sub.set_index("date")[col].sort_index()


def build_research_wide():
    """组装研究用宽表：prices.csv 全部标的 + 补齐 YINN/持仓的无杠杆底层 + CONL/BTC。

    - 底层列：`pipeline.signal_wide(wide)`（复用；补 `GDXU_UND` 合成列与 `COIN`）。
    - `CONL` 自身：`config.CRYPTO_PRICES_PATH`（**不在** prices.csv）。
    - `BTC` 自身：`config.CRYPTO_UNDERLYING_PATH`（7×24 现货）。
    """
    wide = pipeline.load_wide()
    sig = pipeline.signal_wide(wide)
    # CONL 自身（币股）：从加密价格表取
    conl = _crypto_close("CONL", config.CRYPTO_PRICES_PATH)
    if not conl.empty:
        sig[("CONL", "close")] = conl.reindex(sig.index)
    # BTC 自身（现货）：从底层表取
    btc = _crypto_close("BTC", config.CRYPTO_UNDERLYING_PATH)
    if not btc.empty:
        sig[("BTC", "close")] = btc.reindex(sig.index)
    return sig.sort_index()


def close_table(wide, symbols):
    """从 MultiIndex 宽表取 `symbols` 的 close 宽表（缺列 ⇒ 省略该列，交 `missing_series` 报）。"""
    cols = {}
    for s in symbols:
        if (s, "close") in wide.columns:
            cols[s] = wide[(s, "close")].astype(float)
    return pd.DataFrame(cols, index=wide.index)


def daily_returns(close_df):
    """日收益（简单收益率）。`fill_method=None` ⇒ 缺价产生 NaN，**不得**前向填充成 0。"""
    return close_df.pct_change(fill_method=None)


def missing_series(wide, symbols, min_points=2):
    """返回**缺失或可用区间不足**的标的名（按 `symbols` 原序），**显式报告**。

    「缺失」= 没有 close 列，或有效（非 NaN）点数 < `min_points`。
    **为什么必须显式**：静默丢一只会把「少算一个资产」伪装成「组合就这样」。
    """
    out = []
    for s in symbols:
        if (s, "close") not in wide.columns:
            out.append(s)
            continue
        col = wide[(s, "close")]
        if col.notna().sum() < min_points:
            out.append(s)
    return out


def overlap_window(close_df):
    """所有列**共同有值**的区间：返回 `(start, end, n)`；无重叠 ⇒ `(NaT, NaT, 0)`。"""
    valid = close_df.dropna(how="any")
    if valid.empty:
        return pd.NaT, pd.NaT, 0
    return valid.index.min(), valid.index.max(), int(len(valid))


def pairwise_overlap(close_df):
    """两两**共同重叠区间**的起止与长度（第 12.38 条第 1 步要求）。

    返回 DataFrame，行 = `(左, 右)` 有序对，列 = `start / end / n`。
    """
    cols = list(close_df.columns)
    rows = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            m = close_df[[a, b]].dropna()
            rows.append({"left": a, "right": b,
                         "start": m.index.min() if len(m) else pd.NaT,
                         "end": m.index.max() if len(m) else pd.NaT,
                         "n": int(len(m))})
    return pd.DataFrame(rows, columns=["left", "right", "start", "end", "n"])


def pairwise_correlation(close_df):
    """两两相关系数（**各自最大重叠区间**）—— 第 12.38 条第 1 步要求的「两两相关系数」。

    ⚠️ **为什么不能只看全体交集**：`AXTX` 只有 108 行 ⇒ 全体交集被压到 **103 日**
    （< σ 窗口 252）⇒ 那个矩阵的样本**极短**。两两口径能用上每对的**全部**重叠
    （`BTC`–`YINN` 达 **2509 日**）⇒ 两张表必须**并列**看，不能只报一张。

    返回 DataFrame：`left / right / start / end / n / rho`。
    """
    cols = list(close_df.columns)
    rows = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            sub = close_df[[a, b]].dropna()
            n = int(len(sub))
            rho = float(daily_returns(sub).corr().loc[a, b]) if n >= 2 else float("nan")
            rows.append({"left": a, "right": b,
                         "start": sub.index.min() if n else pd.NaT,
                         "end": sub.index.max() if n else pd.NaT,
                         "n": n, "rho": rho})
    return pd.DataFrame(rows, columns=["left", "right", "start", "end", "n", "rho"])


def underpowered_series(wide, symbols, window=None):
    """有效点数**不足** `window`（默认 σ 窗口 `VOL_WEIGHT_WINDOW`）的标的名。

    **为什么需要**：`inv_vol` 的 σ 要 252 日；不足时 `risk_weight_series` 会
    **静默退化为等权**（§4C.6）⇒ 把这类标的混进面板，会让「风险平价」的结论**变假** ✗。

    ⚠️ 这是**数据可用性**判据（客观、**事前**可声明），**不是**按业绩挑标的 ✗。
    """
    window = config.VOL_WEIGHT_WINDOW if window is None else window
    out = []
    for s in symbols:
        if (s, "close") not in wide.columns:
            out.append(s)
            continue
        if int(wide[(s, "close")].notna().sum()) < window:
            out.append(s)
    return out


def is_equal_weight(weights):
    """权重是否**全相等**（= `inv_vol` 已退化为等权，§4C.6）。

    **必须显式判定**：退化时权重表看起来「很整齐」，容易被读成「风险平价算出来的」
    ✗ —— 那是**假结论**。容忍浮点误差。
    """
    w = pd.Series(weights).dropna()
    if len(w) < 2:
        return False
    return bool(float(w.max() - w.min()) < 1e-9)


def correlation_table(close_df):
    """日收益相关矩阵 + 共同重叠区间。

    返回 dict：
      - `corr`  —— DataFrame（在**共同重叠区间**上算 Pearson 相关）
      - `start` / `end` / `n` —— 该重叠区间的起止与长度
    """
    start, end, n = overlap_window(close_df)
    window = close_df.loc[start:end] if n else close_df.iloc[:0]
    corr = daily_returns(window).corr()
    return {"corr": corr, "start": start, "end": end, "n": n}


def inv_vol_weights(wide, symbols, underlying_map, window=None):
    """反比波动率（风险平价）权重 —— **直接复用** `pipeline.risk_weight_series`。

    **禁止**在此重造一套公式（第 12.38 条：不新造权重规则）；本函数只是绑定
    `config.WEIGHTING`（默认 `inv_vol`）并透传参数的**薄壳**。
    """
    return risk_weight_series(wide, symbols=list(symbols),
                              window=window, weighting=config.WEIGHTING,
                              underlying_map=underlying_map)


def portfolio_metrics(wide, symbols, underlying_map, window=None):
    """组合级指标（第 12.38 条第 2 步），权重由 **inv_vol 自动决定**。

    口径（**必须理解，否则数字不可比**）：
      - 权重 = 各标的滚动 `inv_vol` 权重（**同一份预算归一化**，Σw=1）；
      - 组合日收益 = `Σ w_i,t × r_i,t`（`pipeline.weighted_basket_returns`，
        等价于每日再平衡到目标权重的篮子）；
      - 指标由 `runner.performance_metrics` 给出（年化波动 / 最大回撤 / Calmar）。
      - 评估区间 = `window`（不传则取 `symbols` **全体**的共同重叠区间）。

    ⚠️ **不含 `FgStrategy` 的仓位开关**（趋势过滤 / 五档 / 极端规则）—— 本函数
    测的是「**加权篮子本身**的风险」= 权重规则带来的**边际风险贡献**，
    这正是第 12.38 条第 2 步要问的问题；叠加策略会引入第二个自由度。

    返回 dict：`annual_return / annual_vol / max_drawdown / calmar / sharpe /
    weights(末值) / start / end / n`。
    """
    close = close_table(wide, symbols)
    if window is None:
        start, end, _n = overlap_window(close)
    else:
        start, end = window[0], window[1]
    span = close.loc[start:end] if (start is not pd.NaT and end is not pd.NaT) \
        else close.iloc[:0]
    n = int(len(span))
    if n == 0 or len(close.columns) < 2:
        return {"annual_return": float("nan"), "annual_vol": float("nan"),
                "max_drawdown": float("nan"), "calmar": float("nan"),
                "sharpe": float("nan"), "weights": pd.Series(dtype=float),
                "start": start, "end": end, "n": 0}
    # 权重序列（只取评估区间，逐日 ffill）；weighted_basket_returns 内部会把
    # 「标的当日无数据」的权重重新归一化，不把缺失当 0 收益。
    w = inv_vol_weights(wide, symbols, underlying_map).reindex(close.index).ffill()
    rets = pipeline.weighted_basket_returns(wide, w, symbols=symbols)
    rets = rets.loc[start:end].dropna()
    m = runner.performance_metrics(rets)
    m["weights"] = w.iloc[-1]
    m["start"] = start
    m["end"] = end
    m["n"] = n
    return m


def _pct(x):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else "%.2f%%" % (x * 100)


def _fmt(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else ("%.*f" % (nd, x))


def main():
    wide = build_research_wide()
    um = research_underlying_map()
    all_syms = EXISTING_HOLDINGS + [NEW_SYMBOL]

    print("=" * 100)
    print("YINN 组合层面取证（第 12.35 条**检验 3**，第 12.38 条口径）")
    print("只报告，不判定：「是否改善组合」含价值判断，归 §12.35 检验 4（开关默认关）。")
    print("=" * 100)

    # ---- 数据缺口（先声明，不臆造） ----
    miss = missing_series(wide, all_syms)
    print()
    print("【数据缺口声明】")
    for s in all_syms:
        col = wide[(s, "close")] if (s, "close") in wide.columns else None
        if col is None:
            print("  ✗ %-6s 无 close 列（缺失）" % s)
            continue
        v = col.dropna()
        print("  ✓ %-6s %4d 行  %s ~ %s  底层=%s"
              % (s, len(v),
                 v.index.min().date() if len(v) else "-",
                 v.index.max().date() if len(v) else "-",
                 um.get(s, "?")))
    if miss:
        print("  ⚠️ **缺失/可用区间不足**：%s ⇒ 下面的组合口径**已剔除**它们，"
              "不得用替代序列冒充（第 12.38 条）。" % "、".join(miss))
    else:
        print("  ✅ 六个序列均有数据。")
    # BTC 相位差标注（不静默对齐）
    if "BTC" in wide.columns.get_level_values(0):
        print("  ⚠️ **BTC 相位差标注**：BTC 现货（7×24 日均价）与美股 ETF 日收益存在约"
              " 1 交易日相位差（loader.to_crypto_wide docstring）⇒ 与 BTC 的相关系数"
              "**偏低失真**。**不做**相位 shift（后移一天 = 前视偏差，§10 红线）。")

    # ---- 步骤 1：相关性矩阵（仅在有数据的标的上算）----
    usable = [s for s in all_syms if s not in miss]
    close = close_table(wide, usable)
    ct = correlation_table(close)
    print()
    print("=" * 100)
    print("【步骤 1】日收益相关性矩阵（YINN 3× FXI vs 现有持仓）")
    print("共同重叠区间：%s ~ %s，共 %d 个交易日（全体序列交集）"
          % (ct["start"].date() if ct["n"] else "-",
             ct["end"].date() if ct["n"] else "-", ct["n"]))
    print()
    c = ct["corr"]
    # markdown 表
    print("| | " + " | ".join(c.columns) + " |")
    print("|---|" + "|".join(["---"] * len(c.columns)) + "|")
    for i in c.index:
        print("| %s | " % i + " | ".join(_fmt(c.loc[i, j], 3) for j in c.columns) + " |")

    print()
    print("两两共同重叠区间（起止 + 长度）：")
    print("  %-6s %-6s %-12s %-12s %8s" % ("左", "右", "起", "止", "长度"))
    for _, r in pairwise_overlap(close).iterrows():
        print("  %-6s %-6s %-12s %-12s %8d"
              % (r["left"], r["right"],
                 r["start"].date() if pd.notna(r["start"]) else "-",
                 r["end"].date() if pd.notna(r["end"]) else "-", r["n"]))

    print()
    print("两两相关系数（**各自最大重叠区间** —— 样本远大于上面的全体交集，必须并列看）：")
    print("  %-6s %-6s %-12s %-12s %8s %8s" % ("左", "右", "起", "止", "长度", "rho"))
    for _, r in pairwise_correlation(close).iterrows():
        print("  %-6s %-6s %-12s %-12s %8d %8s"
              % (r["left"], r["right"],
                 r["start"].date() if pd.notna(r["start"]) else "-",
                 r["end"].date() if pd.notna(r["end"]) else "-",
                 r["n"], _fmt(r["rho"])))

    # ---- 步骤 2 / 3：边际风险贡献 + 对照（同一区间）----
    # 区间统一取「现有持仓 + YINN」的交集，两条口径**逐字相同**（第 12.38 条第 3 步）。
    win = overlap_window(close_table(wide, usable))
    syms_no = [s for s in EXISTING_HOLDINGS if s not in miss]
    syms_yes = syms_no + [NEW_SYMBOL]

    print()
    print("=" * 100)
    print("【步骤 2 / 3】边际风险贡献（inv_vol 自动分配权重）与「不加 YINN」对照")
    print("权重规则：config.WEIGHTING = %r（既有规则，**未新造**）；σ 用无杠杆底层"
          "（§4C.4）" % config.WEIGHTING)
    print("评估区间（两口径同一段）：%s ~ %s"
          % (win[0].date() if win[2] else "-", win[1].date() if win[2] else "-"))

    out_no = portfolio_metrics(wide, syms_no, um, window=(win[0], win[1]))
    out_yes = portfolio_metrics(wide, syms_yes, um, window=(win[0], win[1]))

    print()
    print("组合指标对照：")
    print("  %-16s %14s %14s %10s" % ("口径", "年化波动", "最大回撤", "Calmar"))
    print("  %-16s %14s %14s %10s"
          % ("不加 YINN", _pct(out_no["annual_vol"]),
             _pct(out_no["max_drawdown"]), _fmt(out_no["calmar"])))
    print("  %-16s %14s %14s %10s"
          % ("加 YINN", _pct(out_yes["annual_vol"]),
             _pct(out_yes["max_drawdown"]), _fmt(out_yes["calmar"])))
    print("  （Calmar = 年化收益 / |最大回撤|；年化收益：不加 %s / 加 %s）"
          % (_pct(out_no["annual_return"]), _pct(out_yes["annual_return"])))

    print()
    print("inv_vol 自动分配出的**末值**权重（Σw=1，每日再平衡口径）：")
    print("  %-8s %12s %12s" % ("标的", "不加 YINN", "加 YINN"))
    for s in syms_yes:
        wn = out_no["weights"].get(s, float("nan"))
        wy = out_yes["weights"].get(s, float("nan"))
        print("  %-8s %11s %11s"
              % (s, "%.2f%%" % (wn * 100) if not np.isnan(wn) else "n/a",
                 "%.2f%%" % (wy * 100) if not np.isnan(wy) else "n/a"))
    if win[2] < config.VOL_WEIGHT_WINDOW:
        print("  ⚠️ 重叠区间 %d 日 < σ 窗口 %d 日 ⇒ inv_vol **退化为等权**（§4C.6），"
              "上述权重即等权，不是风险平价的真值。" % (win[2], config.VOL_WEIGHT_WINDOW))
    if is_equal_weight(out_yes["weights"]):
        print("  ⚠️ 权重**全相等** ⇒ 本面板的权重是**等权**，**不是**风险平价结果 ✗"
              "（原因：至少一个标的的底层 σ 不足 %d 日）。" % config.VOL_WEIGHT_WINDOW)

    # ---- 补充面板：剔除「有效点数 < σ 窗口」的标的 ----
    # **判据是数据可用性**（客观、事前可声明），**不是**按业绩挑标的；
    # 判定标准与上面**完全相同**（同一段区间、同一权重规则、同一指标）。
    weak = underpowered_series(wide, usable)
    print()
    print("=" * 100)
    print("【补充面板】剔除有效点数 < σ 窗口(%d) 的标的：%s"
          % (config.VOL_WEIGHT_WINDOW, "、".join(weak) if weak else "（无）"))
    print("⚠️ 判据是**数据可用性**（客观、事前声明），**不是**按业绩挑标的 ✗；"
          "判定标准与主面板**逐字相同**。")
    strong = [s for s in usable if s not in weak]
    win2 = overlap_window(close_table(wide, strong))
    if len(strong) >= 2 and win2[2] >= 2:
        no2 = [s for s in EXISTING_HOLDINGS if s in strong]
        yes2 = no2 + [NEW_SYMBOL]
        print("评估区间（两口径同一段）：%s ~ %s，共 %d 日"
              % (win2[0].date(), win2[1].date(), win2[2]))
        a2 = portfolio_metrics(wide, no2, um, window=(win2[0], win2[1]))
        b2 = portfolio_metrics(wide, yes2, um, window=(win2[0], win2[1]))
        print("  %-16s %14s %14s %10s %14s"
              % ("口径", "年化波动", "最大回撤", "Calmar", "年化收益"))
        for nm, o in (("不加 YINN", a2), ("加 YINN", b2)):
            print("  %-16s %14s %14s %10s %14s"
                  % (nm, _pct(o["annual_vol"]), _pct(o["max_drawdown"]),
                     _fmt(o["calmar"]), _pct(o["annual_return"])))
        print("  权重（末值）：" + " / ".join(
            "%s %.2f%%" % (s, w * 100) for s, w in b2["weights"].items()))
        if is_equal_weight(b2["weights"]):
            print("  ⚠️ 权重**全相等** ⇒ 该面板仍是**等权**，inv_vol 仍退化 ✗"
                  "（σ 窗口 %d 日不足）。" % config.VOL_WEIGHT_WINDOW)
    else:
        print("  可用标的 < 2 ⇒ 不做（**不臆造**，第 12.38 条）。")

    print()
    print("=" * 100)
    print("⚠️ 本脚本**只报告**（ρ、边际风险贡献、组合指标变化）。")
    print("⚠️ **不判定**「是否改善组合」—— 那是价值判断（用波动换收益的取舍），"
          "归 §12.35 检验 4（开关设计，**默认关**）。")
    print("⚠️ **禁止**把上表任何一列读成「最优权重」或「Calmar 最高的组合」"
          "（那是对历史路径的拟合，§12.11）。")
    print("=" * 100)


if __name__ == "__main__":
    main()
