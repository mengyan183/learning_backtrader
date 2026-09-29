# -*- coding: utf-8 -*-
"""portfolio 组合级共享弹药池测试。"""
import pytest

from fg_system import config
from fg_system.signal import portfolio as pf
from fg_system.signal.market_signal import MarketOutput


def _out(market, drawdown, core=0.4, extreme_fear=False):
    return MarketOutput(
        market=market, core_position=core, drawdown=drawdown, trend=1.0,
        trend_blocked=False, extreme_fear=extreme_fear, extreme=False,
        layer_caps={}, note="")


# ---------------------------------------------------------------- 优先级

def test_pending_threshold_first_batch():
    st = pf.PortfolioState()
    assert pf.pending_threshold(st, "us_equity") == pytest.approx(0.20)
    assert pf.pending_threshold(st, "crypto") == pytest.approx(0.30)


def test_pending_threshold_advances_after_release():
    st = pf.PortfolioState(market_batches={"us_equity": 1})
    assert pf.pending_threshold(st, "us_equity") == pytest.approx(0.40)


def test_pending_threshold_none_when_exhausted():
    st = pf.PortfolioState(market_batches={"us_equity": 3})
    assert pf.pending_threshold(st, "us_equity") is None


def test_priority_is_ratio_not_absolute():
    """大盘 25/20 = 1.25 > 加密 35/30 = 1.167 → 大盘优先。

    这证明用的是比值：若用绝对值，加密（35）会优先。
    """
    st = pf.PortfolioState()
    p_eq = pf.ammo_priority(st, _out("us_equity", 0.25))
    p_cr = pf.ammo_priority(st, _out("crypto", 0.35))
    assert p_eq > p_cr


def test_priority_none_when_below_threshold():
    st = pf.PortfolioState()
    assert pf.ammo_priority(st, _out("us_equity", 0.10)) is None


# ---------------------------------------------------------------- 共享池

def test_release_single_market():
    st = pf.PortfolioState()
    st, newly, note = pf.release_ammo(st, [_out("us_equity", 0.25)])
    assert len(st.ammo_released) == 1
    assert st.market_batches["us_equity"] == 1
    assert newly == 1


def test_release_keeps_only_once_per_market_batch():
    """同一批不得重复释放。"""
    st = pf.PortfolioState()
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.25)])
    st, newly, _ = pf.release_ammo(st, [_out("us_equity", 0.25)])
    assert newly == 0
    assert len(st.ammo_released) == 1


def test_release_deeper_batch_next_day():
    st = pf.PortfolioState()
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.25)])
    st, newly, _ = pf.release_ammo(st, [_out("us_equity", 0.45)])
    assert newly == 1
    assert st.market_batches["us_equity"] == 2


def test_pool_exhausted_stops_release():
    """池子共 3 个槽位，**但单市场最多 2 批**（第 12.11 条）。

    因此「同一市场连打 3 次」只能成功 2 次——第 3 批必须留给另一市场。
    这正是要修的问题：实测**加密把 3 批全拿走、大盘拿到 0 批**。
    """
    st = pf.PortfolioState()
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.25)])
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.45)])
    st, newly, _ = pf.release_ammo(st, [_out("us_equity", 0.65)])
    assert newly == 0, "单市场不得拿走第 3 批（必须为另一市场保留）"
    assert len(st.ammo_released) == 2


def test_release_both_markets_can_fill_pool():
    """两个市场各拿自己的份额后，池子才能满 3 批。"""
    st = pf.PortfolioState()
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.65)])
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.65)])
    st, _, _ = pf.release_ammo(st, [_out("crypto", 0.80)])
    assert len(st.ammo_released) == 3
    assert st.market_batches["us_equity"] == 2
    assert st.market_batches["crypto"] == 1
    # 池子已满，再触发无效
    st, newly, _ = pf.release_ammo(st, [_out("crypto", 0.80)])
    assert newly == 0


def test_market_batch_cap_reserves_for_other_markets():
    """上限必须为**其他每个**市场保留至少 1 批（第 12.11 条）。"""
    assert pf.market_batch_cap(n_markets=2, n_batches=3) == 2
    assert pf.market_batch_cap(n_markets=1, n_batches=3) == 3
    assert pf.market_batch_cap(n_markets=3, n_batches=3) == 1
    # 上限不得低于 1（否则小市场永远拿不到弹药）
    assert pf.market_batch_cap(n_markets=5, n_batches=3) == 1


def test_extreme_fear_respects_batch_cap():
    """极恐提前释放路径**不得绕过**份额上限（第 12.11 条）。"""
    st = pf.PortfolioState()
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.65)])
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.65)])
    assert st.market_batches["us_equity"] == 2
    st, n, _ = pf.apply_extreme_fear(
        st, [_out("us_equity", 0.0, extreme_fear=True)], "2026-01-05")
    assert n == 0


def test_conflict_higher_ratio_wins():
    """同日两市场触发，比值大者先得。"""
    st = pf.PortfolioState()
    st, newly, note = pf.release_ammo(
        st, [_out("crypto", 0.35), _out("us_equity", 0.25)])
    # 大盘 1.25 > 加密 1.167 → 大盘先释放
    assert st.market_batches.get("us_equity") == 1
    assert "us_equity" in note


def test_conflict_tie_goes_to_equity():
    """平局时大盘优先（§6.4）。"""
    st = pf.PortfolioState()
    # 大盘 0.20/0.20 = 1.0；加密 0.30/0.30 = 1.0
    st, newly, note = pf.release_ammo(
        st, [_out("crypto", 0.30), _out("us_equity", 0.20)])
    assert st.market_batches.get("us_equity") == 1


def test_only_one_batch_released_per_day():
    """单日最多释放 1 批（避免一天打光）。"""
    st = pf.PortfolioState()
    st, newly, _ = pf.release_ammo(
        st, [_out("crypto", 0.80), _out("us_equity", 0.65)])
    assert newly == 1
    assert len(st.ammo_released) == 1


# ---------------------------------------------------------------- 极恐提前释放

def test_extreme_fear_releases_one_batch():
    st = pf.PortfolioState()
    st, n, note = pf.apply_extreme_fear(
        st, [_out("crypto", 0.0, extreme_fear=True)], "2026-01-05")
    assert n == 1
    assert st.last_extreme_fear_date == "2026-01-05"


def test_extreme_fear_respects_cooldown():
    st = pf.PortfolioState(last_extreme_fear_date="2026-01-05")
    st, n, _ = pf.apply_extreme_fear(
        st, [_out("crypto", 0.0, extreme_fear=True)], "2026-01-10")
    assert n == 0


def test_extreme_fear_noop_when_pool_exhausted():
    """池子满 3 批后，极恐也不得再释放。

    **v2.5 起填满池子需要两个市场**：单市场最多 2 批（第 12.11 条）。
    """
    st = pf.PortfolioState()
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.65)])
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.65)])
    st, _, _ = pf.release_ammo(st, [_out("crypto", 0.80)])
    assert len(st.ammo_released) == 3
    st, n, _ = pf.apply_extreme_fear(
        st, [_out("crypto", 0.0, extreme_fear=True)], "2026-01-05")
    assert n == 0


# ---------------------------------------------------------------- 组合仓位

def test_combine_sums_core_and_ammo():
    st = pf.PortfolioState(ammo_released=[0])
    target, note = pf.combine([_out("us_equity", 0.0, core=0.49),
                               _out("crypto", 0.0, core=0.21)], st)
    assert target == pytest.approx(0.49 + 0.21 + 0.20 / 3)


def test_combine_handles_none_core():
    """某市场无信号（warmup）时只计另一个市场。"""
    st = pf.PortfolioState()
    target, note = pf.combine([_out("us_equity", 0.0, core=None),
                               _out("crypto", 0.0, core=0.21)], st)
    assert target == pytest.approx(0.21)


def test_combine_none_when_all_markets_none():
    st = pf.PortfolioState()
    target, note = pf.combine([_out("us_equity", 0.0, core=None),
                               _out("crypto", 0.0, core=None)], st)
    assert target is None


def test_combine_clips_to_one():
    st = pf.PortfolioState(ammo_released=[0, 1, 2])
    target, _ = pf.combine([_out("us_equity", 0.0, core=0.49),
                            _out("crypto", 0.0, core=0.21)], st)
    assert target <= 1.0


# ---------------------------------------------------------------- 防抖动（收敛到本层）

def test_throttle_blocks_below_threshold():
    st = pf.PortfolioState()
    ok, reason = pf.throttle_ok(st, 0.50, 0.55, "2026-01-05")
    assert ok is False


def test_throttle_blocks_within_cooldown():
    st = pf.PortfolioState(last_rebalance_date="2026-01-05")
    ok, reason = pf.throttle_ok(st, 0.30, 0.60, "2026-01-07")
    assert ok is False


def test_throttle_allows_when_extreme():
    st = pf.PortfolioState(last_rebalance_date="2026-01-05")
    ok, reason = pf.throttle_ok(st, 0.30, 0.60, "2026-01-07", extreme=True)
    assert ok is True


def test_clip_adjustment_limits_single_move():
    assert pf.clip_adjustment(0.10, 0.90) == pytest.approx(0.40)
    assert pf.clip_adjustment(0.50, 0.55) == pytest.approx(0.55)


def test_state_is_deep_copied():
    st = pf.PortfolioState(market_batches={"us_equity": 1})
    snapshot = st.to_dict()
    pf.release_ammo(st, [_out("us_equity", 0.45)])
    assert st.to_dict() == snapshot
