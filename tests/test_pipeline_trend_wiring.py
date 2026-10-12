# -*- coding: utf-8 -*-
"""P-2026-10-12-trend-wiring 接线测试（选项 ii：core×trend + ammo）。

守卫：
  1. 接线后 blocked 日 target = core×trend + ammo（弹药豁免）；
  2. 接线后 target ≤ v1 target（trend≤1 只降核心仓，弹药豁免不增仓）；
  3. warmup 行 target 保持 NaN；
  4. trend / trend_blocked 列存在且 blocked 掩码 = trend<1.0。
"""
import numpy as np
import pandas as pd
import pytest

from fg_system import pipeline


@pytest.fixture(scope="module")
def v2():
    """接线后的大盘 features（module 级缓存）。"""
    return pipeline.run_equity_v2()


@pytest.fixture(scope="module")
def v1():
    """未接线的 v1 run 输出（对照）。"""
    return pipeline.run(write=False)


def test_wiring_columns_present(v2):
    assert "trend" in v2.columns
    assert "trend_blocked" in v2.columns
    assert (v2["trend"] >= 0).all()


def test_wiring_blocked_mask_consistent(v2):
    blocked = v2["trend_blocked"].fillna(False)
    assert (v2.loc[blocked, "trend"] < 1.0).all()
    assert (v2.loc[~blocked, "trend"] >= 1.0 - 1e-12).all()


def test_wiring_exempts_ammo(v2, v1):
    """接线公式逐行成立：target[T] = core[T-1]×trend[T-1] + ammo[T-1]（弹药豁免）。"""
    common = v2.index.intersection(v1.index)
    a = v2.loc[common]
    b = v1.loc[common]
    valid = b["target_position"].notna()
    if valid.any():
        prev_trend = a["trend"].shift(1).fillna(1.0)
        wired = b["core_position"].shift(1) * prev_trend \
            + b["ammo_position"].shift(1).fillna(0.0)
        assert np.allclose(
            a.loc[valid, "target_position"].values, wired[valid].values,
            rtol=1e-9, atol=1e-12)
        # 弹药豁免：打折日 target ≥ 纯核心打折版
        blocked_prev = prev_trend < 1.0 - 1e-12
        if (valid & blocked_prev).any():
            core_only = b["core_position"].shift(1) * prev_trend
            assert np.all(
                a.loc[valid & blocked_prev, "target_position"]
                >= core_only[valid & blocked_prev] - 1e-12)


def test_wiring_never_exceeds_v1_target(v2, v1):
    """接线不增加仓位：target ≤ v1 target（trend∈{0.5,1.0} 只降不升）。"""
    common = v2.index.intersection(v1.index)
    a = v2.loc[common, "target_position"]
    b = v1.loc[common, "target_position"]
    valid = b.notna()
    assert np.all(a[valid].values <= b[valid].values + 1e-12)


def test_wiring_warmup_stays_nan(v2, v1):
    """warmup（v1 target NaN）行接线后仍为 NaN。"""
    common = v2.index.intersection(v1.index)
    warm = v1.loc[common, "target_position"].isna()
    if warm.any():
        assert v2.loc[common[warm], "target_position"].isna().all()
