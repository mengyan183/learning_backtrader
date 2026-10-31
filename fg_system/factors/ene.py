# -*- coding: utf-8 -*-
"""C5 ENE 包络通道因子（2026-10-31 实现）。

【ENE 是什么】

    MID   = MA(close, 10)
    UPPER = MID × (1 + 10%)
    LOWER = MID × (1 −  9%)

价格触上轨 = 短期涨幅偏离均值过大（超买），触下轨 = 超卖。
本质是**均值回归 + 通道位置**的混合。

【🔴 关键设计：信号载体与交易标的分离】

用户实测（2026-10-31）：「ENE(10,10,9) 在**正股**上用过，杠杆 ETF 上偏差有点大」✓
这个观察在数学上成立：

| 标的 | 正股日波动 | 杠杆 | ETF 日波动 | 10% 上轨 ≈ 几个日波动 |
|---|---|---|---|---|
| YINN | FXI ~1.5% | 3x | ~4.5% | 2.2 个 ✓ 可用 |
| GDXU | GDX ~2.5% | 3x | ~7.5% | 1.3 个 ⚠️ 偏频繁 |
| AXTX | AXTI ~8% | 2x | ~16% | **0.6 个** ✗ 天天穿轨 |

⇒ 同一个固定 10% 参数，在正股上是「2 个标准差」，在 AXTX 上是「0.6 个」✗
⇒ **信号必须算在正股上，交易对应的杠杆 ETF** ✓

【三个变体（用于区分「参数问题」还是「载体问题」）】

    C5a  正股      + ENE(10,10,9)      ← 主变体 ✓（用户偏好）
    C5b  杠杆 ETF  + ENE(10,10,9)      ← 反证「偏差大」✗
    C5c  杠杆 ETF  + MA10 ± 2×ATR20    ← 对照（自适应包络）

判读：
  - C5b 最差、C5c 接近 C5a ⇒ **参数问题**（ATR 包络能救）✓
  - C5b / C5c 都差、只有 C5a 好 ⇒ **载体问题**（必须在正股上算）✓

【因子方向】
`pos` = 价格在通道内的相对位置 ∈ [0, 1]（0 = 触下轨超卖，1 = 触上轨超买）
均值回归 ⇒ `pos` 与未来收益**负相关** ⇒ 评测用 `direction="逆向"` ✓
"""
import pandas as pd

#: ENE 默认参数（用户偏好）✓
ENE_N = 10
ENE_UP = 10.0
ENE_DOWN = 9.0

#: Keltner 对照的 ATR 倍数 ✓（2 倍是行业惯例）
KELTNER_K = 2.0
KELTNER_N = 20

#: 杠杆 ETF → 正股 ✓（信号算在正股上）
UNDERLYING = {
    "YINN": "FXI",
    "GDXU": "GDX",
    "CONL": "COIN",
    "CRCG": "CRCL",
    "AXTX": "AXTI",
    "TQQQ": "QQQ",
    "SOXL": "SMH",
    "UPRO": "SPY",
    "NVDL": "NVDA",
    "TSLL": "TSLA",
}


def close_series(prices_df, sym):
    """从长表取某标的收盘价序列 ✓（index=date，去重升序）。"""
    s = (prices_df[prices_df["symbol"] == sym]
         .set_index("date")["close"].astype(float))
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def ene_bands(close, n=ENE_N, up=ENE_UP, down=ENE_DOWN):
    """ENE 通道 ⇒ `DataFrame[mid, upper, lower]` ✓。"""
    mid = close.rolling(n, min_periods=n).mean()
    return pd.DataFrame({
        "mid": mid,
        "upper": mid * (1.0 + up / 100.0),
        "lower": mid * (1.0 - down / 100.0),
    })


def atr_series(prices_df, sym, n=KELTNER_N):
    """**滚动** ATR 序列 ✓。

    🔴 `risk_mod.atr()` 只返回**最后一天**的标量 ✗（`float(tr.iloc[-n:].mean())`）
    ⇒ 不能直接用于 Keltner 通道 ✗ ⇒ 这里自己算滚动版 ✓
    """
    d = (prices_df[prices_df["symbol"] == sym]
         .set_index("date").sort_index())
    d = d[~d.index.duplicated(keep="last")]
    prev = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"],
                    (d["high"] - prev).abs(),
                    (d["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean().dropna()


def keltner_bands(prices_df, sym, n=ENE_N, k=KELTNER_K, atr_n=KELTNER_N):
    """Keltner 通道（ATR 自适应）⇒ `DataFrame[mid, upper, lower]` ✓。

    与 ENE 的唯一差别：包络宽度用 `k × ATR20` 而不是固定 % ✓
    ⇒ 自动适应波动率，不会在 AXTX 那种高波动标的上失效 ✓
    """
    close = close_series(prices_df, sym)
    mid = close.rolling(n, min_periods=n).mean()
    a = atr_series(prices_df, sym, atr_n).reindex(close.index)
    return pd.DataFrame({
        "mid": mid,
        "upper": mid + k * a,
        "lower": mid - k * a,
    })


def channel_pos(close, bands):
    """价格在通道内的相对位置 ∈ [0, 1] ✓（0=下轨，1=上轨）。

    通道宽度为 0（或 NaN）⇒ `NaN` ✓（不凑值 ✗）。
    """
    width = (bands["upper"] - bands["lower"]).replace(0, pd.NA)
    pos = (close - bands["lower"]) / width
    return pos.astype(float).clip(0.0, 1.0)


def ene_pos(prices_df, sym, n=ENE_N, up=ENE_UP, down=ENE_DOWN):
    """ENE 通道位置 ✓（固定 % 包络）。"""
    close = close_series(prices_df, sym)
    return channel_pos(close, ene_bands(close, n, up, down)).rename("ene_pos")


def keltner_pos(prices_df, sym, n=ENE_N, k=KELTNER_K):
    """Keltner 通道位置 ✓（ATR 自适应包络）。"""
    close = close_series(prices_df, sym)
    return channel_pos(close, keltner_bands(prices_df, sym, n, k)).rename(
        "keltner_pos")


def signal_for(prices_df, trade_sym, mode="underlying"):
    """按变体给出信号序列 ✓。

    :param trade_sym: **交易的**标的（杠杆 ETF）
    :param mode: `underlying`（C5a，信号算正股）/
                 `self_ene`（C5b，信号算自身 ENE）/
                 `self_keltner`（C5c，信号算自身 Keltner）
    :returns: `Series[0,1]`，index=date；`underlying` 模式缺正股 ⇒ 返回空 ✓
    """
    if mode == "underlying":
        und = UNDERLYING.get(str(trade_sym).upper())
        if not und:
            return pd.Series(dtype=float, name="ene_pos")
        return ene_pos(prices_df, und)
    if mode == "self_ene":
        return ene_pos(prices_df, trade_sym)
    if mode == "self_keltner":
        return keltner_pos(prices_df, trade_sym)
    raise ValueError("未知 mode：%r" % mode)
