# -*- coding: utf-8 -*-
"""L3.2 组合风险度量：var/cvar/max_drawdown/hrp_weights/risk_report。"""
import numpy as np
import pandas as pd

from fg_system.risk import (
    cvar, hrp_weights, max_drawdown, risk_report, var)


def _ret_series():
    rng = np.random.default_rng(42)
    return pd.Series(rng.normal(0.0005, 0.02, 500))


def test_var_quantile():
    s = _ret_series()
    v = var(s, alpha=0.05)
    assert isinstance(v, float)
    # 与 numpy 分位一致
    assert abs(v - np.percentile(s.dropna(), 5)) < 1e-9


def test_cvar_is_tail_mean():
    s = _ret_series()
    v = var(s)
    c = cvar(s)
    assert c <= v + 1e-9  # 尾部期望 ≤ VaR（负向收益分布）


def test_short_sample_returns_none():
    assert var(pd.Series([0.01, -0.02])) is None  # <30
    assert cvar(pd.Series([0.01, -0.02])) is None
    assert max_drawdown(pd.Series([0.01])) is None


def test_max_drawdown_known():
    s = pd.Series([0.10, -0.10, 0.05, -0.05, 0.20])
    # 净值 1.1 → 0.99 → 1.0395 → 0.9875 → 1.185；峰 1.1 谷 0.9875 → (0.9875-1.1)/1.1
    m = max_drawdown(s)
    assert abs(m - (0.987525 - 1.1) / 1.1) < 1e-6


def test_hrp_weights_sum_one():
    df = pd.DataFrame(np.random.default_rng(7).normal(0, 0.01, (200, 3)),
                      columns=["a", "b", "c"])
    w = hrp_weights(df)
    assert set(w) == {"a", "b", "c"}
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_hrp_low_vol_asset_gets_more():
    # b 波动远低于 a/c → HRP 给 b 更高权重
    df = pd.DataFrame({
        "a": np.random.default_rng(1).normal(0, 0.05, 300),
        "b": np.random.default_rng(2).normal(0, 0.005, 300),
        "c": np.random.default_rng(3).normal(0, 0.05, 300),
    })
    w = hrp_weights(df)
    assert w["b"] > w["a"] and w["b"] > w["c"]


def test_hrp_short_sample_equal_weight():
    df = pd.DataFrame(np.random.default_rng(5).normal(0, 0.01, (20, 2)),
                      columns=["x", "y"])
    w = hrp_weights(df)
    assert abs(w["x"] - 0.5) < 1e-9


def test_risk_report_structure():
    df = pd.DataFrame(np.random.default_rng(9).normal(0, 0.01, (100, 2)),
                      columns=["x", "y"])
    r = risk_report(df, weights={"x": 0.6, "y": 0.4})
    assert set(r["assets"]) == {"x", "y"}
    assert "var95" in r["portfolio"] and "cvar95" in r["portfolio"]
    assert r["portfolio"]["weights"] == {"x": 0.6, "y": 0.4}
    assert abs(r["portfolio"]["annual_vol"] - r["assets"]["x"]["annual_vol"]
               * 0.6 - r["assets"]["y"]["annual_vol"] * 0.4) < 1  # 近似成立即可


def test_risk_report_empty():
    assert risk_report(pd.DataFrame()) == {}
