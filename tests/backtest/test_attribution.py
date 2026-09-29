# -*- coding: utf-8 -*-
"""趋势过滤贡献度归因测试。"""
import pandas as pd
import pytest

from fg_system.backtest import attribution


def _features(targets, trend_blocked, index=100.0):
    idx = pd.bdate_range("2024-01-01", periods=len(targets))
    return pd.DataFrame({
        "target_position": targets,
        "trend_blocked": trend_blocked,
        "fg_index": [index] * len(targets),
    }, index=idx)


# ---------------------------------------------------------------- without_trend

def test_without_trend_removes_discount():
    """关闭趋势过滤 = 把 trend_blocked 处的仓位还原为未打折值。"""
    f = _features([0.49, 0.245, 0.245], [False, True, True])
    out = attribution.without_trend(f)
    assert out["target_position"].iloc[0] == pytest.approx(0.49)
    assert out["target_position"].iloc[1] == pytest.approx(0.49)


def test_without_trend_leaves_unblocked_rows_unchanged():
    f = _features([0.49, 0.30], [False, False])
    out = attribution.without_trend(f)
    assert out["target_position"].iloc[1] == pytest.approx(0.30)


def test_without_trend_clips_to_one():
    """还原后不得超过 100%。"""
    f = _features([0.90], [True])
    out = attribution.without_trend(f)
    assert out["target_position"].iloc[0] <= 1.0


def test_without_trend_missing_column_is_noop():
    """没有 trend_blocked 列时原样返回，不崩溃。"""
    idx = pd.bdate_range("2024-01-01", periods=3)
    f = pd.DataFrame({"target_position": [0.4, 0.4, 0.4]}, index=idx)
    out = attribution.without_trend(f)
    pd.testing.assert_series_equal(out["target_position"], f["target_position"])


# ---------------------------------------------------------------- contribution_table

def test_contribution_table_columns():
    f = _features([0.49, 0.245, 0.49, 0.245], [False, True, False, True])
    prices = pd.Series([100.0, 102.0, 104.0, 106.0], index=f.index)
    table = attribution.contribution_table(f, prices)
    for col in ["with_trend_return", "without_trend_return",
                "return_delta", "blocked_days", "blocked_ratio"]:
        assert col in table.columns


def test_contribution_reports_blocked_days():
    f = _features([0.49] * 4, [False, True, True, False])
    prices = pd.Series([100.0] * 4, index=f.index)
    table = attribution.contribution_table(f, prices)
    assert table["blocked_days"].iloc[0] == 2


def test_contribution_zero_delta_when_never_blocked():
    """从未触发趋势过滤时，两条路径收益必须完全相同。"""
    f = _features([0.49, 0.49, 0.49], [False, False, False])
    prices = pd.Series([100.0, 105.0, 110.0], index=f.index)
    table = attribution.contribution_table(f, prices)
    assert table["return_delta"].iloc[0] == pytest.approx(0.0, abs=1e-9)


def test_contribution_positive_delta_when_trend_avoids_loss():
    """趋势过滤避开下跌时，带过滤的收益应高于不带过滤。"""
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.245, 0.245],
        "trend_blocked": [False, False, True, True],
        "fg_index": [10.0] * 4,
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 90.0, 80.0], index=idx)
    table = attribution.contribution_table(f, prices)
    assert table["return_delta"].iloc[0] > 0


def test_contribution_negative_delta_when_trend_misses_rebound():
    """趋势过滤错过反弹时，带过滤的收益应低于不带过滤（这是它的代价）。"""
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "target_position": [0.49, 0.245, 0.245, 0.245],
        "trend_blocked": [False, True, True, True],
        "fg_index": [10.0] * 4,
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 120.0, 140.0], index=idx)
    table = attribution.contribution_table(f, prices)
    assert table["return_delta"].iloc[0] < 0


# ---------------------------------------------------------------- max_drawdown_table

def test_mdd_table_columns_and_sign():
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.245, 0.245],
        "trend_blocked": [False, False, True, True],
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 80.0, 60.0], index=idx)
    t = attribution.max_drawdown_table(f, prices)
    assert "with_trend_mdd" in t.columns
    # 趋势过滤降仓，回撤应更小 → mdd_delta > 0
    assert t["mdd_delta"].iloc[0] > 0


# ---------------------------------------------------------------- verdict

def test_verdict_flags_ineffective_when_delta_small():
    """贡献度接近零时必须给出「无效」判定（§12 风险 7）。"""
    idx = pd.bdate_range("2024-01-01", periods=3)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.49],
        "trend_blocked": [False, False, False],
        "fg_index": [50.0] * 3,
    }, index=idx)
    prices = pd.Series([100.0, 101.0, 102.0], index=idx)
    table = attribution.contribution_table(f, prices)
    v = attribution.verdict(table)
    assert v["effective"] is False
    assert "无法评估" in v["reason"]


def test_verdict_flags_effective_when_delta_large():
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.245, 0.245],
        "trend_blocked": [False, False, True, True],
        "fg_index": [10.0] * 4,
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 80.0, 60.0], index=idx)
    table = attribution.contribution_table(f, prices)
    assert attribution.verdict(table)["effective"] is True


def test_verdict_recommends_fallback_when_ineffective():
    """无效时必须给出「回到选项 A」的建议，而不是继续调趋势参数。"""
    idx = pd.bdate_range("2024-01-01", periods=3)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.49],
        "trend_blocked": [True, True, True],
        "fg_index": [50.0] * 3,
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 100.0], index=idx)
    table = attribution.contribution_table(f, prices)
    v = attribution.verdict(table)
    if not v["effective"]:
        assert "选项 A" in v["reason"]


# ---------------------------------------------------------------- full_report

def test_full_report_has_both_tables():
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.245, 0.245],
        "trend_blocked": [False, False, True, True],
        "fg_index": [10.0] * 4,
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 80.0, 60.0], index=idx)
    out = attribution.full_report(f, prices)
    for col in ["return_delta", "mdd_delta", "effective", "reason"]:
        assert col in out.columns
