# -*- coding: utf-8 -*-
"""WT-15 `fg_system/models/markov.py`（档位转移马尔可夫）测试。

**不读真实 Data/**：全部用内联的小 zone 序列构造。
判别力设计：
- 状态贴身的序列 → 转移矩阵对角线 = 1、稳态全落在该状态（而非均匀分布）；
- 交替/有偏序列 → 矩阵行为已知手算值；
- 空/单元素 → 明确返回 None，而不是抛异常或返回垃圾。
"""
import numpy as np
import pytest

from fg_system.models import markov

ZONES = markov.ZONES  # 5


# ------------------------------------------------------------ transition_matrix
def test_transition_matrix_sticky_series_is_identity():
    """全同序列永远自转移 ⇒ P 为单位阵、行和为 1。"""
    P = markov.transition_matrix([2, 2, 2, 2, 2])
    assert P.shape == (ZONES, ZONES)
    assert P[2, 2] == pytest.approx(1.0)
    # 其他格全 0（判别力：不是均匀 1/5）
    assert P[2].sum() == pytest.approx(1.0)
    assert np.count_nonzero(P[2]) == 1
    assert np.allclose(P.sum(axis=1), [0, 0, 1, 0, 0])


def test_transition_matrix_counts_are_normalised_per_row():
    """序列 [0,1,0,1,...] 的同行计数被正确归一化。"""
    P = markov.transition_matrix([0, 1, 0, 1, 0, 1])
    # 0→1 出现 3 次（0 是起点共 3 次）⇒ P[0,1]=1
    assert P[0, 1] == pytest.approx(1.0)
    assert P[1, 0] == pytest.approx(1.0)
    assert np.allclose(P.sum(axis=1), [1, 1, 0, 0, 0])


def test_transition_matrix_single_and_empty_return_none():
    """边界：长度 <2 无法构成转移 ⇒ None。"""
    assert markov.transition_matrix([]) is None
    assert markov.transition_matrix([3]) is None


def test_transition_matrix_out_of_range_zones_ignored():
    """越界 zone（负数/≥5）不得污染矩阵，也不应崩。"""
    P = markov.transition_matrix([0, 0, 7, -1, 1, 1])
    assert P[0, 0] == pytest.approx(1.0)   # 0→0 那次有效
    assert P[1, 1] == pytest.approx(1.0)   # 1→1 那次有效
    assert P.sum() == pytest.approx(2.0)   # 仅 2 条有效转移（越界未被计入）
    assert np.allclose(P.sum(axis=1), [1, 1, 0, 0, 0])


# ------------------------------------------------------------ steady_state
def test_steady_state_sticky_matrix_leaks_mass_but_peaks_at_state():
    """自环链（zone 0/1/3/4 无出边）：稳态**峰值在状态 2**，但未归一化。

    ⚠️ BUG（记录但不修，见报告）：序列只含 zone 2 ⇒ P 仅第 2 行非零，
    其余行为全 0（无出边）。`pi @ P` 迭代把落进零行的质量漏掉，收敛到
    [0,0,0.2,0,0]（sum=0.2，不是概率分布）。方向对（峰在 2），但下游
    model_report.py 直接按它比大小选"长期稳态档位"，数值不可信。
    """
    P = markov.transition_matrix([2] * 5)
    pi = markov.steady_state(P)
    assert pi[2] == pytest.approx(1.0 / ZONES)   # 实测：0.2（初值均分）
    assert np.count_nonzero(pi) == 1             # 只有状态 2 非零
    assert pi.sum() == pytest.approx(0.2)        # 判别力：sum≠1（质量泄漏）


def test_steady_state_zero_matrix_collapses_to_all_zeros():
    """全零矩阵（无出边）⇒ 迭代衰减到全 0，而非概率分布。

    ⚠️ BUG（记录但不修）：`pi @ 0 = 0`，随后差值 <tol 直接返回全 0 向量。
    这**不是概率分布**（sum=0），下游用 `max(i, key=pi[i])` 会得到任意档位。
    本测试固化实际行为。
    """
    assert markov.steady_state(None) is None
    pi = markov.steady_state(np.zeros((ZONES, ZONES)))
    assert pi is not None
    assert np.allclose(pi, 0.0)              # 实测：全 0（非 1/5，也非 NaN）
    assert np.all(np.isfinite(pi))


# ------------------------------------------------------------ persistence
def test_persistence_diagonal_mean_and_none():
    assert markov.persistence(np.eye(ZONES)) == pytest.approx(1.0)
    assert markov.persistence(np.full((ZONES, ZONES), 0.2)) == pytest.approx(0.2)
    assert markov.persistence(None) is None


# ------------------------------------------------------------ forward_dist
def test_forward_dist_sticky_stays_put():
    """自环矩阵：无论几跳都停在起点。"""
    P = markov.transition_matrix([3] * 5)
    d = markov.forward_dist(P, 3, steps=10)
    assert d[3] == pytest.approx(1.0)
    assert d.sum() == pytest.approx(1.0)


def test_forward_dist_two_state_alternation_after_odd_even_steps():
    """确定性交替 0↔1：奇数步到对面、偶数步回原位。"""
    P = markov.transition_matrix([0, 1, 0, 1, 0, 1])
    assert markov.forward_dist(P, 0, steps=1)[1] == pytest.approx(1.0)
    assert markov.forward_dist(P, 0, steps=2)[0] == pytest.approx(1.0)


def test_forward_dist_none_returns_none():
    assert markov.forward_dist(None, 0, steps=3) is None


# ------------------------------------------------------------ analyze
def test_analyze_returns_matrix_steady_persistence():
    """analyze 汇总矩阵/稳态/惯性；此处固化稳态**未归一化**的实际行为。

    ⚠️ BUG（记录但不修）：序列里 zone 3/4 从未出现，其行为全 0（无出边），
    迭代 `pi @ P` 每步把落进这些行概率质量"漏掉" ⇒ 返回的稳态 sum≈0.6
    而非 1。下游 model_report.py 直接读它选"长期稳态最可能档位"，会失真。
    本测试固化实际行为（正确实现应 sum=1，届时本测试转红即为信号）。
    """
    zones = [0, 0, 1, 1, 2, 2, 2, 1, 0]
    out = markov.analyze(zones)
    assert out["matrix"] is not None
    assert np.asarray(out["matrix"]).shape == (ZONES, ZONES)
    # persistence = 对角均值，至少有一个入边 ⇒ 非 0
    assert 0.0 < out["persistence"] <= 1.0
    ss = np.asarray(out["steady_state"])
    assert np.all(ss >= 0)
    assert ss.sum() > 0
    assert abs(ss.sum() - 1.0) > 0.1        # 实测：未归一（质量泄漏）
    assert "horizons" not in out  # 未给 start_zone ⇒ 不做前瞻


def test_analyze_with_start_zone_emits_horizons():
    zones = [0, 0, 1, 1, 2, 2, 2, 1, 0]
    out = markov.analyze(zones, start_zone=0, horizons=(1, 5))
    assert set(out["horizons"].keys()) == {1, 5}
    for h in (1, 5):
        item = out["horizons"][h]
        assert 0 <= item["most_likely"] < ZONES
        assert 0.0 <= item["prob"] <= 1.0
        assert len(item["dist"]) == ZONES
        assert sum(item["dist"]) == pytest.approx(1.0, abs=1e-3)


def test_analyze_short_series_degrades_without_start_zone():
    """单元素序列 ⇒ 无法建矩阵，analyze 明确降级（matrix=None），不抛异常。"""
    out = markov.analyze([2])
    assert out["matrix"] is None
    assert out["steady_state"] is None
    assert out["persistence"] is None
