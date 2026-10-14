# -*- coding: utf-8 -*-
"""原油（大宗商品）候选因子前置：传导机制代理（纯函数，注入序列）。

背景：用户 2026-10-14 提出「今年原油波动对美股影响超级大」——⚠️ 这是**事后观察**，
是 OOS 过拟合的典型入口。因此本模块**只做前置取证**，绝不把油价直接当贪恐因子、
绝不进任何合成/权重路径（见 config.WEIGHTS 红线）。

设计原则（预登记判据见 docs/notes/2026-10-14-crude-factor-preregistration.md）：
  - 不直接用「油价水平」当情绪（水平无稳定方向、且与利率高度共线重复计价）；
  - 只实现**传导机制代理**：波动、油-股相关（机制切换探测）、跳涨事件。

三个纯函数（无 I/O、无联网、缺数据/短序列不崩）：
  - crude_vol(close, window=20)                       原油 20 日已实现波动（年化）
  - crude_equity_corr(crude_close, equity_close, 60)  滚动相关（突变=传导机制切换）
  - crude_shock_days(crude_ret, threshold=0.05)       单日跳涨 >5% 的事件标记

年化口径与既有因子一致（见 fg_system/factors/crypto_price.py：
`pct_change().rolling(20).std() * np.sqrt(252)`）。
"""
import numpy as np
import pandas as pd


def _as_series(x):
    """None / 空输入 → 空 float Series；其它原样返回（保证纯计算不崩）。"""
    if x is None:
        return pd.Series([], dtype="float64")
    return x


def crude_vol(close, window=20):
    """原油 window 日已实现波动（年化，交易日 252）。

    close: 油价收盘序列（index=date）。
    返回：与 close 同索引的波动序列；窗口不足处为 NaN（禁止用不足窗口凑值）。
    """
    s = _as_series(close)
    if s.empty:
        return pd.Series([], dtype="float64")
    ret = s.astype("float64").pct_change()
    return ret.rolling(window).std() * np.sqrt(252.0)


def crude_equity_corr(crude_close, equity_close, window=60):
    """原油与股票（QQQ）收益的 window 日滚动相关。

    突变（相关性显著变动）= 传导机制切换的代理信号。
    两序列按索引交集对齐后滚动；窗口不足处为 NaN。缺数据/空输入返回空序列。
    """
    a = _as_series(crude_close)
    b = _as_series(equity_close)
    if a.empty or b.empty:
        return pd.Series([], dtype="float64")
    ra = a.astype("float64").pct_change()
    rb = b.astype("float64").pct_change()
    df = pd.concat([ra.rename("c"), rb.rename("e")], axis=1).dropna()
    if len(df) < window:
        # 数据不足：返回与该交集同索引的全 NaN 序列（不崩、可解释）
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return df["c"].rolling(window).corr(df["e"])


def crude_shock_days(crude_ret, threshold=0.05):
    """单日跳涨/跳跌超 threshold（默认 5%）的事件标记（严格 > threshold）。

    crude_ret: 油价日收益序列（index=date）。
    返回：同索引 0/1 浮点序列（1 = 事件日），可直接进事件研究矩阵。
    """
    s = _as_series(crude_ret)
    if s.empty:
        return pd.Series([], dtype="float64")
    return (s.astype("float64").abs() > threshold).astype("float64")
