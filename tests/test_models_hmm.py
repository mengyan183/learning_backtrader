# -*- coding: utf-8 -*-
"""WT-15 `fg_system/models/hmm.py`（Gaussian HMM）测试。

**不读真实 Data/**：load_features 用 tmp_path 造 features.csv。
判别力设计：
- _log_gauss 手算值：单状态、零均值、单位方差 ⇒ 高斯密度闭式解（改坏公式会红）；
- _forward_backward：gamma 每行和为 1、loglik 有限；状态极可分时 gamma 贴 0/1；
- _viterbi：双峰观测必须解出 0,0,...,1,1,1 而非全同；
- fit_hmm：T<40 → None；可分双峰 → 状态全活且与观测同序。
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.models import hmm

OBS_COLS = hmm.OBS_COLS


def _two_cluster(T=60, seed=0):
    """构造明显可分的两簇：前一半低、后一半高（标准化后仍可分）。"""
    rng = np.random.default_rng(seed)
    lo = rng.normal(-3.0, 0.2, size=(T // 2, len(OBS_COLS)))
    hi = rng.normal(3.0, 0.2, size=(T - T // 2, len(OBS_COLS)))
    return np.vstack([lo, hi])


# ------------------------------------------------------------ _log_gauss
def test_log_gauss_matches_closed_form():
    """K=1、mu=0、cov=1、D=1：log N(x;0,1) = -0.5 x^2 - 0.5 log(2π)。"""
    X = np.array([[0.0], [1.0], [-2.0]])
    lg = hmm._log_gauss(X, np.array([[0.0]]), np.array([[1.0]]))
    assert lg.shape == (3, 1)
    expected = -0.5 * X[:, 0] ** 2 - 0.5 * np.log(2 * np.pi)
    assert np.allclose(lg[:, 0], expected)


def test_log_gauss_prefers_closer_mean():
    """K=2：同一观测对更近的均值给出更高 log 密度。"""
    X = np.array([[0.0]])
    mu = np.array([[0.0], [5.0]])
    cov = np.array([[1.0], [1.0]])
    lg = hmm._log_gauss(X, mu, cov)
    assert lg.shape == (1, 2)
    assert lg[0, 0] > lg[0, 1]


def test_log_gauss_larger_variance_lowers_density_at_mean():
    """极值/退化：在均值处，方差越大密度越低（cov 抖动影响可见）。"""
    X = np.array([[0.0]])
    mu = np.array([[0.0]])
    tight = hmm._log_gauss(X, mu, np.array([[1.0]]))[0, 0]
    loose = hmm._log_gauss(X, mu, np.array([[100.0]]))[0, 0]
    assert tight > loose


# ------------------------------------------------------------ _forward_backward
def test_forward_backward_gamma_rows_sum_to_one():
    X = _two_cluster()
    pi, A, mu, cov = hmm._init_params(X, K=2, seed=1)
    lg = hmm._log_gauss(X, mu, cov)
    alpha, beta, gamma, xi, loglik = hmm._forward_backward(lg, pi, A)
    assert gamma.shape == (len(X), 2)
    assert np.allclose(gamma.sum(axis=1), 1.0)   # gamma 是逐日后验，必归一
    assert np.all(gamma >= 0)
    assert np.isfinite(loglik)
    assert xi.shape == (len(X) - 1, 2, 2)


def test_forward_backward_xi_is_proper_probability():
    """xi 必须是合法概率量：每层和为 1、每个 (t,i) 行和为 1、全有限非负。

    WT-25 修复前：`denom = (alpha[t]*exp(lg[t+1])) @ A.T @ beta[t+1]` 把
    `exp(lg[t+1])` 乘在**源状态 i** 上，而 numer 用的是**目的状态 j**
    ⇒ denom ≠ Σnumer；极可分数据下 denom 下溢为 0，`+1e-300` 把 xi 放大到
    实测 **2.55e300**（正确层和应为 2.55）。修复后按 Σnumer 归一 ⇒ 层和恒为 1 ✓。
    """
    X = _two_cluster()
    pi, A, mu, cov = hmm._init_params(X, K=2, seed=1)
    lg = hmm._log_gauss(X, mu, cov)
    alpha, _, _, xi, _ = hmm._forward_backward(lg, pi, A)
    assert np.all(np.isfinite(xi))                  # 判别力：无 1e300 爆炸
    assert np.all(xi >= 0)
    assert np.allclose(xi.sum(axis=(1, 2)), 1.0)    # 每层（t）和为 1
    # 每个 (t,i) 行：状态 i 在 t 时刻**可能**（alpha>0）则行和为 1，
    # 不可能（alpha=0）则该行全 0 —— 两种都合法，不得出现中间值
    row_sums = xi.sum(axis=2)
    assert np.all((row_sums == 0.0) | np.isclose(row_sums, 1.0))
    assert np.allclose(row_sums[alpha[:-1] > 0], 1.0)
    # M-step 仍必为随机矩阵（下游真正依赖的不变量）
    A_est = xi.sum(axis=0)
    A_est = A_est / (A_est.sum(axis=1, keepdims=True) + 1e-300)
    assert np.allclose(A_est.sum(axis=1), 1.0)
    assert np.all(A_est >= 0)


def test_forward_backward_degenerate_emission_stays_finite():
    """退化发射概率（exp(lg)=0，denom 为 0）⇒ xi 必须**有限**，不得 NaN/inf。

    WT-25 修复前这里会得到 NaN（alpha 除以 0）或 1e300 级垃圾。
    约定：denom=0 表示「该转移不可能发生」⇒ 该层 xi 全 0（层和 0）。
    """
    lg = np.full((4, 2), -1e6)      # exp(-1e6) 下溢为 0
    pi = np.array([0.5, 0.5])
    A = np.array([[0.5, 0.5], [0.5, 0.5]])
    alpha, beta, gamma, xi, loglik = hmm._forward_backward(lg, pi, A)
    assert np.all(np.isfinite(xi))
    assert np.all(xi >= 0)
    assert np.all(np.isfinite(alpha))
    assert np.all(np.isfinite(beta))
    assert np.all(np.isfinite(gamma))
    layer_sums = xi.sum(axis=(1, 2))
    assert np.all((layer_sums == 0.0) | np.isclose(layer_sums, 1.0))


def test_forward_backward_sharp_clusters_give_decisive_gamma():
    """两簇极可分：低簇观测几乎必然（~1）落在低均值状态上。"""
    X = _two_cluster(seed=2)
    pi, A, mu, cov = hmm._init_params(X, K=2, seed=0)
    lg = hmm._log_gauss(X, mu, cov)
    _, _, gamma, _, _ = hmm._forward_backward(lg, pi, A)
    low_state = int(np.argmin(mu[:, 0]))
    # 第一半（低簇）对 low_state 的后验应显著 > 0.5
    assert gamma[: len(X) // 2, low_state].mean() > 0.5


def test_forward_backward_single_observation_has_empty_xi():
    """边界：T=1 ⇒ xi 形状 (0,K,K)，gamma 仍归一。"""
    lg = np.array([[0.3, 0.7]])
    pi = np.array([0.5, 0.5])
    A = np.array([[0.5, 0.5], [0.5, 0.5]])
    alpha, beta, gamma, xi, loglik = hmm._forward_backward(lg, pi, A)
    assert xi.shape == (0, 2, 2)
    assert gamma.shape == (1, 2)
    assert gamma.sum() == pytest.approx(1.0)
    assert np.isfinite(loglik)


# ------------------------------------------------------------ _viterbi
def test_viterbi_recovers_two_cluster_order():
    """可分双峰观测 ⇒ Viterbi 解出前低后高（保证状态含 2 种，非全同）。"""
    X = _two_cluster(seed=3)
    pi, A, mu, cov = hmm._init_params(X, K=2, seed=0)
    lg = hmm._log_gauss(X, mu, cov)
    states = hmm._viterbi(lg, pi, A)
    assert states.shape == (len(X),)
    assert states[: len(X) // 2].mean() != states[len(X) // 2:].mean()
    assert len(set(states.tolist())) == 2


def test_viterbi_single_observation_picks_argmax():
    lg = np.array([[0.1, 0.9, 0.2]])
    pi = np.full(3, 1.0 / 3)
    A = np.full((3, 3), 1.0 / 3)
    assert hmm._viterbi(lg, pi, A).tolist() == [1]


# ------------------------------------------------------------ fit_hmm
def test_fit_hmm_short_series_returns_none():
    """边界：T<40 ⇒ 明确返回 None（不训练、不崩）。"""
    assert hmm.fit_hmm(np.random.default_rng(0).normal(size=(39, 5))) is None


def test_fit_hmm_recovers_well_separated_clusters():
    """强可分双峰 ⇒ 状态全活、后验均值分居 0 两侧、观测前后段落不同状态。"""
    X = _two_cluster(T=120, seed=4)
    X[:60] -= 4.0   # 拉大簇间距（标准化后仍为两团）
    X[60:] += 4.0
    f = hmm.fit_hmm(X, K=2)
    assert f is not None
    assert f["all_alive"] is True
    assert set(f["states"].tolist()) == {0, 1}
    # 两个状态的均值必须落在一低一高（不是坍缩到同一点）
    mu0 = np.sort(f["mu"][:, 0])
    assert mu0[1] - mu0[0] > 1.0
    # 观测前后两段应各自被同一状态占据
    assert f["states"][:60].mean() != f["states"][60:].mean()


def test_fit_hmm_deterministic_across_runs():
    """seed 固定 ⇒ 两次训练逐位一致（states/loglik），可复现。"""
    X = _two_cluster(T=80, seed=5)
    f1 = hmm.fit_hmm(X, K=2)
    f2 = hmm.fit_hmm(X, K=2)
    assert f1 is not None and f2 is not None
    assert np.array_equal(f1["states"], f2["states"])
    assert f1["loglik"] == pytest.approx(f2["loglik"])
    # 转移矩阵按行归一
    assert np.allclose(f1["A"].sum(axis=1), 1.0)


# ------------------------------------------------------------ load_features
def test_load_features_drops_missing_rows(tmp_path):
    """缺 fg_index/观测列的行被剔除；返回 date 与观测矩阵。"""
    rows = [
        ("2026-01-01", 10.0, 20.0, 1.0, 2.0, 30.0),
        ("2026-01-02", None, 21.0, 1.1, 2.1, 31.0),   # fg 缺失 → 剔除
        ("2026-01-03", 12.0, 22.0, 1.2, 2.2, 32.0),
        ("2026-01-04", 13.0, None, 1.3, 2.3, 33.0),   # 观测列缺失 → 剔除
    ]
    df = pd.DataFrame(rows, columns=["date"] + OBS_COLS)
    df.to_csv(tmp_path / "features.csv", index=False)
    dates, X = hmm.load_features(tmp_path)
    assert list(dates.dt.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-03"]
    assert X.shape == (2, len(OBS_COLS))
    assert X[0, 0] == pytest.approx(10.0)
