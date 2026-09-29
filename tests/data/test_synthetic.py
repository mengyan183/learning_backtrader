# -*- coding: utf-8 -*-
"""合成杠杆序列测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.data import synthetic


def test_synthetic_daily_return_formula():
    """合成日收益 = N × 底层日收益 − 产品损耗/252。"""
    und = pd.Series([0.01, -0.02, 0.03],
                    index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    out = synthetic.synthetic_returns(und, leverage=2, cost_rate=0.0252)
    daily_cost = 0.0252 / 252
    assert out.iloc[0] == pytest.approx(2 * 0.01 - daily_cost)
    assert out.iloc[1] == pytest.approx(2 * -0.02 - daily_cost)
    assert out.iloc[2] == pytest.approx(2 * 0.03 - daily_cost)


def test_synthetic_series_compounds():
    """合成价格 = ∏(1 + 合成日收益)。"""
    und = pd.Series([0.01, 0.01], index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    close = synthetic.build_synthetic_series(und, leverage=2, cost_rate=0.0, base=100.0)
    expected = 100.0 * (1 + 0.02) * (1 + 0.02)
    assert close.iloc[-1] == pytest.approx(expected)


def test_synthetic_series_first_point_is_base():
    und = pd.Series([0.05], index=pd.to_datetime(["2026-01-01"]))
    close = synthetic.build_synthetic_series(und, leverage=3, cost_rate=0.0, base=50.0)
    assert close.iloc[0] == pytest.approx(50.0 * 1.15)


def test_volatility_drag_is_negative_for_choppy_market():
    """横盘震荡时杠杆必然亏损（波动率拖累，数学必然）。"""
    rng = np.random.default_rng(42)
    und = pd.Series(rng.normal(0.0, 0.03, 500),
                    index=pd.bdate_range("2024-01-01", periods=500))
    lev3 = synthetic.build_synthetic_series(und, leverage=3, cost_rate=0.0, base=100.0)
    lev1 = synthetic.build_synthetic_series(und, leverage=1, cost_rate=0.0, base=100.0)
    assert lev3.iloc[-1] < lev1.iloc[-1]


def test_deviation_gate_zero_when_identical():
    s = pd.Series([100.0, 110.0, 121.0],
                  index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    assert synthetic.deviation_gate(s, s.copy()) == pytest.approx(0.0, abs=1e-9)


def test_deviation_gate_positive_when_synthetic_outperforms():
    real = pd.Series([100.0, 100.0, 100.0],
                     index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    synth = pd.Series([100.0, 110.0, 121.0], index=real.index)
    assert synthetic.deviation_gate(synth, real) > 0


def test_deviation_gate_nan_when_too_few_points():
    s = pd.Series([100.0], index=pd.to_datetime(["2026-01-01"]))
    assert np.isnan(synthetic.deviation_gate(s, s.copy()))


def test_check_gate_raises_above_threshold():
    """偏离真正超标（非 too-few 分支）时必须抛异常。"""
    idx = pd.bdate_range("2024-01-01", periods=120)
    real = pd.Series(100.0, index=idx)
    synth = pd.Series([100.0 * (1.002 ** i) for i in range(120)], index=idx)
    with pytest.raises(synthetic.SyntheticQualityError) as exc:
        synthetic.check_gate("BITX", synth, real, gate=0.05)
    assert "偏离" in str(exc.value)


def test_check_gate_raises_when_too_few_points():
    """点数不足 60 时抛异常，不得静默通过。"""
    idx = pd.bdate_range("2024-01-01", periods=3)
    s = pd.Series([100.0, 110.0, 121.0], index=idx)
    with pytest.raises(synthetic.SyntheticQualityError) as exc:
        synthetic.check_gate("BITX", s, s.copy(), gate=0.05)
    assert "不足" in str(exc.value)


def test_check_gate_passes_below_threshold():
    """≥60 点且偏离在阈值内时通过。"""
    idx = pd.bdate_range("2024-01-01", periods=120)
    s = pd.Series([100.0 * (1.0001 ** i) for i in range(120)], index=idx)
    assert synthetic.check_gate("BITX", s, s.copy(), gate=0.05) is True


def test_calibrate_cost_rate_reproduces_real():
    """校准后合成累计收益必须与真实一致（容差 1%）。"""
    rng = np.random.default_rng(11)
    n = 300
    und_ret = pd.Series(rng.normal(0.0005, 0.03, n),
                        index=pd.bdate_range("2024-01-01", periods=n))
    real = 100.0 * (1 + 2 * und_ret - 0.30 / 252).cumprod()
    rate = synthetic.calibrate_cost_rate(und_ret, real, leverage=2)
    rebuilt = 100.0 * (1 + 2 * und_ret - rate / 252).cumprod()
    assert rebuilt.iloc[-1] == pytest.approx(real.iloc[-1], rel=0.01)


def test_calibrate_recovers_known_rate():
    """已知成本率应能被反推出来。"""
    rng = np.random.default_rng(3)
    n = 400
    und_ret = pd.Series(rng.normal(0.0, 0.025, n),
                        index=pd.bdate_range("2024-01-01", periods=n))
    true_rate = 0.25
    real = 100.0 * (1 + 2 * und_ret - true_rate / 252).cumprod()
    rate = synthetic.calibrate_cost_rate(und_ret, real, leverage=2)
    assert rate == pytest.approx(true_rate, abs=0.01)


def test_validate_against_real_flags_implausible_rate():
    """校准出的成本率超过阈值时必须置 warning=True。"""
    rng = np.random.default_rng(5)
    n = 120
    und_ret = pd.Series(rng.normal(0.0, 0.02, n),
                        index=pd.bdate_range("2024-01-01", periods=n))
    real = 100.0 * (1 + 2 * und_ret - 0.40 / 252).cumprod()
    rate = synthetic.calibrate_cost_rate(und_ret, real, leverage=2)
    assert rate > 0.15
    assert synthetic.is_implausible(rate) is True
