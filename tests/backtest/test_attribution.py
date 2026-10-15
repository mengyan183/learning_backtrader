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

def test_without_trend_returns_target_unchanged():
    """关闭趋势过滤 = 原样返回。

    裁决 B：v1 的 `target_position = core_position + ammo`（**无 trend 乘法**），
    趋势折扣从未乘进 v1 target。因此「关闭趋势过滤」的对照就是**不做任何改动**，
    blocked 行**不得**再做 ÷TREND_FILTER_FACTOR（那会让仓位翻倍，实测 0.5→1.0）。
    """
    f = _features([0.49, 0.245, 0.245], [False, True, True])
    out = attribution.without_trend(f)
    pd.testing.assert_series_equal(out["target_position"], f["target_position"])


def test_without_trend_leaves_unblocked_rows_unchanged():
    f = _features([0.49, 0.30], [False, False])
    out = attribution.without_trend(f)
    assert out["target_position"].iloc[1] == pytest.approx(0.30)


def test_without_trend_does_not_rescale_blocked_rows():
    """blocked 行原样保留，不做任何放大 / 裁剪。"""
    f = _features([0.90, 0.245], [True, True])
    out = attribution.without_trend(f)
    assert out["target_position"].iloc[0] == pytest.approx(0.90)
    assert out["target_position"].iloc[1] == pytest.approx(0.245)


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


def test_contribution_zero_delta_when_v1_target_has_no_trend_discount():
    """裁决 B：v1 的 target 未含趋势折扣 ⇒ 对照=原样 ⇒ 两条路径收益相同、delta=0。

    blocked 行**不做 ÷0.5**（旧实现会在此把 0.5 放大回 1.0，凭空造出 delta）。
    """
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.245, 0.245],
        "trend_blocked": [False, False, True, True],
        "fg_index": [10.0] * 4,
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 90.0, 80.0], index=idx)
    table = attribution.contribution_table(f, prices)
    assert table["return_delta"].iloc[0] == pytest.approx(0.0, abs=1e-12)


def test_contribution_paths_identical_without_trend():
    """裁决 B 的核心事实：v1 数据上「带过滤」与「不带过滤」是**同一条序列**。

    因此无论价格怎么走（此处含一段反弹），delta 恒为 0。旧实现会在此把对照
    的 blocked 行 0.245 ÷0.5 = 0.49 放大，凭空吃下更多反弹 ⇒ delta 为负。
    """
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "target_position": [0.49, 0.245, 0.245, 0.245],
        "trend_blocked": [False, True, True, True],
        "fg_index": [10.0] * 4,
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 120.0, 140.0], index=idx)
    table = attribution.contribution_table(f, prices)
    assert table["with_trend_return"].iloc[0] == \
        pytest.approx(table["without_trend_return"].iloc[0], abs=1e-12)
    assert table["return_delta"].iloc[0] == pytest.approx(0.0, abs=1e-12)


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
    # 裁决 B：v1 的 target 未含趋势折扣 ⇒ 对照=原样 ⇒ 两条路径仓位逐行相同
    # ⇒ 回撤相同 ⇒ mdd_delta == 0（旧的 >0 断言基于「blocked 行已打折」的错误前提）。
    assert t["mdd_delta"].iloc[0] == pytest.approx(0.0, abs=1e-12)


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
    """delta 达到阈值且确实触发过滤时，verdict 应判为有效。

    裁决 B 后：v1 的 target 未含趋势折扣 ⇒ `contribution_table` 的 delta 恒为 0，
    已无法从 features 造出大 delta。故此处**直接构造贡献度表**，只测 `verdict()`
    自身的阈值逻辑（与 without_trend 无关）。
    """
    table = pd.DataFrame([{
        "with_trend_return": 0.10, "without_trend_return": -0.05,
        "return_delta": 0.15, "blocked_days": 3, "blocked_ratio": 0.5,
    }])
    assert attribution.verdict(table)["effective"] is True


def test_verdict_negative_delta_reports_negative_and_no_fallback_advice():
    """负贡献（拖累收益）时：effective=False、reason 如实报负，且**不得**给出
    「回到选项 A / 降低核心仓上限」的建议（MT-21：收益维度为负 ≠ 应回退核心仓上限，
    是否保留须结合 max_drawdown_table 人工裁决）。"""
    table = pd.DataFrame([{
        "with_trend_return": 0.67, "without_trend_return": 0.73,
        "return_delta": -0.059, "blocked_days": 413, "blocked_ratio": 0.16,
    }])
    v = attribution.verdict(table)
    assert v["effective"] is False
    reason = v["reason"]
    assert "负" in reason
    assert "选项 A" not in reason
    assert "降低核心仓上限" not in reason


def test_verdict_zero_delta_has_no_fallback_advice():
    """delta=0（收益维度无改善）时：effective=False，reason 也**不得**含回退建议。"""
    table = pd.DataFrame([{
        "with_trend_return": 0.50, "without_trend_return": 0.50,
        "return_delta": 0.0, "blocked_days": 3, "blocked_ratio": 0.2,
    }])
    v = attribution.verdict(table)
    assert v["effective"] is False
    reason = v["reason"]
    assert "选项 A" not in reason
    assert "降低核心仓上限" not in reason


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


# ---------------------------------------------------------------- 接线后对照（P-2026-10-12-trend-wiring）

def test_without_trend_restores_wired_target():
    """接线（选项 ii）后：without_trend 还原未打折版 core+ammo（含 shift 对齐）。

    接线 target[T] = core[T-1]×trend[T-1] + ammo[T-1]（弹药豁免）；
    关闭趋势过滤 ⇒ target[T] = core[T-1] + ammo[T-1]。
    """
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "core_position": [0.3, 0.3, 0.3, 0.3],
        "ammo_position": [0.1, 0.1, 0.0, 0.0],
        "trend": [1.0, 0.5, 0.5, 1.0],
        "trend_blocked": [False, True, True, False],
        # 接线版 target：T1=0.3×1.0+0.1=0.4；T2=0.3×0.5+0.1=0.25；T3=0.3×0.5+0.0=0.15
        "target_position": [float("nan"), 0.4, 0.25, 0.15],
    }, index=idx)
    out = attribution.without_trend(f)
    # 还原：T1=0.3+0.1=0.4；T2=0.3+0.1=0.4；T3=0.3+0.0=0.3；T0=NaN
    assert out["target_position"].iloc[0] != out["target_position"].iloc[0]  # NaN
    assert out["target_position"].iloc[1] == pytest.approx(0.4)
    assert out["target_position"].iloc[2] == pytest.approx(0.4)
    assert out["target_position"].iloc[3] == pytest.approx(0.3)


def test_without_trend_restores_missing_column_noop_still_holds():
    """缺 core/ammo 列（旧守卫场景）仍原样返回，不崩溃。"""
    f = _features([0.49, 0.245], [True, True])
    out = attribution.without_trend(f)
    pd.testing.assert_series_equal(out["target_position"], f["target_position"])
