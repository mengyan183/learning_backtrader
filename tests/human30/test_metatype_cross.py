# tests/human30/test_metatype_cross.py
# -*- coding: utf-8 -*-
"""跨象限解锁/阻塞〔Prompt〕与假性转变/回退〔主文〕+〔Prompt〕。"""
from fg_system.human30 import metatype


def test_unlocks_when_source_reaches_l2():
    out = metatype.cross_quadrant({"mind": 2, "body": 1, "spirit": 1, "vocation": 1})
    assert ("mind", "vocation") in out["unlocked"]
    assert ("body", "spirit") not in out["unlocked"]


def test_blocks_when_source_low():
    out = metatype.cross_quadrant({"mind": 1, "body": 1, "spirit": 1, "vocation": 2})
    assert ("mind", "vocation") in out["blocked"]


def test_cross_quadrant_skips_unknown():
    out = metatype.cross_quadrant({"mind": None, "body": 1, "spirit": 1, "vocation": 1})
    assert out["unlocked"] == [] and out["blocked"] == []


def test_false_transformation_flag():
    r = metatype.false_transformation(
        {"mind": 3, "body": 2, "spirit": 2, "vocation": 2},
        hits={"mind": ["自称开放却拒绝异见"]})
    assert r["mind"] is True
    assert r["body"] is False


def test_false_transformation_no_hits():
    r = metatype.false_transformation({"mind": 3, "body": 3, "spirit": 3, "vocation": 3})
    assert r == {"mind": False, "body": False, "spirit": False, "vocation": False}


def test_regression_flag_from_history():
    r = metatype.regression(
        {"mind": 2, "body": 2, "spirit": 2, "vocation": 2},
        {"mind": 3, "body": 2, "spirit": 2, "vocation": 1})
    assert r["mind"] is True        # 3 → 2 下降
    assert r["vocation"] is False   # 1 → 2 上升
    assert r["body"] is False       # 持平
