# -*- coding: utf-8 -*-
"""守猪待兔「早清仓代价」分析的纯函数测试（Step B · C）。

设计：docs/superpowers/specs/2026-09-24-shoutu-greed-exit-cost-design.md
"""
import pandas as pd
import pytest

from fg_system import config
from fg_system import shoutu_analysis
from fg_system.signal import portfolio


def test_next_position_clears_small_sleeve_in_one_day():
    """单标的 sleeve ≈12% ⇒ 一天清完（12pp < MAX_SINGLE_ADJUST 30pp）。"""
    assert portfolio.next_position(0.12, 0.0) == pytest.approx(0.0)


def test_next_position_needs_two_days_above_cap():
    """45% 仓位 ⇒ 单次最多 30pp ⇒ 第一天到 15%，第二天到 0%（两天清完）。

    ⚠️ 计划原文用 36%（断言第二天到 0%），与
    `test_next_position_leaves_last_ten_pp` **直接矛盾**——同一输入
    `next_position(0.06, 0.0)` 不可能同时等于 0.0 和 0.06；且计划 Task 2 的
    `replay_exit_path(t, p0=0.36) == [0.06, 0.06, 0.06]` 也证明 6% 会**留在** 6%。
    故改为 45%：它才真正体现"单日限幅 30pp ⇒ 需两天"（15% 仍 ≥ 10pp 阈值）。
    """
    p1 = portfolio.next_position(0.45, 0.0)
    assert p1 == pytest.approx(0.15)
    assert portfolio.next_position(p1, 0.0) == pytest.approx(0.0)


def test_next_position_leaves_last_ten_pp():
    """|目标 − 现状| < REBALANCE_THRESHOLD ⇒ 不动作（最后 10pp 被留下）。"""
    assert portfolio.next_position(0.06, 0.0) == pytest.approx(0.06)


def test_next_position_acts_when_diff_equals_threshold():
    """⚠️ 是 `<` 不是 `≤`：|差| 恰好等于阈值时**要动作**（与 FgStrategy 一致）。"""
    thr = config.REBALANCE_THRESHOLD
    assert portfolio.next_position(thr, 0.0) == pytest.approx(0.0)


def test_next_position_nan_target_holds():
    """目标 NaN（warmup）⇒ 不动，不得当成空仓。"""
    assert portfolio.next_position(0.30, float("nan")) == pytest.approx(0.30)


def test_next_position_clamps_upper_bound_on_buy():
    """加仓方向 + 上钳位：0.55 → 目标 1.20 ⇒ 单次 +30pp 到 0.85（仍在 [0,1] 内）。"""
    assert portfolio.next_position(0.55, 1.20) == pytest.approx(0.85)


def test_next_position_clamps_at_one():
    """已满仓时再加仓 ⇒ 被钳在 1.0（上钳位分支）。"""
    assert portfolio.next_position(1.0, 1.20) == pytest.approx(1.0)


def _series(pairs):
    """`{"2024-01-01": 61, ...}` → 日期索引的 Series（升序）。"""
    s = pd.Series({pd.Timestamp(k): float(v) for k, v in pairs.items()})
    return s.sort_index()


def test_greed_episodes_single_day():
    s = _series({"2024-01-01": 10, "2024-01-02": 61, "2024-01-03": 10})
    ep = shoutu_analysis.greed_episodes(s)
    assert len(ep) == 1
    assert ep.iloc[0]["start"] == pd.Timestamp("2024-01-02")
    assert ep.iloc[0]["days"] == 1
    assert bool(ep.iloc[0]["closed"]) is True


def test_greed_episodes_contiguous_run():
    s = _series({"2024-01-01": 60, "2024-01-02": 61,
                 "2024-01-03": 70, "2024-01-04": 59})
    ep = shoutu_analysis.greed_episodes(s)
    assert len(ep) == 1
    assert ep.iloc[0]["days"] == 3          # 60 恰好等于阈值 ⇒ 算在内
    assert ep.iloc[0]["peak"] == 70.0


def test_greed_episodes_open_at_tail_is_marked_unclosed():
    """数据末尾仍在贪婪档 ⇒ closed=False（不进"全程"统计）。"""
    s = _series({"2024-01-01": 10, "2024-01-02": 61, "2024-01-03": 70})
    ep = shoutu_analysis.greed_episodes(s)
    assert bool(ep.iloc[0]["closed"]) is False


def test_greed_episodes_none():
    s = _series({"2024-01-01": 10, "2024-01-02": 20})
    ep = shoutu_analysis.greed_episodes(s)
    assert ep.empty
    # 列名与列序必须完整 —— 下游 concat 依赖它
    assert list(ep.columns) == ["start", "end", "days", "peak", "closed"]


def test_greed_episodes_empty_closed_column_is_bool():
    """空表的 closed 列必须是 bool dtype（否则下游 .sum()/.any() 语义不同）。"""
    ep = shoutu_analysis.greed_episodes(pd.Series(dtype=float))
    assert ep.empty
    assert ep["closed"].dtype == bool


def test_greed_episodes_two_separate_runs():
    s = _series({"2024-01-01": 61, "2024-01-02": 10, "2024-01-03": 62})
    ep = shoutu_analysis.greed_episodes(s)
    assert len(ep) == 2
    # 第一段：只有一天，且后面还有数据 ⇒ 已结束
    assert ep.iloc[0]["start"] == pd.Timestamp("2024-01-01")
    assert ep.iloc[0]["end"] == pd.Timestamp("2024-01-01")
    assert bool(ep.iloc[0]["closed"]) is True
    # 第二段：延续到数据末尾 ⇒ **未完成**
    assert ep.iloc[1]["start"] == pd.Timestamp("2024-01-03")
    assert ep.iloc[1]["end"] == pd.Timestamp("2024-01-03")
    assert bool(ep.iloc[1]["closed"]) is False


def test_greed_episodes_run_starts_at_first_day():
    """段起于 index-0 ⇒ 起点边界（循环的 i=0 分支）必须正确。"""
    s = _series({"2024-01-01": 65, "2024-01-02": 70, "2024-01-03": 10})
    ep = shoutu_analysis.greed_episodes(s)
    assert len(ep) == 1
    assert ep.iloc[0]["start"] == pd.Timestamp("2024-01-01")
    assert ep.iloc[0]["days"] == 2
    assert bool(ep.iloc[0]["closed"]) is True


def test_greed_episodes_run_ends_at_second_to_last_day():
    """段终止于末尾**前一格** ⇒ closed 必须是 True（与"终止于末尾"仅差一格）。"""
    s = _series({"2024-01-01": 10, "2024-01-02": 61,
                 "2024-01-03": 70, "2024-01-04": 10})
    ep = shoutu_analysis.greed_episodes(s)
    assert ep.iloc[0]["end"] == pd.Timestamp("2024-01-03")
    assert bool(ep.iloc[0]["closed"]) is True


def test_replay_exit_path_small_sleeve_one_day():
    """12% 仓位，目标 0 ⇒ 一天到 0。"""
    t = pd.Series([0.0, 0.0], index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    path = shoutu_analysis.replay_exit_path(t, p0=0.12)
    assert list(path) == pytest.approx([0.0, 0.0])


def test_replay_exit_path_leaves_last_ten_pp():
    """36% 仓位 ⇒ 第一天 6%，之后 |0−6%| < 10pp ⇒ 停在 6%（不归零）。"""
    t = pd.Series([0.0, 0.0, 0.0], index=pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-04"]))
    path = shoutu_analysis.replay_exit_path(t, p0=0.36)
    assert list(path) == pytest.approx([0.06, 0.06, 0.06])


def test_replay_exit_path_rebuys_when_target_returns():
    """⚠️ 关键：值回落后**重新买回** —— 不得冻结在 0（冻结会高估卖飞）。"""
    t = pd.Series([0.0, 0.12, 0.12], index=pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-04"]))
    path = shoutu_analysis.replay_exit_path(t, p0=0.12)
    assert list(path) == pytest.approx([0.0, 0.12, 0.12])


def test_price_divergence_detects_mismatch():
    a = pd.Series([10.0, 11.0], index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    b = pd.Series([10.0, 12.0], index=a.index)
    d = shoutu_analysis.price_divergence(a, b)
    assert d["n"] == 2
    assert d["max_rel"] > 0.08


def test_price_divergence_identical_is_zero():
    a = pd.Series([10.0, 11.0], index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    d = shoutu_analysis.price_divergence(a, a.copy())
    assert d["max_rel"] == pytest.approx(0.0)


def test_price_divergence_reports_return_consistency():
    """⚠️ 关键：**恒定级差**（复权口径差的形态）不影响日收益。"""
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    a = pd.Series([100.0, 110.0, 99.0, 108.9], index=idx)
    d = shoutu_analysis.price_divergence(a, a * 1.02)     # 恒定 2% 水平差
    # ⚠️ 分母取 `max(|a|,|b|)` ⇒ 2/102 而非 2/100（计划原稿写 0.02 是手算按 2/100，
    #    与本模块公式不符）。这里按**公式**取值。
    assert d["max_rel"] == pytest.approx(2.0 / 102.0)
    assert d["corr_dret"] == pytest.approx(1.0)
    assert d["max_abs_dret"] == pytest.approx(0.0, abs=1e-12)


def test_price_consistency_ok_ignores_level_gap():
    """⚠️ 关键：2% 的**级差**（复权口径差）不得判失败 —— 分析只用日收益。"""
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    a = pd.Series([100.0, 110.0, 99.0, 108.9], index=idx)
    assert shoutu_analysis.price_consistency_ok(
        shoutu_analysis.price_divergence(a, a * 1.02)) is True


def test_price_consistency_ok_thresholds():
    """corr 或单日收益差任一越界 ⇒ 判失败。"""
    good = {"n": 100, "corr_dret": 0.99995, "max_abs_dret": 0.0038}
    assert shoutu_analysis.price_consistency_ok(good) is True
    assert shoutu_analysis.price_consistency_ok(
        dict(good, corr_dret=0.99)) is False
    assert shoutu_analysis.price_consistency_ok(
        dict(good, max_abs_dret=0.05)) is False


def test_price_consistency_ok_insufficient_sample_is_failure():
    """⚠️ 样本不足 / NaN ⇒ **判失败**（"没查过"不等于"查过通过"）。"""
    assert shoutu_analysis.price_consistency_ok(
        {"n": 0, "corr_dret": float("nan"), "max_abs_dret": float("nan")}) is False
    assert shoutu_analysis.price_consistency_ok(
        shoutu_analysis.price_divergence(pd.Series(dtype=float),
                                        pd.Series(dtype=float))) is False


# ---------------------------------------------------------------- A2-E Task 2：触发频率 / 换手纯函数
def test_extreme_trigger_counts_boundaries_are_inclusive():
    """⚠️ 边界必须 `>=`（贪婪）/ `<=`（恐惧）—— 与 `market_signal` 的判定同语义。

    用哨兵法验证：恰好等于阈值算触发，差 1 点不算。
    """
    s = _series({"2024-01-01": 85.0, "2024-01-02": 84.999, "2024-01-03": 10.0,
                 "2024-01-04": 10.001})
    got = shoutu_analysis.extreme_trigger_counts(
        s, greed_trigger=85.0, fear_trigger=10.0)
    assert got == {"greed_days": 1, "fear_days": 1}


def test_extreme_trigger_counts_skips_nan():
    """NaN（warmup / 无信号）**不计入** —— 不得把「无信号」当「触发」。"""
    s = _series({"2024-01-01": float("nan"), "2024-01-02": 90.0,
                 "2024-01-03": float("nan"), "2024-01-04": 5.0})
    got = shoutu_analysis.extreme_trigger_counts(
        s, greed_trigger=85.0, fear_trigger=10.0)
    assert got == {"greed_days": 1, "fear_days": 1}


def test_extreme_trigger_counts_empty_series():
    got = shoutu_analysis.extreme_trigger_counts(
        pd.Series(dtype=float), greed_trigger=85.0, fear_trigger=10.0)
    assert got == {"greed_days": 0, "fear_days": 0}


def test_trigger_date_distribution_lists_dates_and_months():
    """返回触发日列表 + 月度分布（哪几个月集中）—— 供「少数几天主导」核对。"""
    s = _series({"2024-07-01": 90.0, "2024-07-02": 5.0, "2024-07-15": 88.0,
                 "2025-01-10": 9.0})
    got = shoutu_analysis.trigger_date_distribution(
        s, greed_trigger=85.0, fear_trigger=10.0)
    assert got["greed"] == [pd.Timestamp("2024-07-01"), pd.Timestamp("2024-07-15")]
    assert got["fear"] == [pd.Timestamp("2024-07-02"), pd.Timestamp("2025-01-10")]
    assert got["greed_months"] == {"2024-07": 2}
    assert got["fear_months"] == {"2024-07": 1, "2025-01": 1}


def test_trigger_date_distribution_empty():
    got = shoutu_analysis.trigger_date_distribution(
        pd.Series(dtype=float), greed_trigger=85.0, fear_trigger=10.0)
    assert got["greed"] == [] and got["fear"] == []
    assert got["greed_months"] == {} and got["fear_months"] == {}


# ---------------------------------------------------------------- D5：fng 的 price 属哪个复权口径
def test_fng_price_caliber_picks_the_matching_reference():
    """⚠️ **D5 判据**：fng 的 `price` 与**哪个参照源**同口径。

    构造：`fng` = `hist` 的等比缩放（**恒定 2% 水平差** —— 正是复权口径差的形态）
    ⇒ 与 `hist` 的**日收益完全一致**；而另一条序列的日收益不同 ⇒ 判为「同 hist」。

    ⚠️ 判据只用**日收益**（`corr_dret` / `max_abs_dret`）—— 级差是复权口径差，
    不是错误（同 `price_consistency_ok` 的纪律）。
    """
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    hist = pd.Series([100.0, 110.0, 99.0, 108.9], index=idx)
    fng = hist * 1.02                                          # 恒定级差
    px = pd.Series([100.0, 105.0, 102.0, 104.0], index=idx)    # 另一条口径不同
    out = shoutu_analysis.fng_price_caliber(fng, hist, px)
    assert out["ok_hist"] is True
    assert out["ok_prices"] is False
    assert "shoutu_history" in out["verdict"]


def test_fng_price_caliber_reports_no_discrimination_on_thin_sample():
    """⚠️ **样本不足 ⇒ 必须报「无分辨力」，不得偏袒任何一方**。

    实测现状（2026-09-28）：fng 的 `price` 从 **2026-09-25** 起才有值，与参照源
    重叠仅 **1 天** ⇒ 日收益点 0 个 ⇒ `corr_dret = NaN` ⇒ **判据不可计算**。
    「没查过」不等于「查过通过」（同 `price_consistency_ok` 对 NaN 的纪律）。
    分辨力需要**跨越至少一个除息日**的样本。
    """
    idx = pd.to_datetime(["2026-09-25"])
    fng = pd.Series([100.0], index=idx)
    ref = pd.Series([100.0], index=idx)
    out = shoutu_analysis.fng_price_caliber(fng, ref, ref)
    assert out["ok_hist"] is False and out["ok_prices"] is False
    assert "无分辨力" in out["verdict"]


def test_fng_price_caliber_picks_prices_when_that_side_matches():
    """对称性：fng 与 `prices.csv` 同口径时，判据必须**翻到另一边**。

    （防「写死偏向 hist」的实现 —— 只测一个方向的话，返回常量的假实现也能过。）
    """
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    px = pd.Series([100.0, 105.0, 102.0, 104.0], index=idx)
    fng = px * 0.98
    hist = pd.Series([100.0, 110.0, 99.0, 108.9], index=idx)
    out = shoutu_analysis.fng_price_caliber(fng, hist, px)
    assert out["ok_prices"] is True
    assert out["ok_hist"] is False
    assert "prices" in out["verdict"]


# ---------------------------------------------------------------- 除息日剔除（2026-09-28 用户裁决 (a)）
def test_ex_dividend_dates_detects_a_ratio_step():
    """⚠️ 除息日 = `hist/ref` 比值**阶跃**的那一天。

    构造：比值前 2 天恒为 1.0，第 3 天跳到 0.98（−2%）—— 正是实测形态
    （`shoutu_history/prices` 在 `09-23 → 09-24` 由 `0.99807` 跳到 `0.98111`）。

    为什么用比值而不是别的信号：`hist.price` 是**前复权**（分红被抹掉）、
    `ref.close` **未复权** ⇒ 两者比值 = **累计分红因子**，在两次除息之间**恒定**，
    只在除息日当天阶跃。
    """
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    ref = pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)
    hist = pd.Series([100.0, 100.0, 98.0, 98.0], index=idx)      # 01-03 阶跃 −2%
    assert list(shoutu_analysis.ex_dividend_dates(hist, ref)) == [idx[2]]


def test_ex_dividend_dates_empty_when_ratio_is_flat():
    """比值恒定（**无除息**）⇒ 必须返回空 —— 不得把舍入噪声当成除息日。"""
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    ref = pd.Series([100.0, 110.0, 99.0], index=idx)
    hist = ref * 1.02                                            # 恒定级差
    assert len(shoutu_analysis.ex_dividend_dates(hist, ref)) == 0


def test_price_divergence_excludes_the_ex_div_day_return_only():
    """⚠️ **剔除方式的关键**：只能删**那一天的收益**，不能让次日收益跨过缺口。

    构造：`ref` 在 01-03 因除息跌 2%，`hist`（前复权）不跌 ⇒ 01-03 的日收益差 2%。
    剔除 01-03 后，01-04 的收益必须仍以 **01-03 的价格**为基准（两边都是）。

    ⇒ 若实现改成「**删价格行**」，01-04 的收益会跨过缺口（`102/100` vs `99.96/100`）
    又出现一次 **2.04%** 的假差异 —— 本用例正是为了区分这两种实现而写的。
    """
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    hist = pd.Series([100.0, 100.0, 100.0, 102.0], index=idx)    # 不跌
    ref = pd.Series([100.0, 100.0, 98.0, 99.96], index=idx)      # 除息 −2%，之后 +2%
    ex = shoutu_analysis.ex_dividend_dates(hist, ref)
    assert list(ex) == [idx[2]], "01-03 必须被识别为除息日"
    d = shoutu_analysis.price_divergence(hist, ref, exclude_dates=ex)
    assert d["excluded"] == 1
    assert d["max_abs_dret"] == pytest.approx(0.0, abs=1e-12)
    assert d["corr_dret"] == pytest.approx(1.0)


def test_price_divergence_default_keeps_ex_div_days():
    """等价性：不传 `exclude_dates` 时行为**逐位不变**（既有调用方零影响）。

    ⚠️ 样本刻意**非退化**（收益有波动）—— 若三条价格里有两条相等，收益序列方差为 0，
    `corr` 会算出 NaN 并触发 `RuntimeWarning: invalid value encountered in divide`
    （测试输出必须干净，同 TDD 检查表）。
    """
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    a = pd.Series([100.0, 101.0, 102.0], index=idx)
    b = pd.Series([100.0, 101.0, 100.0], index=idx)
    d1 = shoutu_analysis.price_divergence(a, b)
    d2 = shoutu_analysis.price_divergence(a, b, exclude_dates=None)
    for k in ("n", "max_rel", "mean_rel", "corr_dret",
              "max_abs_dret", "mean_abs_dret"):
        assert d1[k] == pytest.approx(d2[k]), k
    assert d1["excluded"] == 0 and d2["excluded"] == 0
    assert d1["max_abs_dret"] > 0.0, "样本必须非退化"
