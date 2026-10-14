# -*- coding: utf-8 -*-
"""model.py 常量与词表完整性（守卫：词表不得缺 key）。"""
from fg_system.human30 import model


def test_quadrants_and_labels():
    assert model.QUADRANTS == ["mind", "body", "spirit", "vocation"]
    assert set(model.LABELS) == set(model.QUADRANTS)


def test_levels_three():
    assert sorted(model.LEVELS) == [1, 2, 3]
    assert model.LEVELS[1][0].startswith("1.0")
    assert model.LEVELS[2][0].startswith("2.0")
    assert model.LEVELS[3][0].startswith("3.0")


def test_phases_three():
    assert model.PHASES == ["dissonance", "uncertainty", "discovery"]


def test_archetypes_complete_4x3():
    """4 象限 × 3 层级，每格至少 4 个名字（原文 〔Prompt〕）。"""
    assert set(model.ARCHETYPES) == set(model.QUADRANTS)
    for q in model.QUADRANTS:
        assert sorted(model.ARCHETYPES[q]) == [1, 2, 3]
        for lv in (1, 2, 3):
            assert len(model.ARCHETYPES[q][lv]) >= 4


def test_lifestyle_archetypes_six():
    assert len(model.LIFESTYLE_ARCHETYPES) == 6
    names = [a["name"] for a in model.LIFESTYLE_ARCHETYPES]
    assert names == ["The Workaholic", "The Seeker", "The Optimizer",
                     "The Drifter", "The Specialist", "The Integrated"]


def test_false_transformation_16():
    assert set(model.FALSE_TRANSFORMATION) == set(model.QUADRANTS)
    for q in model.QUADRANTS:
        assert len(model.FALSE_TRANSFORMATION[q]) == 4


def test_cross_quadrant_unlock_block():
    assert len(model.UNLOCK_SEQUENCES) == 6
    assert len(model.BLOCK_PATTERNS) == 4


def test_key_principles_five():
    assert len(model.KEY_PRINCIPLES) == 5
