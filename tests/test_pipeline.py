# -*- coding: utf-8 -*-
"""管道编排测试（§3.3、§10）。"""
import re

import numpy as np
import pandas as pd
import pytest

from fg_system import index as index_mod
from fg_system import pipeline


@pytest.fixture(scope="module")
def features():
    """全量管道结果（module 级缓存，避免每个用例重复跑全链路）。"""
    return pipeline.run(write=False)


def test_features_columns_present(features):
    for col in ["fg_index", "zone", "core_position", "ammo_position",
                "target_position", "drawdown", "circuit_breaker",
                "vix", "term", "price", "breadth"]:
        assert col in features.columns


def test_features_sorted_ascending(features):
    assert features.index.is_monotonic_increasing


def test_index_is_valid_for_a_meaningful_span(features):
    """warmup(756 交易日) 之后应有足够多的有效指数。"""
    assert features["fg_index"].notna().sum() > 800


def test_fg_index_within_range(features):
    valid = features["fg_index"].dropna()
    assert valid.between(0, 100).all()


def test_target_position_never_exceeds_one(features):
    valid = features["target_position"].dropna()
    assert not valid.empty
    assert valid.between(0.0, 1.0).all()


def test_ammo_position_is_monotonic_non_decreasing(features):
    """状态化规则必须按时间顺序推进（§10.5）：弹药释放只增不减。"""
    ammo = features["ammo_position"].dropna()
    assert ammo.is_monotonic_increasing


def test_target_position_is_shifted_by_one_day(features):
    """§10.3：target_position 必须整体后移一天（T 日开盘执行 T-1 信号）。"""
    recomputed = (features["core_position"].fillna(0)
                  + features["ammo_position"].fillna(0)).shift(1)
    both = pd.concat([recomputed.rename("a"), features["target_position"].rename("b")], axis=1).dropna()
    assert not both.empty
    # 存在熔断日时 target 会被覆写，故只要求绝大多数一致
    same = (both["a"] - both["b"]).abs() < 1e-9
    assert same.mean() > 0.9


# ---------------------------------------------------------------- 前视偏差校验（§10.6）
def test_no_lookahead_bias_by_shift_test(features):
    """平移测试：输入整体后移一天 → 输出也必须整体后移一天。

    若输出「不随输入后移而改变」，说明第 T 天的计算用到了 T 之后的数据。
    """
    shifted = pipeline.run(write=False, shift_inputs=1)
    overlap = features.index.intersection(shifted.index)
    assert len(overlap) > 100

    expected = features["fg_index"].shift(1).loc[overlap]
    actual = shifted.loc[overlap, "fg_index"]
    diff = (expected - actual).abs().dropna()
    assert not diff.empty
    assert diff.max() < 1e-9


def test_no_lookahead_by_truncation(features):
    """截断测试：只喂到某日为止的数据，该日的 fg_index 必须与全量一致。

    这是对「第 T 天只用 ≤T 数据」最直接的验证。
    """
    valid = features["fg_index"].dropna()
    cutoff = valid.index[len(valid) // 2]

    wide_trunc = pipeline.load_wide().loc[:cutoff]
    fg_trunc = index_mod.combine(index_mod.factor_scores(wide_trunc))

    assert fg_trunc.loc[cutoff] == pytest.approx(features.loc[cutoff, "fg_index"])


# ---------------------------------------------------------------- 信号日 / 执行日（第 12.18 条）
def test_executable_snapshot_separates_signal_and_exec_dates(features):
    """`target_position` 被 shift(1)，所以「执行日」必须晚于「信号日」。"""
    sig, ex, row, target = pipeline.executable_snapshot(features)
    assert ex > sig
    assert target == pytest.approx(features.loc[ex, "target_position"]), \
        "目标值必须取自**执行日**那一行"


def test_executable_snapshot_row_is_self_consistent(features):
    """**核心不变量**：信号行的「核心仓 + 弹药仓」必须等于目标值。

    真实缺陷（两层错位）：分项未 shift 而目标 shift 了，用同一行打印会差 6.75pp；
    只把分项挪到前一行仍会差一天——目标值必须另取自执行日。
    """
    _, _, row, target = pipeline.executable_snapshot(features)
    assert (row["core_position"] or 0) + (row["ammo_position"] or 0) == \
        pytest.approx(target)


def test_pending_signal_is_one_day_ahead_of_executable(features):
    """**实盘口径 vs 回测口径**：待执行的信号日必须比已执行的信号日晚一天。

    --- 为什么删掉了「两个口径的目标必须不同」 ---
    那条断言**不是不变量**：组合目标连续两天相同是完全正常的
    （`REBALANCE_THRESHOLD` 10pp 的防抖动会让目标保持不动）。当初能过，
    只是因为当时的数据恰好凑巧不同——它是用真实数据写的一条**代理断言**，
    一旦数据延长（09-24/09-25 的 core+ammo 恰好都是 0.425）就会假失败。
    真正要守的「`shift(1)` 没被绕过」改由下面的**构造**测试承担：
    test_pending_signal_differs_from_executable_when_target_changes。

    留下的是恒成立、与数据无关的不变量：
      1. 待执行的信号日必须晚于已执行的信号日；
      2. 待执行目标 == 最新一行**未 shift** 的 core + ammo。
    """
    p_date, p_row, p_target = pipeline.pending_signal(features)
    s_date, _, _, s_target = pipeline.executable_snapshot(features)
    assert p_date > s_date, "待执行的信号日必须晚于已执行的信号日"
    assert p_target == pytest.approx(
        (p_row["core_position"] or 0) + (p_row["ammo_position"] or 0)), \
        "待执行目标 = 最新一行未 shift 的 core + ammo"


def test_pending_signal_differs_from_executable_when_target_changes():
    """**构造式 shift 守卫**：目标在最后两天发生变化时，两个口径必须给出**不同**值。

    用合成 features 把 `shift(1)` 的语义钉死——不依赖真实数据：

      - `executable_snapshot`（回测口径）取 `target_position.shift(1)`，即**前一行的
        目标**（T 日开盘执行 T-1 收盘信号，§10.3）；
      - `pending_signal`（实盘口径）取**最后一行未 shift** 的 `core + ammo`。

    这里把目标从 0.2（倒数第二行）跳到 0.5（最后一行），于是：

      - 回测口径 = 倒数第二行的 `target_position` = 0.2
      - 实盘口径 = 最后一行 `core + ammo`       = 0.5

    **若这条失败 ⇒ `shift(1)` 被绕过或被重复应用 ⇒ `status` 会报出已经过去的目标**
    （09-22 只看到 09-21 的目标，漏掉当天该做的调仓）。

    分工说明（两条互补的守卫，缺一不可）：
      - **本条**：钉死两个函数**对同一 frame 的读取语义**——喂一个「未 shift」或
        「shift 两次」的 frame，两个口径就会给出相同 / 错误的目标。
      - **test_target_position_is_shifted_by_one_day**（真实数据）：钉死
        `pipeline.run` 确实对整列做了 `.shift(1)`；把该 shift 去掉会让它失败。
    """
    idx = pd.date_range("2026-01-01", periods=4, freq="D")
    out = pd.DataFrame({
        "core_position": [0.20, 0.20, 0.20, 0.50],
        "ammo_position": [0.00, 0.00, 0.00, 0.00],
        # 管道写盘前整体 shift(1)：T 日开盘执行 T-1 收盘信号
        "target_position": [np.nan, 0.20, 0.20, 0.20],
    }, index=idx)

    p_date, p_row, p_target = pipeline.pending_signal(out)
    s_date, exec_date, _, s_target = pipeline.executable_snapshot(out)

    assert p_date == idx[-1] and s_date == idx[-2]
    assert p_date > s_date
    assert s_target == pytest.approx(0.20), "回测口径取执行日那一行的 target（=前一行信号）"
    assert p_target == pytest.approx(0.50), "实盘口径取最后一行未 shift 的 core + ammo"
    assert p_target != pytest.approx(s_target), (
        "两个口径必须给出不同的目标：相等意味着 shift(1) 被绕过或被重复应用，"
        "status 会报出已经过去的目标")


def test_pending_signal_returns_none_when_all_nan():
    out = pd.DataFrame({"core_position": [np.nan]},
                       index=pd.date_range("2020-01-01", periods=1))
    assert pipeline.pending_signal(out) is None


def test_executable_snapshot_returns_none_when_no_target():
    out = pd.DataFrame({"target_position": [np.nan, np.nan]},
                       index=pd.date_range("2020-01-01", periods=2))
    assert pipeline.executable_snapshot(out) is None


def test_executable_snapshot_returns_none_at_first_row():
    """只有一行时没有「前一日」可用，必须返回 None 而不是抛异常。"""
    out = pd.DataFrame({"target_position": [0.5]},
                       index=pd.date_range("2020-01-01", periods=1))
    assert pipeline.executable_snapshot(out) is None


# ---------------------------------------------------------------- 指令卡（§13.1）
def test_instruction_card_contains_key_fields(features):
    card = pipeline.instruction_card(features, current_position=0.50)
    for token in ["信号日", "执行日", "fg_index", "核心仓", "弹药仓",
                  "目标总仓位", "熔断状态", "指令"]:
        assert token in card


def test_instruction_card_components_sum_to_target(features):
    """**回归**：卡片里的「核心仓 + 弹药仓」必须等于「目标总仓位」。"""
    card = pipeline.instruction_card(features, current_position=0.50)
    core = float(re.search(r"核心仓：([\d.]+)%", card).group(1))
    ammo = float(re.search(r"弹药仓：([\d.]+)%", card).group(1))
    target = float(re.search(r"目标总仓位：([\d.]+)%", card).group(1))
    assert core + ammo == pytest.approx(target, abs=0.05)
    assert "信号日" in card and "执行日" in card, "必须显式区分信号日与执行日"


def test_instruction_card_without_position_asks_for_it(features):
    card = pipeline.instruction_card(features)
    assert "请提供当前仓位" in card
