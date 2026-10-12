# -*- coding: utf-8 -*-
"""WT-15 `fg_system/models/bayes_update.py`（Beta-Bernoulli）测试。

**不读真实 Data/**：已知解析解的 Beta 分布（均匀/对称/大样本）验证数值分位，
hypotheses.md 用 tmp_path 造表。
判别力设计：
- Beta(1,1)=Uniform(0,1)：均值 0.5、95%CI≈[0.025,0.975]（数值 ppf 精度可见）；
- 对称 Beta(a,a) 均值必 0.5、区间关于 0.5 对称；
- 似然主导：大量成功/失败 ⇒ 后验均值贴向经验频率且 CI 收窄；
- 先验加成：a2 = prior_a + successes、b2 = prior_b + (trials - successes)；
- 空表格/不存在文件 ⇒ {}（明确降级）。
"""
import numpy as np
import pytest

from fg_system.models import bayes_update as bu


# ------------------------------------------------------------ beta_moments / _beta_ppf
def test_beta_moments_uniform_is_half_and_wide_ci():
    """Beta(1,1)=U(0,1)：均值 0.5，95%CI≈[0.025, 0.975]。"""
    mean, lo, hi = bu.beta_moments(1.0, 1.0)
    assert mean == pytest.approx(0.5)
    assert lo == pytest.approx(0.025, abs=5e-3)
    assert hi == pytest.approx(0.975, abs=5e-3)


def test_beta_moments_symmetric_is_symmetric_interval():
    """对称 Beta(a,a) 区间必关于 0.5 对称，且夹住 0.5。"""
    mean, lo, hi = bu.beta_moments(5.0, 5.0)
    assert mean == pytest.approx(0.5)
    assert lo < 0.5 < hi
    assert (0.5 - lo) == pytest.approx(hi - 0.5, abs=5e-3)


def test_beta_ppf_is_monotone_and_bounded():
    """分位函数单调、落在 (0,1)。"""
    qs = [0.025, 0.25, 0.5, 0.75, 0.975]
    vals = [bu._beta_ppf(q, 3.0, 7.0) for q in qs]
    assert vals == sorted(vals)
    assert all(0.0 < v < 1.0 for v in vals)


# ------------------------------------------------------------ update
def test_update_posterior_parameters_add_counts():
    """a' = prior_a + successes，b' = prior_b + (trials - successes)。"""
    r = bu.update(successes=3, trials=5, prior_a=1.0, prior_b=1.0)
    assert r["posterior_a"] == pytest.approx(4.0)
    assert r["posterior_b"] == pytest.approx(3.0)
    assert r["successes"] == 3 and r["trials"] == 5


def test_update_mean_tracks_empirical_rate_with_many_trials():
    """似然主导：大量观测 ⇒ 后验均值贴近经验频率，CI 收窄。"""
    r = bu.update(successes=90, trials=100)
    assert r["posterior_mean"] == pytest.approx(0.9, abs=0.03)
    lo, hi = r["ci95"]
    assert lo < r["posterior_mean"] < hi
    assert (hi - lo) < 0.15  # 比均匀先验的 ~0.95 宽区间明显收窄
    assert 0.0 <= lo <= hi <= 1.0


def test_update_boundary_zero_trials_follows_prior():
    """边界：0/0 观测 ⇒ 后验退回先验 Beta(1,1)，均值 0.5。"""
    r = bu.update(successes=0, trials=0)
    assert r["posterior_a"] == pytest.approx(1.0)
    assert r["posterior_b"] == pytest.approx(1.0)
    assert r["posterior_mean"] == pytest.approx(0.5)


def test_update_all_failures_and_all_successes():
    """极值：全失败 ⇒ 均值 <0.5 且区间左偏；全成功 ⇒ 均值 >0.5 且区间右偏。"""
    fail = bu.update(successes=0, trials=10)
    succ = bu.update(successes=10, trials=10)
    assert fail["posterior_mean"] < 0.5
    assert succ["posterior_mean"] > 0.5
    assert fail["ci95"][1] < succ["ci95"][0]  # 两个区间不重叠


def test_update_nonzero_prior_shifts_posterior():
    """强先验见证：prior_b 很大时，少量成功也拉不高均值（先验可判别）。"""
    weak = bu.update(successes=3, trials=3)                 # Beta(4,1)
    strong = bu.update(successes=3, trials=3, prior_a=1.0, prior_b=50.0)  # Beta(4,50)
    assert strong["posterior_mean"] < weak["posterior_mean"]
    assert strong["posterior_mean"] < 0.5


# ------------------------------------------------------------ parse_hypothesis_counts
def test_parse_hypothesis_counts_extracts_observed_counts(tmp_path):
    """只认"观察/天数/累计 X/N"语境，忽略分箱区间与日期，且同假说累加。"""
    md = tmp_path / "hypotheses.md"
    md.write_text(
        "| ID | 假说 | 状态 | 备注 |\n"
        "|---|---|---|---|\n"
        "| H-001 | A | verifying | 观察点 3/5 命中 |\n"
        "| H-002 | B | verifying | 天数 1/4，另累计 2/4 |\n"
        "| H-003 | C | verifying | 分箱 40-50/50-55 与 09-25/09-29 |\n",
        encoding="utf-8",
    )
    out = bu.parse_hypothesis_counts(md)
    assert out["H-001"] == {"successes": 3, "trials": 5, "note_snippet": "观察点 3/5 命中"}
    # H-002 两处计数累加
    assert out["H-002"]["successes"] == 3
    assert out["H-002"]["trials"] == 8
    # H-003 的区间/日期不得被当成观察证据
    assert "H-003" not in out


def test_parse_hypothesis_counts_missing_file_returns_empty(tmp_path):
    """边界：文件不存在 ⇒ {}（明确降级，不抛异常）。"""
    assert bu.parse_hypothesis_counts(tmp_path / "nope.md") == {}


def test_parse_hypothesis_counts_empty_table_returns_empty(tmp_path):
    """边界：只有表头、无 H- 行 ⇒ {}。"""
    md = tmp_path / "hypotheses.md"
    md.write_text("| ID | 假说 |\n|---|---|\n", encoding="utf-8")
    assert bu.parse_hypothesis_counts(md) == {}
