# -*- coding: utf-8 -*-
"""F3 价格因子（先验权重 30%，§5.2）。

四个子项（等权）：动量、RSI(14)、距 52 周高点回撤（反转）、20 日已实现波动率（反转）。
输入：QQQ（标的指数代理）。**禁止使用杠杆 ETF 自身价格**（§4.5 约束 1）——
杠杆 ETF 含年化 12%~38% 的波动率拖累，会把损耗系统性误读为恐惧。
"""
import numpy as np

from fg_system import config
from fg_system.factors.base import Factor, rolling_pct


def rsi(series, period=14):
    """Wilder RSI，含边界处理。

    边界约定（必须显式处理，否则会产生 NaN 并污染整个因子）：
    - avg_loss == 0 且 avg_gain > 0（期内只涨不跌）→ RSI = 100
    - avg_gain == 0 且 avg_loss > 0（期内只跌不涨）→ RSI = 0
    - 两者同时为 0（完全无变化）→ RSI = 50（中性）
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)

    out = out.where(avg_loss != 0.0, 100.0)                 # 只涨不跌 → 100
    flat = (avg_gain == 0.0) & (avg_loss == 0.0)
    out = out.where(~flat, 50.0)                            # 完全无变化 → 50
    out = out.where(avg_gain.notna() & avg_loss.notna())    # warmup 期保持 NaN
    return out


def drawdown_52w(series, lookback=252):
    """距滚动 52 周最高收盘价的回撤（正数表示回撤幅度）。"""
    peak = series.rolling(lookback, min_periods=lookback).max()
    return 1.0 - series / peak


class PriceFactor(Factor):
    name = "price"
    underlying = "QQQ"

    def raw(self, wide):
        if (self.underlying, "close") not in wide.columns:
            raise ValueError(
                "F3 必须使用无杠杆标的 %s，当前列: %s" % (self.underlying, list(wide.columns))
            )
        qqq = wide[(self.underlying, "close")]
        w = config.RANK_WINDOW

        # 动量子项含 20 日与 60 日两部分（§5.2 F3）
        mom = (rolling_pct(qqq.pct_change(20), w)
               + rolling_pct(qqq.pct_change(60), w)) / 2.0             # 正向
        strength = rolling_pct(rsi(qqq), w)                            # 正向
        dd = 1.0 - rolling_pct(drawdown_52w(qqq), w)                   # 反转
        vol = qqq.pct_change().rolling(20).std() * np.sqrt(252)
        calm = 1.0 - rolling_pct(vol, w)                               # 反转
        return (mom + strength + dd + calm) / 4.0
