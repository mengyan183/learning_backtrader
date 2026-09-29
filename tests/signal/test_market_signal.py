# -*- coding: utf-8 -*-
"""market_signal 单市场层测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system.signal import market_signal as ms


# ---------------------------------------------------------------- 趋势过滤

def test_trend_factor_is_one_above_ma():
    close = pd.Series(np.linspace(100, 200, 300),
                      index=pd.bdate_range("2020-01-01", periods=300))
    tf = ms.trend_factor_series(close)
    assert tf.iloc[-1] == pytest.approx(1.0)


def test_trend_factor_is_discounted_below_ma():
    close = pd.Series(np.linspace(200, 100, 300),
                      index=pd.bdate_range("2020-01-01", periods=300))
    tf = ms.trend_factor_series(close)
    assert tf.iloc[-1] == pytest.approx(config.TREND_FILTER_FACTOR)


def test_trend_factor_is_one_during_ma_warmup():
    """均线窗口不足时不做限制（返回 1.0），且不得抛异常。"""
    close = pd.Series(np.linspace(100, 110, 50),
                      index=pd.bdate_range("2020-01-01", periods=50))
    tf = ms.trend_factor_series(close)
    assert (tf == 1.0).all()


def test_trend_factor_handles_nan():
    close = pd.Series([100.0, np.nan, 102.0],
                      index=pd.bdate_range("2020-01-01", periods=3))
    tf = ms.trend_factor_series(close)
    assert len(tf) == 3


# ---------------------------------------------------------------- 核心仓

def test_market_core_without_trend():
    """无趋势限制时，核心仓 = 饱和度 × CORE_CAP × MARKET_CORE_RATIO。"""
    core = ms.market_core(10.0, trend=1.0, market="us_equity")
    expected = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"] * 1.0
    assert core == pytest.approx(expected)


def test_market_core_with_trend_discount():
    core = ms.market_core(10.0, trend=config.TREND_FILTER_FACTOR, market="us_equity")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert core == pytest.approx(full * config.TREND_FILTER_FACTOR)


def test_market_core_nan_index_returns_none():
    assert ms.market_core(float("nan"), trend=1.0, market="us_equity") is None


def test_crypto_core_is_smaller_than_equity_core():
    """同样指数下，加密核心仓上限必须小于大盘（v2.1：13.5% vs 31.5%）。"""
    eq = ms.market_core(10.0, trend=1.0, market="us_equity")
    cr = ms.market_core(10.0, trend=1.0, market="crypto")
    assert cr < eq


# ---------------------------------------------------------------- 分层上限

def test_layer_caps_crypto_three_layers():
    """v2.1：三层上限收紧至 80% / 50% / 30%（trading-discipline.md 第 12.1 条）。"""
    caps = ms.layer_cap_position(1.0, market="crypto")
    assert caps["btc_beta"] == pytest.approx(0.80)
    assert caps["stock_high_beta"] == pytest.approx(0.50)
    assert caps["stock_ops_beta"] == pytest.approx(0.30)


def test_layer_caps_scales_with_core():
    caps = ms.layer_cap_position(0.135, market="crypto")
    assert caps["btc_beta"] == pytest.approx(0.135 * 0.80)
    assert caps["stock_high_beta"] == pytest.approx(0.135 * 0.50)


def test_btc_layer_cap_leaves_room_outside_btc():
    """BTC 层上限 < 1.0 ⇒ 强制 ≥20% 的加密核心仓配置在 BTC 层之外。

    依据：真实轨实测 MSTX 最大回撤 -99.61%（接近净值归零）。
    """
    core = 0.135
    caps = ms.layer_cap_position(core, market="crypto")
    assert caps["btc_beta"] < core
    assert core - caps["btc_beta"] == pytest.approx(core * 0.20)


def test_layer_caps_empty_for_equity():
    assert ms.layer_cap_position(0.49, market="us_equity") == {}


# ---------------------------------------------------------------- 加密极贪分批

def test_greed_tiers_trigger_in_order():
    st = ms.MarketState(market="crypto")
    st, note = ms.apply_greed_tiers(st, 86.0)
    assert st.greed_tier == 1
    st, note = ms.apply_greed_tiers(st, 91.0)
    assert st.greed_tier == 2
    st, note = ms.apply_greed_tiers(st, 96.0)
    assert st.greed_tier == 3


def test_greed_tiers_only_trigger_once():
    st = ms.MarketState(market="crypto")
    st, _ = ms.apply_greed_tiers(st, 86.0)
    st, _ = ms.apply_greed_tiers(st, 87.0)
    assert st.greed_tier == 1


def test_greed_tiers_restore_one_by_one():
    """回落至 <60 时**逐档恢复**，不是一次性恢复。"""
    st = ms.MarketState(market="crypto")
    for v in (86.0, 91.0, 96.0):
        st, _ = ms.apply_greed_tiers(st, v)
    assert st.greed_tier == 3
    st, _ = ms.apply_greed_tiers(st, 55.0)
    assert st.greed_tier == 2
    st, _ = ms.apply_greed_tiers(st, 55.0)
    assert st.greed_tier == 1


def test_greed_tier_factor_values():
    """三档对应的核心仓系数：2/3、1/3、1/4。"""
    assert ms.greed_tier_factor(0) == pytest.approx(1.0)
    assert ms.greed_tier_factor(1) == pytest.approx(2.0 / 3.0)
    assert ms.greed_tier_factor(2) == pytest.approx(1.0 / 3.0)
    assert ms.greed_tier_factor(3) == pytest.approx(0.25)


def test_market_state_is_deep_copied():
    """§3.4 硬约定：状态变更函数不得修改入参。"""
    st = ms.MarketState(market="crypto")
    snapshot = st.to_dict()
    ms.apply_greed_tiers(st, 96.0)
    assert st.to_dict() == snapshot


# ---------------------------------------------------------------- market_target

def test_market_target_greed_tier_replaces_five_tier_saturation():
    """档位 > 0 时必须替换五档饱和度，而不是相乘。

    背景：五档在指数 >=80 时给饱和度 0（清仓），而档位在 >=85 触发——
    若写成相乘，档位永远对着 0 做乘法，成为死代码。
    设计 §6.5 的初衷是「不一次性清仓、分批递减」，故档位应设下限。
    """
    st = ms.MarketState(market="crypto")
    out, st = ms.market_target(
        index_value=86.0, drawdown=0.0, trend=1.0, state=st, market="crypto")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    # 86.0 命中第 1 档 → 2/3；五档此时是 0.0，但档位必须覆盖它
    assert st.greed_tier == 1
    assert out.core_position == pytest.approx(full * 2.0 / 3.0)
    assert out.core_position > 0.0, "档位必须覆盖五档的清仓，否则是死代码"


def test_market_target_greed_tier_deepens_with_index():
    st = ms.MarketState(market="crypto")
    out, st = ms.market_target(
        index_value=96.0, drawdown=0.0, trend=1.0, state=st, market="crypto")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert st.greed_tier == 3
    assert out.core_position == pytest.approx(full * 0.25)


def test_market_target_greed_tier_respects_trend_filter():
    """趋势过滤优先级最高：档位也要被趋势系数打折。"""
    st = ms.MarketState(market="crypto")
    out, st = ms.market_target(
        index_value=86.0, drawdown=0.0, trend=config.TREND_FILTER_FACTOR,
        state=st, market="crypto")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert out.core_position == pytest.approx(full * config.TREND_FILTER_FACTOR * 2.0 / 3.0)


def test_market_target_without_tier_uses_five_tier():
    """档位 = 0 时沿用五档饱和度（极恐 100%）。"""
    st = ms.MarketState(market="crypto")
    out, st = ms.market_target(
        index_value=10.0, drawdown=0.0, trend=1.0, state=st, market="crypto")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert st.greed_tier == 0
    assert out.core_position == pytest.approx(full * 1.0)


def test_market_target_trend_priority_over_extreme_fear():
    """趋势过滤优先级最高：极恐 + 跌破均线时，上限取趋势结果。"""
    st = ms.MarketState(market="us_equity")
    out, st = ms.market_target(
        index_value=5.0, drawdown=0.0, trend=config.TREND_FILTER_FACTOR,
        state=st, market="us_equity")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert out.core_position == pytest.approx(full * config.TREND_FILTER_FACTOR)


def test_market_target_reports_extreme_fear():
    st = ms.MarketState(market="crypto")
    out, st = ms.market_target(
        index_value=8.0, drawdown=0.0, trend=1.0, state=st, market="crypto")
    assert out.extreme_fear is True


def test_market_target_nan_index_returns_none_core():
    st = ms.MarketState(market="us_equity")
    out, st = ms.market_target(
        index_value=float("nan"), drawdown=0.0, trend=1.0,
        state=st, market="us_equity")
    assert out.core_position is None


def test_market_target_circuit_breaker_replaces_five_tier_saturation():
    """熔断必须**替换**五档饱和度（设底仓），不是取 min。

    背景：熔断在指数 >=85 触发，而五档在 >=80 时已给饱和度 0（清仓）。
    若写成 min(core, full*floor)，熔断永远对着 0 取最小，「25% 底仓」成为死代码
    ——而设计 §8.1 原话是「减至 25% 底仓（不清仓——避免完全踏空后续反弹）」。
    """
    st = ms.MarketState(market="us_equity")
    out, st = ms.market_target(
        index_value=90.0, drawdown=0.0, trend=1.0, state=st, market="us_equity")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert st.circuit_breaker is True
    assert out.core_position == pytest.approx(full * config.EXTREME_GREED_FLOOR)
    assert out.core_position > 0.0, "熔断底仓必须覆盖五档的清仓，否则是死代码"


def test_market_target_circuit_breaker_maintained_next_day():
    """熔断次日未达解锁条件时，必须维持底仓（跨日状态机）。"""
    st = ms.MarketState(market="us_equity")
    out1, st = ms.market_target(
        index_value=90.0, drawdown=0.0, trend=1.0, state=st, market="us_equity")
    out2, st = ms.market_target(
        index_value=88.0, drawdown=0.0, trend=1.0, state=st, market="us_equity")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert st.circuit_breaker is True
    assert out2.core_position == pytest.approx(full * config.EXTREME_GREED_FLOOR)


def test_market_target_circuit_breaker_unlocks_below_threshold():
    """指数回落至 < EXTREME_GREED_UNLOCK_INDEX 时解锁，恢复五档。"""
    st = ms.MarketState(market="us_equity")
    out1, st = ms.market_target(
        index_value=90.0, drawdown=0.0, trend=1.0, state=st, market="us_equity")
    out2, st = ms.market_target(
        index_value=30.0, drawdown=0.0, trend=1.0, state=st, market="us_equity")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert st.circuit_breaker is False
    # 指数 30 → 五档「恐惧」饱和度 0.75
    assert out2.core_position == pytest.approx(full * 0.75)
