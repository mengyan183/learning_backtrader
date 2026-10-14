# tests/human30/test_metatype_score.py
# -*- coding: utf-8 -*-
"""整体分 Σ(层级分)/12〔主文〕与四象限层级聚合。"""
import pytest

from fg_system.human30 import metatype


def test_total_score_all_l1():
    r = metatype.total_score({"mind": 1, "body": 1, "spirit": 1, "vocation": 1})
    assert r["sum"] == 4
    assert r["total"] == pytest.approx(4 / 12, abs=1e-4)      # Σ/12（原文算法）
    assert r["avg_level"] == pytest.approx(1.0, abs=1e-4)     # sum/4（分档用）
    assert r["band"] == "low"


def test_total_score_all_l3():
    r = metatype.total_score({"mind": 3, "body": 3, "spirit": 3, "vocation": 3})
    assert r["sum"] == 12
    assert r["total"] == pytest.approx(1.0, abs=1e-4)
    assert r["avg_level"] == pytest.approx(3.0, abs=1e-4)
    assert r["band"] == "high"


def test_total_score_mixed():
    r = metatype.total_score({"mind": 3, "body": 2, "spirit": 2, "vocation": 1})
    assert r["sum"] == 8
    assert r["total"] == pytest.approx(8 / 12, abs=1e-4)
    assert r["avg_level"] == pytest.approx(2.0, abs=1e-4)
    assert r["band"] == "mid"


def test_total_score_unknown_level_raises():
    with pytest.raises(ValueError):
        metatype.total_score({"mind": None, "body": 2, "spirit": 2, "vocation": 1})


def test_band_boundaries():
    """band 作用在**平均层级**（值域 1~3）上 —— Glitch 的 2.0 / 2.5 阈值只在这个量纲下成立。"""
    assert metatype.band_of(1.99) == "low"
    assert metatype.band_of(2.0) == "mid"
    assert metatype.band_of(2.5) == "mid"
    assert metatype.band_of(2.51) == "high"
    with pytest.raises(ValueError):
        metatype.band_of(0.5)      # 低于平均层级下界 ⇒ 量纲用错


def test_quadrant_levels_from_assess_output():
    judged = {
        "mind": {"level": 3}, "body": {"level": 2},
        "spirit": {"level": 1}, "vocation": {"level": None},
    }
    out = metatype.quadrant_levels(judged)
    assert out["mind"] == 3 and out["body"] == 2 and out["spirit"] == 1
    assert out["vocation"] is None
