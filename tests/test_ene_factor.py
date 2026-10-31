# -*- coding: utf-8 -*-
"""C5 ENE 包络通道因子（`fg_system/factors/ene.py`，2026-10-31）。

锁住三条设计：
  1. **ENE 通道**用固定 %（10 / 9）✓
  2. **Keltner** 用 `k × ATR20` 自适应 ✓（`risk_mod.atr` 只给标量 ✗ 不能用）
  3. **信号载体可分离**：正股出信号、杠杆 ETF 交易 ✓
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors import ene


def _px(sym, n=60, start=10.0, step=0.0):
    d = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [start + i * step for i in range(n)]
    return pd.DataFrame({
        "date": d, "symbol": sym,
        "open": close, "high": [c * 1.02 for c in close],
        "low": [c * 0.98 for c in close], "close": close,
    })


def test_ene_bands_use_fixed_percent():
    """ENE 上轨 = MA10×1.10、下轨 = MA10×0.91 ✓（固定 %）。"""
    px = _px("SPY", 30)
    close = ene.close_series(px, "SPY")
    b = ene.ene_bands(close, n=10, up=10.0, down=9.0)

    mid = close.rolling(10).mean()
    assert b["upper"].iloc[-1] == pytest.approx(mid.iloc[-1] * 1.10)
    assert b["lower"].iloc[-1] == pytest.approx(mid.iloc[-1] * 0.91)


def test_channel_pos_range_and_endpoints():
    """位置 ∈ [0,1] ✓；贴下轨 ≈ 0、贴上轨 ≈ 1 ✓。"""
    px = _px("SPY", 30)
    close = ene.close_series(px, "SPY")
    b = ene.ene_bands(close, n=10)
    pos = ene.channel_pos(close, b).dropna()

    assert pos.min() >= 0.0 and pos.max() <= 1.0


def test_atr_series_is_rolling_not_scalar():
    """`atr_series` 必须返回**序列** ✓ —— `risk_mod.atr()` 只给最后一天的标量 ✗。

    这是 Keltner 通道能画出来的前提 ✓。
    """
    px = _px("SPY", 60)
    a = ene.atr_series(px, "SPY", n=20)
    assert isinstance(a, pd.Series)
    assert len(a) > 0
    assert (a > 0).all(), "ATR 应恒为正 ✗"


def test_keltner_width_follows_volatility():
    """Keltner 通道宽度随波动率变化 ✓（ENE 固定% 则不变）。"""
    calm = _px("AAA", 60, step=0.1)
    wild = calm.copy()
    wild["high"] = wild["close"] * 1.20      # 放大日内振幅 ⇒ ATR 变大
    wild["low"] = wild["close"] * 0.80
    wild["symbol"] = "BBB"
    both = pd.concat([calm, wild], ignore_index=True)

    w_calm = (ene.keltner_bands(both, "AAA")["upper"]
              - ene.keltner_bands(both, "AAA")["lower"]).dropna()
    w_wild = (ene.keltner_bands(both, "BBB")["upper"]
              - ene.keltner_bands(both, "BBB")["lower"]).dropna()

    assert w_wild.iloc[-1] > w_calm.iloc[-1] * 3, \
        "波动率放大后 Keltner 宽度应显著变宽 ✗"


def test_signal_for_modes():
    """三种 mode 都要能出信号 ✓；缺正股 ⇒ 空序列（不报错 ✓）。"""
    px = pd.concat([_px("YINN", 60), _px("FXI", 60, start=20.0)],
                   ignore_index=True)

    assert not ene.signal_for(px, "YINN", "underlying").empty
    assert not ene.signal_for(px, "YINN", "self_ene").empty
    assert not ene.signal_for(px, "YINN", "self_keltner").empty
    # 没有正股映射的标的 ⇒ 空（不抛错 ✓）
    assert ene.signal_for(px, "ZZZZ", "underlying").empty
    with pytest.raises(ValueError):
        ene.signal_for(px, "YINN", "不存在的mode")


def test_underlying_mapping_covers_holdings():
    """持仓的杠杆 ETF 都要有正股映射 ✓（否则 C5a 出不了信号）。"""
    for s in ("YINN", "GDXU", "CONL", "CRCG", "AXTX"):
        assert s in ene.UNDERLYING, "%s 缺正股映射 ✗" % s
