# tests/human30/test_metatype_lifestyle.py
# -*- coding: utf-8 -*-
"""Archetype 名称（词表〔Prompt〕）与 Lifestyle 6 类判定。"""
from fg_system.human30 import metatype
from fg_system.human30 import model


def test_archetype_name_from_table():
    assert metatype.archetype_name("mind", 3) == "Creator"
    assert metatype.archetype_name("vocation", 1) == "Clock Puncher"
    assert metatype.archetype_name("spirit", 2) == "Spiritual Shopper"


def test_archetype_name_unknown_level():
    assert metatype.archetype_name("mind", None) == "未判定"


def test_archetype_names_all_quadrants():
    out = metatype.archetype_names({"mind": 3, "body": 2, "spirit": 1, "vocation": 2})
    assert set(out) == {"mind", "body", "spirit", "vocation"}
    assert out["body"] == "Gym Bro"


def test_lifestyle_workaholic():
    """vocation 领先其它三象限 ≥2 档 ⇒ Workaholic（其余三象限均为 L1 ⇒ gap=2 ✓）。"""
    r = metatype.lifestyle({"mind": 1, "body": 1, "spirit": 1, "vocation": 3})
    assert r["name"] == "The Workaholic"


def test_lifestyle_specialist():
    r = metatype.lifestyle({"mind": 3, "body": 1, "spirit": 1, "vocation": 1})
    assert r["name"] == "The Specialist"


def test_lifestyle_integrated():
    r = metatype.lifestyle({"mind": 2, "body": 3, "spirit": 2, "vocation": 2})
    assert r["name"] == "The Integrated"


def test_lifestyle_returns_problem_and_solution():
    r = metatype.lifestyle({"mind": 2, "body": 1, "spirit": 1, "vocation": 3})
    assert r["problem"] and r["solution"]
    assert r["name"] in [a["name"] for a in model.LIFESTYLE_ARCHETYPES]


def test_lifestyle_unknown_when_any_none():
    r = metatype.lifestyle({"mind": None, "body": 1, "spirit": 1, "vocation": 1})
    assert r["name"] == "未判定"
