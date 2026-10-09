# -*- coding: utf-8 -*-
"""C-1 变体设施等价性守卫测试（红线：默认参数逐位相同）。

守卫内容：
  1. `apply_variant(..., "B0")` 返回的 target_position 与生产 features 逐位相同；
  2. V-H7 只动 trend_blocked_us=True 的交易日（×0.5），其余日逐位不变；
  3. 阻断日掩码与 portfolio_features.trend_blocked_us 完全一致（无遗漏）。
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.backtest import variants as vmod


def _mk_features(n=120):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    target = 0.5 + 0.1 * np.sin(np.arange(n) / 5.0)
    return pd.DataFrame(
        {"fg_index": 50.0, "zone": 2.0, "target_position": target},
        index=idx)


def _mk_portfolio(n=120, blocked_idx=None):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    blocked = np.zeros(n, dtype=bool)
    if blocked_idx:
        blocked[list(blocked_idx)] = True
    return pd.DataFrame(
        {"trend_blocked_us": blocked, "us_core": 0.3}, index=idx)


def test_b0_identity():
    """B0 必须逐位相同（默认参数逐位相同红线）。"""
    f = _mk_features()
    pf = _mk_portfolio(len(f))
    out = vmod.apply_variant(f, pf, vmod.BASELINE)
    assert out.index.equals(f.index)
    assert np.allclose(out["target_position"].values,
                       f["target_position"].values, rtol=0, atol=0)


def test_unknown_variant_rejected():
    with pytest.raises(KeyError):
        vmod.apply_variant(_mk_features(), _mk_portfolio(), "V-NOPE")


def test_vh7_only_touches_blocked_days():
    """V-H7 只动阻断日：阻断日 target ×0.5，非阻断日逐位不变。"""
    f = _mk_features(120)
    blocked = {10, 20, 30, 31, 32}
    pf = _mk_portfolio(len(f), blocked_idx=blocked)
    out = vmod.apply_variant(f, pf, "V-H7")
    exp = f["target_position"].copy()
    idx = f.index[list(blocked)]
    exp.loc[idx] = exp.loc[idx] * 0.5
    assert np.allclose(out["target_position"].values, exp.values,
                       rtol=1e-12, atol=1e-12)
    # 非阻断日不变
    unblocked = np.ones(len(f), dtype=bool)
    unblocked[list(blocked)] = False
    assert np.allclose(
        out["target_position"].values[unblocked],
        f["target_position"].values[unblocked], rtol=0, atol=0)


def test_blocked_mask_matches_portfolio():
    """阻断掩码与 portfolio_features.trend_blocked_us 完全一致（无遗漏）。"""
    f = _mk_features(60)
    pf = _mk_portfolio(60, blocked_idx={5, 6, 7, 40})
    out = vmod.apply_variant(f, pf, "V-H7")
    changed = ~np.isclose(out["target_position"].values,
                          f["target_position"].values, rtol=0, atol=1e-12)
    assert set(np.where(changed)[0]) == {5, 6, 7, 40}


def _mk_price_features(n=120):
    """带价格列的 features（V-ATR 需要 high/low/close）。"""
    f = _mk_features(n)
    rng = np.random.default_rng(7)
    close = 100.0 + np.cumsum(rng.normal(0, 1.0, n))
    close = np.maximum(close, 10.0)
    high = close * 1.02
    low = close * 0.98
    f["open"] = close
    f["high"] = high
    f["low"] = low
    f["close"] = close
    return f


def test_vatr_no_price_columns_returns_identical():
    """V-ATR 缺价格列（守卫测试纯 features 场景）→ 返回原样（保守不加规则）。"""
    f = _mk_features(120)
    pf = _mk_portfolio(len(f))
    out = vmod.apply_variant(f, pf, "V-ATR")
    assert out.index.equals(f.index)
    assert np.allclose(out["target_position"].values,
                       f["target_position"].values, rtol=0, atol=0)


def test_vatr_stop_triggers_zero():
    """V-ATR 触发日 target_position 归零（20日高点回撤 ≥ k×ATR）。"""
    f = _mk_price_features(120)
    pf = _mk_portfolio(len(f))
    n = len(f)
    # 覆盖为干净价格路径：前 60 日单边缓涨（无回撤），后 60 日深跌
    close = np.empty(n)
    close[:60] = 100.0 + np.arange(60) * 0.1          # 平稳缓涨
    close[60:] = float(close[59]) * np.linspace(1.0, 0.80, n - 60)  # 深跌 20%
    f["close"] = close
    f["open"] = close
    f["high"] = np.maximum(close * 1.001, close)
    f["low"] = np.minimum(close * 0.999, close)
    out = vmod.apply_variant(f, pf, "V-ATR")
    stopped = (out["target_position"].values == 0.0)
    # 后半段（深跌段）应有触发
    assert stopped[75:].any()
    # 前半段（平稳段）不应误触发
    assert not stopped[30:55].any()
