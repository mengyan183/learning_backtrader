# -*- coding: utf-8 -*-
"""信号层测试（§7、§8、§9）。"""
import pandas as pd
import pytest

from fg_system import config
from fg_system import signal


# ---------------------------------------------------------------- 核心仓（§7.2）
def test_core_position_five_zones():
    """五档映射：饱和度 × CORE_CAP。

    字面值 0.45 是**故意的**（不写成 config.CORE_CAP）：CORE_CAP 变更必须走
    docs/trading-discipline.md 第 8 条流程，写成字面值让参数变更**必须**同步改本测试。
    v2.1（2026-09-22）由 0.70 下调至 0.45，见该文档第 12.1 条。
    """
    assert config.CORE_CAP == pytest.approx(0.45)
    assert signal.core_position(10) == pytest.approx(0.45)
    assert signal.core_position(30) == pytest.approx(0.45 * 0.75)
    assert signal.core_position(50) == pytest.approx(0.45 * 0.50)
    assert signal.core_position(70) == pytest.approx(0.45 * 0.25)
    assert signal.core_position(90) == pytest.approx(0.0)


def test_core_position_boundaries_are_lower_inclusive():
    """边界取下闭区间：20 属于恐惧档，80 属于极贪档。"""
    assert signal.core_position(20) == pytest.approx(0.45 * 0.75)
    assert signal.core_position(80) == pytest.approx(0.0)


def test_core_position_nan_returns_none():
    assert signal.core_position(float("nan")) is None
    assert signal.core_position(None) is None


def test_zone_of_maps_all_ranges():
    assert signal.zone_of(0) == 0
    assert signal.zone_of(19.99) == 0
    assert signal.zone_of(40) == 2
    assert signal.zone_of(100) == 4


# ---------------------------------------------------------------- 弹药池（§7.3）
def test_ammo_released_progressively():
    """回撤穿越 20/40/60% 依次释放三批，各批只释放一次。

    每批 = `AMMO_CAP / 3` ≈ 6.67%（v2.4 定 `AMMO_CAP` = 20%，
    见 docs/trading-discipline.md 第 12.7 条）。
    字面值 0.20 是**故意的**：`AMMO_CAP` 变更必须走第 8 条流程，故同步改本测试。
    """
    per = 0.20 / 3
    st = signal.SignalState()
    st, ammo, _ = signal.update_ammo(st, drawdown=0.25)
    assert ammo == pytest.approx(per)
    st, ammo, _ = signal.update_ammo(st, drawdown=0.45)
    assert ammo == pytest.approx(2 * per)
    st, ammo, _ = signal.update_ammo(st, drawdown=0.65)
    assert ammo == pytest.approx(3 * per)
    # 再次穿越不重复释放
    st, ammo, _ = signal.update_ammo(st, drawdown=0.70)
    assert ammo == pytest.approx(3 * per)


def test_ammo_jump_releases_multiple_batches_at_once():
    """回撤一次性跳到 65% 时，三批同时释放（不要求逐档穿越）。"""
    st = signal.SignalState()
    st, ammo, newly = signal.update_ammo(st, drawdown=0.65)
    assert ammo == pytest.approx(0.20)
    assert newly == [0, 1, 2]


def test_ammo_not_released_when_drawdown_shallow():
    st = signal.SignalState()
    st, ammo, newly = signal.update_ammo(st, drawdown=0.05)
    assert ammo == pytest.approx(0.0)
    assert newly == []


def test_ammo_nan_drawdown_keeps_state():
    st = signal.SignalState(ammo_released=[0])
    st, ammo, newly = signal.update_ammo(st, drawdown=float("nan"))
    assert ammo == pytest.approx(0.20 / 3)
    assert newly == []


def test_target_position_sums_core_and_ammo():
    st = signal.SignalState()
    st, _, _ = signal.update_ammo(st, drawdown=0.25)
    assert signal.target_position(10, st) == pytest.approx(0.45 + 0.20 / 3)


def test_target_position_none_when_index_invalid():
    assert signal.target_position(float("nan"), signal.SignalState()) is None


# ---------------------------------------------------------------- 状态持久化
def test_state_roundtrip_json_serializable():
    st = signal.SignalState(ammo_released=[0, 2], circuit_breaker=True,
                            cb_trigger_index=90.0, cb_low_price={"TQQQ": 10.0})
    restored = signal.SignalState.from_dict(st.to_dict())
    assert restored.ammo_released == [0, 2]
    assert restored.circuit_breaker is True
    assert restored.cb_low_price == {"TQQQ": 10.0}


# ---------------------------------------------------------------- 极贪熔断（§8.1）
def test_circuit_breaker_triggers_at_threshold():
    st = signal.SignalState()
    st, target, reason = signal.apply_extremes(st, fg_index=90.0, date="2024-01-02",
                                               prices={"TQQQ": 100.0}, target=0.7)
    assert st.circuit_breaker is True
    assert target == pytest.approx(config.EXTREME_GREED_FLOOR)
    assert "熔断" in reason


def test_circuit_breaker_does_not_trigger_below_threshold():
    st = signal.SignalState()
    st, target, reason = signal.apply_extremes(st, fg_index=84.9, date="2024-01-02",
                                               prices={"TQQQ": 100.0}, target=0.7)
    assert st.circuit_breaker is False
    assert target == pytest.approx(0.7)


def test_circuit_breaker_unlocks_when_index_falls():
    """解锁条件 ①：指数回落至 < 60。"""
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 90.0})
    st, target, reason = signal.apply_extremes(st, fg_index=55.0, date="2024-01-20",
                                               prices={"TQQQ": 95.0}, target=0.7)
    assert st.circuit_breaker is False
    assert target == pytest.approx(0.7)
    assert "指数回落" in reason


def test_circuit_breaker_unlocks_on_rebound():
    """解锁条件 ②：标的自熔断后低点反弹 >= 10%（标的级独立解锁）。"""
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 100.0})
    st, target, reason = signal.apply_extremes(st, fg_index=80.0, date="2024-01-20",
                                               prices={"TQQQ": 111.0}, target=0.7)
    assert st.circuit_breaker is False
    assert "反弹" in reason


def test_circuit_breaker_unlocks_on_index_drop():
    """解锁条件 ③：指数自熔断峰值回落 >= 15 点。"""
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 100.0})
    st, target, reason = signal.apply_extremes(st, fg_index=74.0, date="2024-01-20",
                                               prices={"TQQQ": 101.0}, target=0.7)
    assert st.circuit_breaker is False
    assert "回落" in reason


def test_circuit_breaker_stays_locked_when_nothing_unlocks():
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 100.0})
    st, target, reason = signal.apply_extremes(st, fg_index=88.0, date="2024-01-20",
                                               prices={"TQQQ": 101.0}, target=0.7)
    assert st.circuit_breaker is True
    assert target == pytest.approx(config.EXTREME_GREED_FLOOR)


def test_circuit_breaker_updates_low_price():
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 100.0})
    st, _, _ = signal.apply_extremes(st, fg_index=88.0, date="2024-01-20",
                                     prices={"TQQQ": 92.0}, target=0.7)
    assert st.cb_low_price["TQQQ"] == pytest.approx(92.0)


def test_circuit_breaker_ignores_nan_price():
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 100.0})
    st, _, _ = signal.apply_extremes(st, fg_index=88.0, date="2024-01-20",
                                     prices={"TQQQ": float("nan")}, target=0.7)
    assert st.cb_low_price["TQQQ"] == pytest.approx(100.0)


# ---------------------------------------------------------------- 极恐加仓（§8.2）
def test_extreme_fear_releases_extra_ammo():
    st = signal.SignalState()
    st, released, reason = signal.apply_extreme_fear(st, fg_index=8.0, date="2024-01-02")
    assert released == 1
    assert len(st.ammo_released) == 1
    assert "极恐" in reason


def test_extreme_fear_no_action_above_threshold():
    st = signal.SignalState()
    st, released, _ = signal.apply_extreme_fear(st, fg_index=15.0, date="2024-01-02")
    assert released == 0


def test_extreme_fear_cooldown_blocks_repeat():
    st = signal.SignalState(ammo_released=[0], last_extreme_fear_date="2024-01-02")
    st, released, _ = signal.apply_extreme_fear(st, fg_index=8.0, date="2024-02-01")
    assert released == 0


def test_extreme_fear_allowed_after_cooldown():
    st = signal.SignalState(ammo_released=[0], last_extreme_fear_date="2024-01-02")
    st, released, _ = signal.apply_extreme_fear(st, fg_index=8.0, date="2024-04-15")
    assert released == 1


def test_extreme_fear_cannot_release_beyond_cap():
    st = signal.SignalState(ammo_released=[0, 1, 2])
    st, released, _ = signal.apply_extreme_fear(st, fg_index=5.0, date="2024-01-02")
    assert released == 0


# ---------------------------------------------------------------- 防抖动（§9）
def test_throttle_blocks_small_adjustment():
    st = signal.SignalState(last_rebalance_date="2024-01-02")
    ok, reason = signal.throttle_ok(st, current=0.50, target=0.55, date="2024-01-03",
                                    extreme=False)
    assert ok is False
    assert "阈值" in reason


def test_throttle_blocks_within_cooldown():
    st = signal.SignalState(last_rebalance_date="2024-01-02")
    ok, reason = signal.throttle_ok(st, current=0.50, target=0.70, date="2024-01-04",
                                    extreme=False)
    assert ok is False
    assert "冷却" in reason


def test_throttle_allows_after_cooldown():
    st = signal.SignalState(last_rebalance_date="2024-01-02")
    ok, reason = signal.throttle_ok(st, current=0.50, target=0.70, date="2024-01-10",
                                    extreme=False)
    assert ok is True


def test_throttle_extreme_bypasses_all():
    st = signal.SignalState(last_rebalance_date="2024-01-02")
    ok, reason = signal.throttle_ok(st, current=0.50, target=0.55, date="2024-01-03",
                                    extreme=True)
    assert ok is True


def test_throttle_invalid_position_blocked():
    st = signal.SignalState()
    ok, reason = signal.throttle_ok(st, current=None, target=0.7, date="2024-01-10")
    assert ok is False


def test_clip_single_adjustment():
    assert signal.clip_adjustment(0.0, 0.70) == pytest.approx(config.MAX_SINGLE_ADJUST)
    assert signal.clip_adjustment(0.50, 0.60) == pytest.approx(0.60)
    assert signal.clip_adjustment(0.60, 0.00) == pytest.approx(0.30)


# ---------------------------------------------------------------- 纯函数约定（§3.4）
def test_update_ammo_does_not_mutate_input_state():
    """§3.4 硬约定：信号层必须纯函数，不得修改传入的 state。

    否则调用方传入 state 副本（并行回测、多组合对比）时会静默丢失状态。
    """
    st = signal.SignalState()
    snapshot = st.to_dict()
    st2, _, _ = signal.update_ammo(st, drawdown=0.25)
    assert st.to_dict() == snapshot, "update_ammo 修改了入参 state"
    assert st2.ammo_released == [0]
    assert st2 is not st


def test_apply_extreme_fear_does_not_mutate_input_state():
    st = signal.SignalState()
    snapshot = st.to_dict()
    st2, released, _ = signal.apply_extreme_fear(st, fg_index=8.0, date="2024-01-02")
    assert st.to_dict() == snapshot, "apply_extreme_fear 修改了入参 state"
    assert released == 1
    assert st2.ammo_released == [0]
    assert st2 is not st


def test_apply_extremes_does_not_mutate_input_state():
    st = signal.SignalState()
    snapshot = st.to_dict()
    signal.apply_extremes(st, fg_index=90.0, date="2024-01-02",
                          prices={"TQQQ": 100.0}, target=0.7)
    assert st.to_dict() == snapshot, "apply_extremes 修改了入参 state"


def test_cb_low_price_is_deep_copied():
    """熔断低点字典必须是副本，否则改副本会污染原状态。"""
    st = signal.SignalState()
    st2, _, _ = signal.apply_extremes(st, fg_index=90.0, date="2024-01-02",
                                      prices={"TQQQ": 100.0}, target=0.7)
    st2.cb_low_price["TQQQ"] = 1.0
    assert st.cb_low_price == {}
