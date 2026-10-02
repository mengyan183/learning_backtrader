# -*- coding: utf-8 -*-
"""个股系统指数（路径 B）测试：`fg_system.factors.symbol`。

断言风格与 tests/factors 一致：构造确定性数据，用**情景对比**代替绝对阈值
（绝对值依赖滚动排名边界细节，不稳定）。
不读取真实 Data/ 文件——价格输入全部用构造的 DataFrame / Series。
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors import symbol


def _prices(symbol_close):
    """symbol_close: {symbol: Series(close, index=date)} → prices 长表 DataFrame。"""
    rows = []
    for sym, s in symbol_close.items():
        for d, v in s.items():
            rows.append((d, sym, v))
    df = pd.DataFrame(rows, columns=["date", "symbol", "close"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _trend(n, daily, start=100.0, seed=None):
    """确定性趋势序列：日收益固定为 daily（可为标量或数组）。"""
    if seed is not None:
        rng = np.random.default_rng(seed)
        rets = rng.normal(daily, 0.005, n)
        rets[0] = 0.0
    else:
        rets = np.full(n, daily)
        rets[0] = 0.0
    close = start * np.cumprod(1.0 + rets)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(close, index=idx, dtype=float)


# ---------------------------------------------------------------- underlying 映射
def test_yinn_maps_to_fxi_unleveraged():
    """YINN 的底层必须是 FXI（无杠杆），绝不能是 YINN 自身。"""
    idx = pd.date_range("2020-01-01", periods=200, freq="B")
    fxi = pd.Series(np.linspace(30, 40, 200), index=idx)
    yinn = pd.Series(np.linspace(50, 20, 200), index=idx)   # 杠杆ETF 走势不同
    px = _prices({"FXI": fxi, "YINN": yinn})
    out = symbol.underlying_close("YINN", prices=px)
    assert out is not None
    assert (out.index == fxi.index).all()
    assert out.iloc[0] == pytest.approx(30.0)      # 返回 FXI 而非 YINN


def test_gdxu_uses_weighted_blend():
    """GDXU 底层 = GDX×0.7607 + GDXJ×0.2393 合成（config.GDXU_UNDERLYING_BLEND）。"""
    n = 200
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    gdx = pd.Series(np.linspace(20, 30, n), index=idx)
    gdxj = pd.Series(np.linspace(40, 50, n), index=idx)
    px = _prices({"GDX": gdx, "GDXJ": gdxj})
    out = symbol.underlying_close("GDXU", prices=px)
    assert out is not None
    assert out.iloc[-1] == pytest.approx(
        30.0 * 0.7607 + 50.0 * 0.2393, rel=1e-6)


def test_conl_missing_underlying_returns_none():
    """CONL 映射 COIN，但构造数据里没有 COIN → 返回 None（调用方回退市场）。"""
    idx = pd.date_range("2020-01-01", periods=100, freq="B")
    px = _prices({"QQQ": pd.Series(np.linspace(1, 2, 100), index=idx)})
    assert symbol.underlying_close("CONL", prices=px) is None


def test_conl_with_coin_underlying_returns_index():
    """CONL 映射 COIN；构造数据含 COIN（≥61 行）→ 个股指数非 None。

    2026-10-02 真实 prices.csv 已补录 COIN 日线（Yahoo 来源，2021-10 起），
    本用例用构造数据复现该路径，不依赖真实文件。
    """
    n = 900   # > 756+60，保证滚动分位可用（与趋势方向用例同约定）
    px = _prices({"COIN": _trend(n, 0.0015, seed=21)})
    close = symbol.underlying_close("CONL", prices=px)
    assert close is not None and len(close) == n
    fg = symbol.symbol_fg_index("CONL", prices=px)
    assert fg is not None and 0 <= float(fg.iloc[-1]) <= 100


def test_unknown_symbol_returns_none():
    idx = pd.date_range("2020-01-01", periods=100, freq="B")
    px = _prices({"QQQ": pd.Series(np.linspace(1, 2, 100), index=idx)})
    assert symbol.underlying_close("NOT_A_TICKER", prices=px) is None


def test_btc_uses_crypto_close():
    """BTC-USDT → 现货 BTC close（crypto 输入），与美股 prices 无关。"""
    idx = pd.date_range("2020-01-01", periods=150, freq="B")
    btc = pd.Series(np.linspace(20000, 60000, 150), index=idx)
    out = symbol.underlying_close("BTC-USDT", crypto_close=btc)
    assert out is not None
    assert out.iloc[-1] == pytest.approx(60000.0)
    assert symbol.underlying_close("BTC", crypto_close=btc).iloc[0] == \
        pytest.approx(20000.0)


# ---------------------------------------------------------------- symbol_fg_index
def test_short_history_returns_none():
    """历史不足（<61 行）→ None，不产出半截序列。"""
    idx = pd.date_range("2020-01-01", periods=30, freq="B")
    px = _prices({"FXI": pd.Series(np.linspace(1, 2, 30), index=idx)})
    assert symbol.symbol_fg_index("YINN", prices=px) is None


def test_window_too_short_all_nan_returns_none():
    """有足够 pct_change 行数但滚动分位窗口不足 → 全 NaN → None（CRCG 场景）。"""
    idx = pd.date_range("2020-01-01", periods=300, freq="B")   # 300 < 756+60
    close = pd.Series(np.linspace(1, 2, 300), index=idx)
    px = _prices({"CRCL": close})
    assert symbol.symbol_fg_index("CRCG", prices=px) is None


def test_uptrend_scores_higher_than_downtrend():
    """情景对比（带噪声，避免单调序列滚动分位恒 1 的陷阱）：
    稳定上行底层的最新指数必须高于稳定下行底层（动量方向正确）。"""
    n = 900   # > 756+60，保证滚动分位可用
    up = _trend(n, 0.0015, seed=11)
    down = _trend(n, -0.0015, seed=12)
    px = _prices({"FXI": up, "GDX": down, "GDXJ": down})   # GDXU 底层=GDX+GDXJ 合成
    idx_up = symbol.symbol_fg_index("YINN", prices=px)
    idx_down = symbol.symbol_fg_index("GDXU", prices=px)
    assert idx_up is not None and idx_down is not None
    assert idx_up.dropna().iloc[-1] > idx_down.dropna().iloc[-1]


def test_output_bounded_0_100():
    n = 900
    close = _trend(n, 0.0005, seed=42)
    px = _prices({"FXI": close})
    out = symbol.symbol_fg_index("YINN", prices=px)
    assert out is not None
    valid = out.dropna()
    assert len(valid) > 0
    assert valid.between(0, 100).all()


def test_recent_volatility_spike_lowers_score():
    """同趋势下：最近 200 日叠加高波动的底层，最新指数 ≤ 全程低波动底层
    （波动率因子反向生效；固定 seed 保证确定性）。"""
    n = 900
    rng = np.random.default_rng(7)
    # 基线：日均 +0.08% 的低噪声
    base = rng.normal(0.0008, 0.0008, n); base[0] = 0.0
    low = pd.Series(100 * np.cumprod(1 + base),
                    index=pd.date_range("2020-01-01", periods=n, freq="B"))
    # 同基线，但最近 200 日改为 ±4% 剧烈波动（动量均值保持 +0.08%）
    spike = base.copy()
    spike[-200:] = rng.normal(0.0008, 0.04, 200)
    high = pd.Series(100 * np.cumprod(1 + spike),
                     index=pd.date_range("2020-01-01", periods=n, freq="B"))
    px = _prices({"FXI": low, "GDX": high, "GDXJ": high})  # GDXU 合成底层
    s_low = symbol.symbol_fg_index("YINN", prices=px)
    s_high = symbol.symbol_fg_index("GDXU", prices=px)
    assert s_low is not None and s_high is not None
    assert s_low.dropna().iloc[-1] >= s_high.dropna().iloc[-1]
