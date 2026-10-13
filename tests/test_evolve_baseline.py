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
    """必须含 portfolio 段（策略轨 + 组合权重买入持有轨 + MT-07 日序列）。"""
    p = baseline["portfolio"]
    assert set(p) == {"strategy", "buy_and_hold", "daily", "weights_last", "meta"}


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


def test_portfolio_daily_series_feeds_cvar(baseline):
    """MT-07（B1）：daily 序列可直接喂 cvar()，且 max_drawdown 交叉核对一致。"""
    import pandas as pd
    from fg_system.risk import cvar, max_drawdown

    d = baseline["portfolio"]["daily"]
    assert len(d["date"]) >= 30                      # 点数门槛
    assert len(d["date"]) == len(d["strategy_ret"]) == len(d["bh_portfolio_ret"])
    assert len(d["strategy_nav"]) == len(d["date"])
    # 序列可直接喂 cvar()（尾部概率语义：0.05 = 最差 5%）
    rets = pd.Series(d["strategy_ret"])
    c95, c99 = cvar(rets, 0.05), cvar(rets, 0.01)
    assert c95 is not None and c99 is not None
    assert c99 < c95                                  # 更极端尾部损失更大
    # 交叉核对：用 daily 序列重算 max_drawdown 应与 full.max_drawdown 一致
    md_new = max_drawdown(rets)
    md_old = baseline["portfolio"]["strategy"]["full"]["max_drawdown"]
    assert abs(abs(md_new) - abs(md_old)) < 0.005
    # meta 附 generated_at + features_range + daily_points
    assert baseline["portfolio"]["meta"]["generated_at"]
    assert baseline["portfolio"]["meta"]["features_range"]
    assert baseline["portfolio"]["meta"]["daily_points"] == len(d["date"])
