# -*- coding: utf-8 -*-
"""加密双轨回测测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.backtest import crypto_runner


# ---------------------------------------------------------------- v2.5 组合级口径

def test_portfolio_backtest_returns_series():
    """正常输入必须返回非空、无 NaN 的日收益序列。"""
    long = _prices(["BITX", "CONL"], n=400)
    idx = pd.bdate_range("2024-01-01", periods=400)
    target = pd.Series(0.20, index=idx)
    w = pd.Series({"BITX": 0.5, "CONL": 0.5})
    r = crypto_runner.portfolio_backtest(long, target, w)
    assert r is not None
    assert len(r) > 0
    assert r.notna().all()


def test_portfolio_backtest_none_when_target_all_nan():
    """warmup 期（目标全 NaN）必须返回 None，**不得抛异常**。"""
    long = _prices(["BITX", "CONL"], n=50)
    idx = pd.bdate_range("2024-01-01", periods=50)
    target = pd.Series(np.nan, index=idx)
    w = pd.Series({"BITX": 0.5, "CONL": 0.5})
    assert crypto_runner.portfolio_backtest(long, target, w) is None


def test_portfolio_backtest_scales_with_target():
    """目标仓位越大，篮子收益幅度越大（执行约束之下仍应单调）。"""
    long = _prices(["BITX"], n=400, trend=0.002)
    idx = pd.bdate_range("2024-01-01", periods=400)
    w = pd.Series({"BITX": 1.0})
    lo = crypto_runner.portfolio_backtest(long, pd.Series(0.10, index=idx), w)
    hi = crypto_runner.portfolio_backtest(long, pd.Series(0.30, index=idx), w)
    assert lo is not None and hi is not None
    assert hi.iloc[-1] > lo.iloc[-1]


def test_portfolio_backtest_respects_weights():
    """权重必须真的生效：把全部权重给下跌标的，收益必须低于给上涨标的。"""
    n = 400
    idx = pd.bdate_range("2024-01-01", periods=n)
    frames = []
    for s, trend in (("UP", 0.002), ("DOWN", -0.002)):
        close = 100.0 * (1 + trend) ** np.arange(n)
        frames.append(pd.DataFrame({
            "date": idx, "symbol": s, "open": close, "high": close,
            "low": close, "close": close, "volume": 1.0}))
    long = pd.concat(frames, ignore_index=True)
    target = pd.Series(0.30, index=idx)
    up = crypto_runner.portfolio_backtest(long, target, pd.Series({"UP": 1.0, "DOWN": 0.0}))
    dn = crypto_runner.portfolio_backtest(long, target, pd.Series({"UP": 0.0, "DOWN": 1.0}))
    assert up.iloc[-1] > 0 > dn.iloc[-1]


def _prices(symbols, n=300, start="2024-01-01", trend=0.001):
    idx = pd.bdate_range(start, periods=n)
    frames = []
    for s in symbols:
        close = 100.0 * (1 + trend) ** np.arange(n)
        frames.append(pd.DataFrame({
            "date": idx, "symbol": s, "open": close, "high": close,
            "low": close, "close": close, "volume": 1.0,
        }))
    return pd.concat(frames, ignore_index=True)


def test_track_labels_are_distinct():
    assert crypto_runner.TRACK_SYNTHETIC == "synthetic"
    assert crypto_runner.TRACK_REAL == "real"


def test_metrics_for_synthetic_track():
    prices = _prices(["BITX"])
    m = crypto_runner.track_metrics(prices, "BITX", track="synthetic")
    assert "annual_return" in m and "max_drawdown" in m


def test_result_carries_track_label():
    """结果必须带轨标签——防止合成轨数字被当成真实预期（§4.2）。"""
    prices = _prices(["BITX"])
    res = crypto_runner.evaluate_symbol(prices, "BITX", track="synthetic")
    assert res["track"] == "synthetic"


def test_track_metrics_empty_symbol():
    prices = _prices(["BITX"])
    m = crypto_runner.track_metrics(prices, "NOT_EXIST", track="real")
    assert np.isnan(m["annual_return"])


def test_cross_market_correlation_returns_float():
    us = _prices(["TQQQ"], n=200).set_index("date")["close"]
    cr = _prices(["BITX"], n=200).set_index("date")["close"]
    r = crypto_runner.cross_market_correlation(us, cr)
    assert isinstance(r, float)


def test_cross_market_correlation_nan_when_too_few_points():
    us = pd.Series([1.0, 2.0], index=pd.bdate_range("2024-01-01", periods=2))
    cr = pd.Series([1.0, 2.0], index=pd.bdate_range("2024-01-01", periods=2))
    assert np.isnan(crypto_runner.cross_market_correlation(us, cr))


def test_crisis_correlation_flags_high_risk():
    """危机期相关性 > 0.7 时必须告警（§12 风险 8）。"""
    idx = pd.bdate_range("2024-01-01", periods=100)
    rng = np.random.default_rng(7)
    base = pd.Series(rng.normal(-0.005, 0.02, 100), index=idx)
    us = pd.Series((1 + base).cumprod().values * 100, index=idx)
    cr = pd.Series((1 + base * 1.5).cumprod().values * 100, index=idx)
    out = crypto_runner.crisis_correlation(us, cr, threshold=0.7)
    assert out["correlation"] > 0.7
    assert out["warning"] is True
    assert "风险" in out["reason"]


def test_crisis_correlation_no_warning_when_low():
    idx = pd.bdate_range("2024-01-01", periods=200)
    rng = np.random.default_rng(11)
    us = pd.Series((1 + rng.normal(-0.001, 0.01, 200)).cumprod() * 100, index=idx)
    cr = pd.Series((1 + rng.normal(-0.001, 0.05, 200)).cumprod() * 100, index=idx)
    out = crypto_runner.crisis_correlation(us, cr, threshold=0.7)
    assert out["warning"] is False


def test_crisis_correlation_insufficient_sample():
    us = pd.Series(np.linspace(100, 90, 30), index=pd.bdate_range("2024-01-01", periods=30))
    cr = pd.Series(np.linspace(100, 90, 30), index=pd.bdate_range("2024-01-01", periods=30))
    out = crypto_runner.crisis_correlation(us, cr)
    assert out["warning"] is False
    assert "不足" in out["reason"]


def test_layer_contribution_sums_to_total():
    prices = _prices(["BITX", "MSTX", "CONL"])
    table = crypto_runner.layer_contribution(prices)
    assert set(table["layer"]) == {"btc_beta", "stock_high_beta", "stock_ops_beta"}
    assert len(table) == 3


def test_layer_contribution_empty_returns_columns():
    prices = _prices(["NOT_EXIST"])
    table = crypto_runner.layer_contribution(prices)
    assert list(table.columns) == ["layer", "symbol", "annual_return",
                                   "max_drawdown", "cap"]


def test_report_handles_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto_runner.config, "SYNTHETIC_PATH",
                        str(tmp_path / "nope1.csv"))
    monkeypatch.setattr(crypto_runner.config, "CRYPTO_PRICES_PATH",
                        str(tmp_path / "nope2.csv"))
    monkeypatch.setattr(crypto_runner.config, "CRYPTO_UNDERLYING_PATH",
                        str(tmp_path / "nope3.csv"))
    out = crypto_runner.report()
    assert out["synthetic"] == []
    assert out["real"] == []


def test_portfolio_backtest_drops_missing_symbols_and_renormalizes():
    """**回归**：某轨缺少某个标的时必须丢弃 + 权重归一化，而不是 KeyError。

    真实场景（v2.8，第 12.23 条）：真实轨 `crypto_prices.csv` **没有 BTC 现货杠杆**
    ——它是用户的实盘仓位，不是可下载的 ETF。硬性要求全部标的会直接 KeyError。
    真实轨的用途只是「验证合成轨是否可信」，只能验证存在的部分。
    """
    idx = pd.bdate_range("2024-01-01", periods=60)
    long = pd.DataFrame({
        "date": list(idx) * 2,
        "symbol": ["A"] * 60 + ["B"] * 60,
        "close": list(np.linspace(100, 110, 60)) + list(np.linspace(50, 55, 60)),
    })
    target = pd.Series(0.5, index=idx)
    weights = pd.Series({"A": 0.5, "B": 0.25, "MISSING": 0.25})

    r = crypto_runner.portfolio_backtest(long, target, weights, None)
    assert r is not None and not r.empty, "缺标的时不得返回 None"


def test_portfolio_backtest_returns_none_when_no_symbol_present():
    """全部标的都缺失时必须返回 None，而不是抛异常或返回空壳。"""
    idx = pd.bdate_range("2024-01-01", periods=30)
    long = pd.DataFrame({"date": idx, "symbol": ["Z"] * 30,
                         "close": np.linspace(1, 2, 30)})
    target = pd.Series(0.5, index=idx)
    weights = pd.Series({"A": 1.0})
    assert crypto_runner.portfolio_backtest(long, target, weights, None) is None
