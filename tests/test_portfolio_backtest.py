# -*- coding: utf-8 -*-
"""M2.1 组合回测层：构造性交叉验证 + 等权合成 + OOS 切片 + 渲染。"""
import numpy as np
import pandas as pd
import pytest

from scripts.portfolio_backtest import _metrics, _split, build_portfolio, render_md


def _mock_data(n=60, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-06-01", periods=n)
    feats = pd.DataFrame({
        "date": dates,
        "fg_index": rng.uniform(10, 90, n),
        "zone": rng.integers(0, 5, n),
        "target_position": rng.uniform(0.0, 1.0, n),
    })
    rows = []
    for sym, base in [("TQQQ", 30.0), ("SOXL", 20.0), ("UPRO", 40.0)]:
        close = base * (1 + rng.normal(0, 0.01, n)).cumprod()
        for i, d in enumerate(dates):
            rows.append({"date": d, "symbol": sym, "open": close[i] * 0.999,
                         "high": close[i] * 1.005, "low": close[i] * 0.995,
                         "close": close[i], "volume": 1e6})
    prices = pd.DataFrame(rows)
    return feats, prices


def test_constructive_identity():
    """组合日收益 ≡ Σ(1/n)·单标的日收益（构造保证），max|diff|=0。"""
    feats, prices = _mock_data()
    out = build_portfolio(feats, prices, oos_start="2024-09-01")
    assert out["cross_check"]["max_abs_diff"] == 0.0


def test_equal_weight():
    feats, prices = _mock_data()
    out = build_portfolio(feats, prices, oos_start="2024-09-01")
    assert set(out["symbols"]) == {"TQQQ", "SOXL", "UPRO"}
    for s in out["symbols"]:
        assert out["weights"][s] == pytest.approx(1 / 3)


def test_oos_split_boundary():
    feats, prices = _mock_data()
    out = build_portfolio(feats, prices, oos_start="2024-09-15")
    # 渲染健壮：短 OOS 段指标可 NaN，渲染用 "—" 兜底不崩
    md = render_md(out)
    assert "组合（OOS）" in md and "B0 等权买入持有（OOS）" in md
    assert "相关性矩阵" in md
    assert "| 年化 |" in md and "—" in md


def test_correlation_symmetric():
    feats, prices = _mock_data()
    out = build_portfolio(feats, prices, oos_start="2024-09-01")
    corr = out["correlation"]
    for a in out["symbols"]:
        assert corr[a][a] == pytest.approx(1.0, abs=1e-3)
        for b in out["symbols"]:
            assert corr[a][b] == pytest.approx(corr[b][a], abs=1e-3)


def test_split_respects_oos_start():
    idx = pd.to_datetime(["2024-08-01", "2024-09-01", "2024-09-15", "2024-10-01"])
    s = pd.Series([0.01, 0.02, -0.01, 0.03], index=idx)
    is_r, oos_r = _split(s, "2024-09-15")
    assert (is_r.index < "2024-09-15").all()
    assert (oos_r.index >= "2024-09-15").all()
    assert len(is_r) == 2 and len(oos_r) == 2
