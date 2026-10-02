# -*- coding: utf-8 -*-
"""个股系统贪恐指数（路径 B：个股级因子合成，0-100，高分=贪婪）。

设计纪律（与系统 §4.5 约束 1 / SHOUTU_INDEX_MODE 注释一致）：
1. 输入必须是**无杠杆 underlying**（config.SIGNAL_UNDERLYING_MAP /
   config.CRYPTO_UNDERLYING / config.GDXU_UNDERLYING_BLEND），
   禁止用 YINN/GDXU 等杠杆 ETF 自身价格——波动率拖累会被系统性误读为恐惧。
2. 三因子合成（权重为先验，禁止优化，§4C.5 纪律）：
   - mom60：60 日动量 → 滚动分位（0.5）
   - mom20：20 日动量 → 滚动分位（0.3）
   - vol20：20 日年化波动率 → 滚动分位**反向**（0.2，低波动 = 贪婪）
3. 滚动分位窗口复用 config.RANK_WINDOW（756 日），不新造参数（第 4B.6 条）。
4. 数据不足（无 underlying 或历史 < 窗口 + 60 交易日）→ 返回 None/NaN，
   由调用方回退市场级 fg_index。
"""

import os

import pandas as pd

from fg_system import config
from fg_system.factors.base import pct_score

# 三因子先验权重：长动量为主、短动量次之、波动率反向兜底。
# 权重之和 = 1；不提供可配置项（防止被当作可优化参数）。
_SYMBOL_WEIGHTS = {"mom60": 0.5, "mom20": 0.3, "vol20": 0.2}


def _read_prices():
    df = pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"),
                     dtype={"symbol": str}, parse_dates=["date"])
    return df


def _crypto_underlying_close():
    df = pd.read_csv(config.CRYPTO_UNDERLYING_PATH, parse_dates=["date"])
    return df.set_index("date")["close"].astype(float).sort_index()


def underlying_close(symbol, prices=None, crypto_close=None):
    """symbol → 无杠杆底层日线 close（Series，index=date）。无数据返回 None。

    - 杠杆 ETF（YINN/GDXU/CRCG/CONL/AXTX）按 config 映射到无杠杆底层；
    - GDXU 底层是 GDX+GDXJ 合成列（config.GDXU_UNDERLYING_BLEND）；
    - BTC/BTC-USDT 取 crypto_underlying.csv（现货 BTC，2016 年起）。
    """
    sym = "BTC" if symbol == "BTC-USDT" else symbol
    if sym == "BTC":
        return (crypto_close if crypto_close is not None
                else _crypto_underlying_close())
    und = (config.SIGNAL_UNDERLYING_MAP.get(sym)
           or config.CRYPTO_UNDERLYING.get(sym))
    if und is None:
        return None
    if prices is None:
        prices = _read_prices()
    if und == config.GDXU_UNDERLYING_COLUMN:
        out = None
        for s, w in config.GDXU_UNDERLYING_BLEND.items():
            sub = prices[prices["symbol"] == s].set_index("date")["close"]
            sub = sub.astype(float) * float(w)
            out = sub if out is None else out + sub
        return out.sort_index() if out is not None else None
    sub = prices[prices["symbol"] == und].set_index("date")["close"]
    return sub.astype(float).sort_index() if not sub.empty else None


def symbol_fg_index(symbol, window=None, prices=None, crypto_close=None):
    """个股系统贪恐指数 0-100（高分=贪婪），返回时间序列。

    数据不足时返回 None（调用方回退市场级 fg_index）。
    """
    close = underlying_close(symbol, prices, crypto_close)
    if close is None or len(close) < 61:
        return None
    ret = close.pct_change(fill_method=None)
    mom60 = close.pct_change(60, fill_method=None)
    mom20 = close.pct_change(20, fill_method=None)
    vol20 = ret.rolling(20).std() * (252.0 ** 0.5)
    out = (_SYMBOL_WEIGHTS["mom60"] * pct_score(mom60, window)
           + _SYMBOL_WEIGHTS["mom20"] * pct_score(mom20, window)
           + _SYMBOL_WEIGHTS["vol20"] * pct_score(vol20, window, reverse=True))
    if out.dropna().empty:      # 窗口不足 → 全 NaN → 交由调用方回退市场
        return None
    return out
