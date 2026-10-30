# -*- coding: utf-8 -*-
"""风控与趋势结构工具（知识库沉淀落地 P1/P4/P5）。

数据源：Data/raw/prices.csv 长表（date,symbol,open,high,low,close,volume）。
全部函数对数据不足/缺失返回 None，不阻塞展示。

规则来源（知识库 9 频道归纳，见 docs/kb-insights.md）：
- P1 单笔风险：先定风险金额（账户净值 1%）再反推仓位（RaynerTeo《The Math
  Behind Profitable Trading》）；止损距离 = 2×ATR20（下限 3%，防过度集中）。
- P4 趋势结构：200 日均线方向 + 近 20 日支撑/阻力带（价格行为派）。
- P5 风险标签：杠杆 ETF 衰减/清算风险（BenFelix）、加密现货杠杆。
"""
import pandas as pd

from fg_system import config


def _sym_rows(prices_df, sym):
    """长表 prices 按 symbol 过滤并按日期升序；异常返回空表。"""
    if prices_df is None or prices_df.empty:
        return pd.DataFrame()
    try:
        d = (prices_df[prices_df["symbol"] == sym]
             .dropna(subset=["close"]).sort_values("date"))
    except Exception:
        return pd.DataFrame()
    return d


def atr(prices_df, sym, n=20):
    """ATR(n)：最后一日的 n 日均真实波幅；数据不足返回 None。"""
    d = _sym_rows(prices_df, sym)
    if len(d) < n + 1:
        return None
    prev = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"],
                    (d["high"] - prev).abs(),
                    (d["low"] - prev).abs()], axis=1).max(axis=1)
    return float(tr.iloc[-n:].mean())


def ma(prices_df, sym, n=200):
    """简单移动平均（最近 n 日收盘）；数据不足返回 None。"""
    d = _sym_rows(prices_df, sym)
    if len(d) < n:
        return None
    return float(d["close"].iloc[-n:].mean())


def support_resistance(prices_df, sym, n=20):
    """近 n 日支撑（最低）与阻力（最高）；无数据返回 (None, None)。"""
    d = _sym_rows(prices_df, sym)
    if len(d) < 1:
        return None, None
    dd = d.iloc[-min(n, len(d)):]
    try:
        return float(dd["low"].min()), float(dd["high"].max())
    except Exception:
        return None, None


def atr_pct(prices_df, sym, price, n=20, stop_mult=2.0, floor=0.03, fallback=0.06):
    """单笔止损距离（%）：2×ATR20 / 现价，下限 3%；ATR 或价格缺失 → 6% 保守默认。"""
    a = atr(prices_df, sym, n=n)
    if a and price:
        pct = max(stop_mult * a / price, floor)
        return pct
    return fallback


def atr_pct_underlying(prices_df, sym, n=20, stop_mult=2.0,
                       floor=0.03, fallback=None):
    """**底层（正股）**的 ATR%，无映射/取不到 ⇒ `fallback`（默认 None，不猜 ✗）。

    用于建仓间距：`position_plan.gap_pct()` 自己会乘杠杆 ✓
    ⇒ 这里**必须**给未加杠杆的底层值，否则杠杆被乘两次 ✗。
    """
    from fg_system import config as _cfg

    und = _cfg.SIGNAL_UNDERLYING_MAP.get(str(sym or ""))
    if not und or str(und).endswith("_UND"):
        return fallback
    rows = _sym_rows(prices_df, und)
    if len(rows) < n + 1:
        return fallback
    return atr_pct(prices_df, und, float(rows["close"].iloc[-1]), n=n,
                   stop_mult=stop_mult, floor=floor,
                   fallback=fallback if fallback is not None else 0.06)


def atr_pct_effective(prices_df, sym, price=None, n=20, stop_mult=2.0,
                      floor=0.03, fallback=0.06):
    """杠杆 ETF 的**有效**止损距离：**底层 ATR × 杠杆倍数** ✓（纪律 4C.4）。

    为什么不用 ETF 自身 ATR ✗：
      含 vol decay / 费用 / 融资 / 跟踪误差噪声 ✗ —— 纪律 4C.4 明令禁止 ✗。
    为什么也不直接用底层 ATR ✗：
      3x 标的的实际敞口是底层的 3 倍，直接用会**低估风险 3 倍** ✗
      （上限被放宽 3 倍 ⇒ 悄悄放松风控 ✗）。
    ⇒ 底层 ATR × L：保留真实波动幅度、去掉噪声 ✓。

    非杠杆标的 / 无底层映射 / 底层取不到价 ⇒ 回落到自身 ATR ✓（不猜 ✗）。
    """
    from fg_system import config as _cfg
    from fg_system import position_plan as _pp

    lev = _pp.leverage_of(sym)
    und = _cfg.SIGNAL_UNDERLYING_MAP.get(str(sym or ""))
    if lev <= 1 or not und or str(und).endswith("_UND"):
        return atr_pct(prices_df, sym, price, n=n, stop_mult=stop_mult,
                       floor=floor, fallback=fallback)
    rows = _sym_rows(prices_df, und)
    if len(rows) < n + 1:
        return atr_pct(prices_df, sym, price, n=n, stop_mult=stop_mult,
                       floor=floor, fallback=fallback)
    und_px = float(rows["close"].iloc[-1])
    base = atr_pct(prices_df, und, und_px, n=n, stop_mult=stop_mult,
                   floor=floor, fallback=fallback)
    return base * lev


def position_limit(net_value, mv, atr_pct_val, risk_pct=0.01):
    """1% 风险规则的仓位上限：建议市值上限 = 净值×风险% / 止损距离%。

    返回 (上限市值, 当前市值/上限 比值)；缺输入返回 (None, None)。
    """
    if not net_value or not mv or not atr_pct_val:
        return None, None
    limit = net_value * risk_pct / atr_pct_val
    return limit, (mv / limit if limit > 0 else None)


def trend_tags(prices_df, sym, price):
    """P4 趋势结构：200 日均线方向 + 近 20 日支撑/阻力。

    返回 dict(ma200, above, support, resistance)；数据不足返回 None。
    """
    m = ma(prices_df, sym, 200)
    s, r = support_resistance(prices_df, sym, 20)
    if m is None or price is None:
        return None
    return {"ma200": m, "above": price >= m, "support": s, "resistance": r}


# 杠杆 ETF 白名单（持仓可能出现的）：3×/2× 品种，衰减+清算双重风险
LEVERAGED_SYMS = {
    "TQQQ", "SOXL", "UPRO",            # 3× 美股大盘
    "YINN", "GDXU", "AXTX",            # 3×/2× 主题（中国/金矿/AXTI）
    "CONL", "CRCG",                    # 2× 加密相关
    "BITX", "BITU", "MSTX", "MSTU",    # 2× 加密
}


def risk_tags(sym, name):
    """P5 风险标签：杠杆 ETF（衰减/清算）、加密现货杠杆。返回 [(label, mark)]。

    规则：白名单命中或名称含杠杆特征 → 杠杆 ETF；
    config.CRYPTO_LEVERAGE 命中或 -USDT 后缀 → 加密杠杆。
    """
    tags = []
    sym_u = str(sym or "").upper()
    name_l = str(name or "").lower()
    if (sym_u in LEVERAGED_SYMS or "leveraged" in name_l
            or "倍做多" in name_l or "3x" in name_l or "2x" in name_l):
        tags.append(("杠杆ETF·衰减清算", "⚠"))
    if sym_u in config.CRYPTO_LEVERAGE or sym_u.endswith("-USDT"):
        tags.append(("加密现货杠杆", "⚠"))
    return tags


# ---------------------------------------------------------------------------
# L3.2 组合风险度量（M2.1 承接）：尾部指标 VaR/CVaR + HRP 参考权重（纯 numpy）
# 纪律：优化器输出仅是参考建议，不得绕过指令卡/人工审批（第 1、8 条）。
# ---------------------------------------------------------------------------

import numpy as np  # noqa: E402


def var(returns, alpha=0.05):
    """历史模拟 VaR：收益分布 alpha 分位（负值=损失）。数据不足返回 None。"""
    if returns is None or len(returns) == 0:
        return None
    s = returns.dropna()
    if len(s) < 30:
        return None
    return float(np.percentile(s.values, alpha * 100))


def cvar(returns, alpha=0.05):
    """历史模拟 CVaR：尾部（<=VaR）期望损失。数据不足返回 None。"""
    if returns is None or len(returns) == 0:
        return None
    s = returns.dropna()
    if len(s) < 30:
        return None
    v = np.percentile(s.values, alpha * 100)
    tail = s.values[s.values <= v]
    return float(np.mean(tail)) if len(tail) else float(v)


def max_drawdown(returns):
    """最大回撤（收益序列）。数据不足（<2 点）返回 None。"""
    if returns is None or len(returns) == 0:
        return None
    s = returns.dropna()
    if len(s) < 2:
        return None
    nav = (1.0 + s).cumprod()
    peak = np.maximum.accumulate(nav)
    return float(((nav - peak) / peak).min())


def hrp_weights(returns, linkage="single"):
    """分层风险平价（HRP）参考权重：相关矩阵层次聚类 → 递归二分 → 逆方差。

    scipy 层次聚类（单连接），纯 numpy 权重计算；样本不足回退等权。
    二分严格沿**聚类树结构**：从根节点起，按每行的左右孩子递归拆分
    （不再用 fcluster 的全局簇号——子集递归时全局簇号会与 loc 错位，
    导致静默退化为等分、权重失真）。
    输出仅是参考建议（纪律：不得绕过指令卡/人工审批）。
    """
    from scipy.cluster import hierarchy
    s = returns.dropna()
    if len(s) < 30 or s.shape[1] < 2:
        return {c: 1.0 / s.shape[1] for c in s.columns} if s.shape[1] else {}
    corr = s.corr().fillna(0.0).values
    dist = np.sqrt(np.maximum(0.0, (1.0 - corr) / 2.0))
    n_leaves = len(s.columns)
    Z = hierarchy.linkage(dist[np.triu_indices(n_leaves, k=1)],
                          method=linkage)
    labels = s.columns
    inv = np.diag(np.linalg.pinv(s.cov().fillna(0.0).values))

    def _leaves(node):
        """树节点覆盖的叶子索引集合（叶子 0..n-1，内部节点 n+r）。"""
        if node < n_leaves:
            return [int(node)]
        r = int(node) - n_leaves
        return _leaves(Z[r, 0]) + _leaves(Z[r, 1])

    def _recursive(w, node):
        if node < n_leaves:  # 叶子
            w[int(node)] = 1.0
            return
        r = int(node) - n_leaves
        # 直接读树结构的两个孩子 → 与 idxs 子集严格对应（不再用全局簇号）
        left = _leaves(Z[r, 0])
        right = _leaves(Z[r, 1])
        wl = np.sum(inv[left]) if inv[left].sum() else 1.0
        wr = np.sum(inv[right]) if inv[right].sum() else 1.0
        alpha = wl / (wl + wr)
        _recursive(w, Z[r, 0])
        _recursive(w, Z[r, 1])
        for k in left:
            w[k] *= alpha
        for k in right:
            w[k] *= (1.0 - alpha)

    w = {}
    _recursive(w, n_leaves + len(Z) - 1)  # 从全局根节点起递归二分
    total = sum(w.values())
    return {labels[k]: float(w[k] / total) for k in w}


def risk_report(returns_df, weights=None):
    """组合尾部风险报告：单资产 + 组合的 VaR/CVaR/年化波动/最大回撤。

    returns_df: 收益 DataFrame（列=资产）；weights: 组合权重 dict（默认等权）。
    """
    if returns_df is None or returns_df.empty:
        return {}
    cols = list(returns_df.columns)
    n = len(cols)
    w = weights or {c: 1.0 / n for c in cols}
    comb = sum(w[c] * returns_df[c].fillna(0.0) for c in cols)
    annual = 252 ** 0.5
    out = {"assets": {}}
    for c in cols:
        r = returns_df[c]
        out["assets"][c] = {
            "var95": var(r), "cvar95": cvar(r),
            "annual_vol": float(r.dropna().std() * annual) if len(r.dropna()) > 1 else None,
            "max_drawdown": max_drawdown(r),
        }
    out["portfolio"] = {
        "var95": var(comb), "cvar95": cvar(comb),
        "annual_vol": float(comb.dropna().std() * annual) if len(comb.dropna()) > 1 else None,
        "max_drawdown": max_drawdown(comb),
        "weights": w,
    }
    return out


def target_vs_actual(target_position, net_value, market_value):
    """模型目标仓位 vs 实盘仓位的偏离（**只报事实，不给指令** ✗）。

    - `target_position`：模型目标占比（0~1）
    - `net_value` / `market_value`：实盘净值与持仓市值（同币种）
    返回 `{"target", "actual", "gap_pp", "side"}`；
    任一输入缺失/非法 ⇒ `None`（**不猜** ✗）。
    `gap_pp` 单位是**百分点**（actual − target）；|gap| ≤ 1pp 视为 `on_target`。
    """
    try:
        t = float(target_position)
        n = float(net_value)
        m = float(market_value)
    except (TypeError, ValueError):
        return None
    if n <= 0 or not (0.0 <= t <= 1.0):
        return None
    actual = m / n
    gap_pp = (actual - t) * 100.0
    if abs(gap_pp) <= 1.0:
        side = "on_target"
    elif gap_pp > 0:
        side = "over"
    else:
        side = "under"
    return {"target": t, "actual": actual, "gap_pp": gap_pp, "side": side}
