# -*- coding: utf-8 -*-
"""R1.4 归一化/档位对照实验：三方案档位函数 + 对齐口径。

覆盖：
- plan_a_zone：生产 fg_index + 固定边界（index=date）
- plan_b_zone：z-score 截断合成指数在 [0,100] 且档位合法
- plan_c_zone：动态档位（滚动百分位）
- regime_shift：A vs C 偏移统计
"""
import numpy as np
import pandas as pd

from fg_system.index import factor_zone
from scripts.norm_compare import (FACTOR_COLS, plan_a_zone, plan_b_zone,
                                  plan_c_zone, _regime_shift)


def _sample_features(n=400):
    rng = np.random.default_rng(42)
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    df = pd.DataFrame({"date": dates})
    for c in FACTOR_COLS:
        df[c] = 50 + 20 * np.sin(np.linspace(0, 8, n)) + rng.normal(0, 5, n)
    # fg_index = 因子均值（近似合成）
    df["fg_index"] = df[FACTOR_COLS].mean(axis=1).clip(0, 100)
    return df


def test_plan_a_uses_date_index():
    f = _sample_features()
    z = plan_a_zone(f)
    assert isinstance(z.index, pd.DatetimeIndex)
    assert z.notna().sum() > 0
    assert set(z.dropna().unique()).issubset({0, 1, 2, 3, 4})


def test_plan_b_bounds_and_zones():
    f = _sample_features()
    z, idx = plan_b_zone(f)
    valid = idx.dropna()
    assert valid.between(0, 100).all()
    assert set(z.dropna().unique()).issubset({0, 1, 2, 3, 4})
    # z-score 会改变分布：与 A 不完全相同
    zA = plan_a_zone(f)
    assert (z != zA).any()


def test_plan_c_dynamic():
    f = _sample_features()
    z = plan_c_zone(f)
    assert set(z.dropna().unique()).issubset({0, 1, 2, 3, 4})
    assert z.dropna().shape[0] >= 0.8 * len(f)   # min_periods=60 后绝大多数有档位


def test_regime_shift_stats():
    f = _sample_features()
    rs = _regime_shift(plan_a_zone(f), plan_c_zone(f))
    assert rs["n"] > 0
    assert 0 <= rs["pct_same"] <= 1
    assert 0 <= rs["pct_shift_ge1"] <= 1
    assert sum(rs["shift_dist"].values()) == rs["n"]


def test_factor_zone_consistency():
    assert factor_zone(20.0) == 1 and factor_zone(80.0) == 4
