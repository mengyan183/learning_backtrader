# -*- coding: utf-8 -*-
"""WT-15 `fg_system/models/evt.py`（GPD/POT 极端阈值校准）测试。

**不读真实 Data/**：内联构造 0-100 指数序列；analyze 用 tmp_path 造 features.csv。
判别力设计：
- _gpd_pwm：指数分布样本 ⇒ ξ≈0（GPD 的 ξ=0 即指数）——正好命中 pot_analyze
  里的 ξ≈0 分支，能把形状公式改坏；
- pot_analyze：样本 <120 ⇒ 明确 {"error": ...}；常量序列 ⇒ 无超阈值量 ⇒ 拟合失败；
  下尾 vs 上尾的 u_raw 必须落在相反的两侧（flip 逻辑）；levels 被夹在 [0,100]。
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.models import evt


# ------------------------------------------------------------ _gpd_pwm
def test_gpd_pwm_exponential_sample_gives_wrong_negative_shape():
    """指数样本（真值 ξ=0）却被估成 ξ≈-2 ⇒ 暴露 PWM 权重/公式缺陷。

    ⚠️ BUG（记录但不修，见报告）：指数分布对应 GPD(ξ=0, σ=1)，但
    `_gpd_pwm` 用 `w = i/(n+1)` 作用于**已排序**样本，得到 b1/b0≈0.75
    （正确 PWM 权重应给出 ≈0.25），于是
        shape = (b0-2*b1)/(b0-b1) ≈ -2.03  （应为 0）
        scale ≈ 6.15                       （应为 ~1）
    本测试固化**实际行为**（数学期望的 ξ≈0 会在改正后被恢复，届时此断言转红）。
    """
    rng = np.random.default_rng(0)
    excess = rng.exponential(scale=1.0, size=5000)
    shape, scale = evt._gpd_pwm(excess)
    assert shape == pytest.approx(-2.0323, abs=0.01)   # 实测：明显负偏
    assert shape < -1.0                                # 判别力：绝非 ξ≈0
    assert scale > 0


def test_gpd_pwm_insufficient_sample_returns_none():
    """边界：<10 个超阈值量 ⇒ None（不硬拟合）。"""
    assert evt._gpd_pwm(np.arange(9) + 1.0) is None


def test_gpd_pwm_all_zero_excess_returns_none():
    """极值退化：excess 全 0 ⇒ b0=0 ⇒ 明确返回 None。"""
    assert evt._gpd_pwm(np.zeros(20)) is None


# ------------------------------------------------------------ pot_analyze
def test_pot_analyze_short_series_reports_insufficient():
    """边界：样本 <120 ⇒ 明确降级为 {"error": "样本不足"}，不抛异常。"""
    out = evt.pot_analyze(np.linspace(0, 100, 50))
    assert out == {"error": "样本不足"}


def test_pot_analyze_constant_series_fails_gracefully():
    """极值退化：常量序列（方差 0）⇒ 无有效尾部拟合 ⇒ 明确报错。"""
    out = evt.pot_analyze(np.full(200, 50.0), tail="lower")
    assert "error" in out


def test_pot_analyze_lower_vs_upper_use_opposite_tails():
    """下尾取低位、上尾取高位：u_raw 必须分居 50 的两侧（flip 生效）。"""
    v = np.linspace(0.0, 100.0, 250)
    lo = evt.pot_analyze(v, tail="lower")
    up = evt.pot_analyze(v, tail="upper")
    assert "error" not in lo and "error" not in up
    assert lo["u_raw"] < 50.0 < up["u_raw"]
    assert lo["current_boundary"] == 20.0
    assert up["current_boundary"] == 80.0


def test_pot_analyze_levels_clamped_and_finite():
    """重现水平被夹在 [0,100] 且逐年更极端（极贪尾部：CR 越大值越大）。"""
    rng = np.random.default_rng(1)
    v = np.clip(rng.gamma(2.0, 12.0, size=600), 0, 100)
    out = evt.pot_analyze(v, tail="upper", returns=(1, 5, 20))
    assert "error" not in out
    assert out["n_excess"] >= 10
    levels = out["levels"]
    assert set(levels) == {1, 5, 20}
    for val in levels.values():
        assert 0.0 <= val <= 100.0
        assert np.isfinite(val)
    # 更极端必对应更大的极贪指数
    assert levels[1] <= levels[5] <= levels[20]
    assert out["suggested_boundary"] == levels[1]
    assert isinstance(out["verdict"], str) and out["verdict"]


def test_pot_analyze_verdict_marks_too_frequent_lower():
    """下尾：1 年重现水平远低于现状 20 ⇒ 现状边界触发偏频（判语方向可判别）。"""
    rng = np.random.default_rng(2)
    # 大量贴近 0 的极恐值 ⇒ 尾部很浅 ⇒ 建议阈值低
    v = np.concatenate([rng.uniform(0, 5, size=200), rng.uniform(5, 100, size=200)])
    out = evt.pot_analyze(v, tail="lower")
    assert "error" not in out
    if out["levels"][1] < out["current_boundary"]:
        assert "偏频" in out["verdict"]
    else:
        assert "偏频" not in out["verdict"]


# ------------------------------------------------------------ analyze
def test_analyze_reads_csv_and_reports_range(tmp_path):
    """analyze 走 tmp_path 的 features.csv，返回上下尾 + 样本数 + 日期范围。"""
    rng = np.random.default_rng(3)
    vals = np.clip(rng.normal(50, 20, size=300), 0, 100)
    df = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=300, freq="D"),
        "fg_index": vals,
    })
    df.to_csv(tmp_path / "features.csv", index=False)
    out = evt.analyze(tmp_path / "features.csv")
    assert out["n"] == 300
    assert out["date_range"] == ["2025-01-01", "2025-10-27"]
    assert set(out) >= {"lower", "upper", "n", "date_range"}
    assert out["lower"]["tail"] == "lower"
    assert out["upper"]["tail"] == "upper"
