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
