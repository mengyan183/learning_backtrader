# -*- coding: utf-8 -*-
"""MT-01 守卫：baseline.json 必须含 inv_vol 组合权重轨（A5 闸门）。"""
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(REPO, "evolution", "baseline.json")


@pytest.fixture(scope="module")
def baseline():
    with open(BASELINE, encoding="utf-8") as fh:
        return json.load(fh)


def test_meta_has_WEIGHTING(baseline):
    """meta 必须声明组合权重口径（MT-01 验收）。"""
    assert baseline["meta"]["WEIGHTING"] == "inv_vol"


def test_portfolio_section_present(baseline):
    """必须含 portfolio 段（策略轨 + 组合权重买入持有轨）。"""
    p = baseline["portfolio"]
    assert set(p) == {"strategy", "buy_and_hold", "weights_last", "meta"}


def test_portfolio_strategy_and_bh_same_periods(baseline):
    """策略轨与组合 bh 轨同时段（full/is/oos/yearly 同构，年化非 NaN）。"""
    p = baseline["portfolio"]
    for key in ("strategy", "buy_and_hold"):
        full = p[key]["full"]
        assert full["annual_return"] == full["annual_return"], key  # 非 NaN
        assert "yearly" in p[key] and "is" in p[key] and "oos" in p[key]
    # 组合轨不是单标的满仓：权重和 = 1
    w = p["weights_last"]
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert set(w) == {"TQQQ", "SOXL", "UPRO"}


def test_portfolio_meta_weighting_declared(baseline):
    p = baseline["portfolio"]
    assert p["meta"]["weighting"] == "inv_vol"
    assert p["meta"]["basket"] == "daily_rebalance_to_target"
