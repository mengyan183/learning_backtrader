# -*- coding: utf-8 -*-
"""兼容层与等价性回归测试（设计文档 §9.2 第 12 条）。

**为什么必须存在**：v2 把 `signal.py` 拆成了包（`market_signal` + `portfolio`）。
拆分本身是重构——重构不得改变 v1 的行为。本文件是「拆分没有改变行为」的证明。

两条防线：
  1. v1 的公开 API 名字必须仍可从 `fg_system.signal` 访问
  2. 在 v1 参数下（大盘占比 1.0、无趋势折扣），v2 的核心仓计算必须与 v1 逐点相同
"""
import numpy as np
import pytest

from fg_system import config
from fg_system import signal
from fg_system.signal import legacy
from fg_system.signal import market_signal as ms


# ---------------------------------------------------------------- API 兼容

def test_v1_api_is_reexported():
    """v1 的全部公开名字必须仍可从 fg_system.signal 访问。"""
    for name in ["SignalState", "zone_of", "core_position", "update_ammo",
                 "ammo_position", "target_position", "apply_extremes",
                 "apply_extreme_fear", "throttle_ok", "clip_adjustment"]:
        assert hasattr(signal, name), "缺少 v1 公开 API: %s" % name


def test_v2_api_is_available():
    assert hasattr(signal, "market_signal")
    assert hasattr(signal, "portfolio")
    assert hasattr(signal, "MarketState")
    assert hasattr(signal, "PortfolioState")


def test_legacy_state_roundtrip_unchanged():
    st = legacy.SignalState()
    st.ammo_released = [0, 2]
    st.circuit_breaker = True
    restored = legacy.SignalState.from_dict(st.to_dict())
    assert restored.to_dict() == st.to_dict()


# ---------------------------------------------------------------- 等价性（核心）

@pytest.mark.parametrize("index_value", [0.0, 19.9, 20.0, 39.9, 40.0, 59.9,
                                         60.0, 79.9, 80.0, 100.0])
def test_market_core_equals_legacy_when_ratio_is_one(index_value, monkeypatch):
    """v1 参数下（us_equity 占比 1.0、无趋势折扣），v2 核心仓必须与 v1 逐点相同。

    这是「拆分没有改变行为」的证明。
    """
    monkeypatch.setitem(config.MARKET_CORE_RATIO, "us_equity", 1.0)
    v1 = legacy.core_position(index_value)
    v2 = ms.market_core(index_value, trend=1.0, market="us_equity")
    assert v2 == pytest.approx(v1)


def test_zone_of_equals_legacy():
    for v in np.arange(0.0, 100.1, 0.5):
        assert ms.zone_of(v) == legacy.zone_of(v)


def test_ammo_equivalence_with_single_market(monkeypatch):
    """单市场场景下，v2 portfolio 的弹药仓必须与 v1 相同。

    **v2.5 起必须同时把 `config.MARKETS` 改成单市场**：新增的「单市场弹药份额上限」
    （第 12.11 条）按 `config.MARKETS` 计算——3 批 / 2 个市场 ⇒ 单市场上限 2 批。
    单市场系统里没有「其他市场」需要保留，上限自然回到 3 批，与 v1 一致。
    """
    monkeypatch.setitem(config.MARKET_CORE_RATIO, "us_equity", 1.0)
    monkeypatch.setattr(config, "MARKETS", ["us_equity"])

    v1_state = legacy.SignalState()
    v2_state = signal.PortfolioState()
    for dd in (0.15, 0.25, 0.45, 0.65):
        v1_state, v1_ammo, _ = legacy.update_ammo(v1_state, dd)
        out = ms.MarketOutput(
            market="us_equity", core_position=0.0, drawdown=dd, trend=1.0,
            trend_blocked=False, extreme_fear=False, extreme=False,
            layer_caps={}, note="")
        v2_state, _, _ = signal.portfolio.release_ammo(v2_state, [out])

    assert v2_state.ammo_released == v1_state.ammo_released
    assert signal.portfolio.ammo_position(v2_state) == pytest.approx(
        legacy.ammo_position(v1_state))


def test_throttle_equivalence():
    """v2 的 throttle_ok 与 v1 行为一致（本层只是搬家）。"""
    v1_state = legacy.SignalState(last_rebalance_date="2026-01-05")
    v2_state = signal.PortfolioState(last_rebalance_date="2026-01-05")

    for current, target, date in [
        (0.50, 0.55, "2026-01-20"),
        (0.30, 0.60, "2026-01-07"),
        (0.30, 0.60, "2026-01-20"),
    ]:
        a = legacy.throttle_ok(v1_state, current, target, date)[0]
        b = signal.portfolio.throttle_ok(v2_state, current, target, date)[0]
        assert a == b


def test_clip_adjustment_equivalence():
    for current, target in [(0.10, 0.90), (0.50, 0.55), (0.80, 0.20)]:
        assert signal.portfolio.clip_adjustment(current, target) == pytest.approx(
            legacy.clip_adjustment(current, target))


# ---------------------------------------------------------------- 趋势过滤不污染 v1

def test_v1_path_has_no_trend_filter():
    """legacy 路径必须完全不含趋势过滤——v1 的测试靠这一点。"""
    src = open(legacy.__file__, encoding="utf-8").read()
    assert "trend" not in src.lower()


def test_market_core_trend_discount_is_new_behavior(monkeypatch):
    """趋势折扣是 v2 新增行为：v1 的 core_position 不含它。"""
    monkeypatch.setitem(config.MARKET_CORE_RATIO, "us_equity", 1.0)
    v1 = legacy.core_position(10.0)
    v2 = ms.market_core(10.0, trend=config.TREND_FILTER_FACTOR, market="us_equity")
    assert v2 == pytest.approx(v1 * config.TREND_FILTER_FACTOR)
    assert v2 < v1
