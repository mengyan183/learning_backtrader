# tests/human30/test_assess_level.py
# -*- coding: utf-8 -*-
"""判层规则（确定性降级路径）。守卫 13：互异不得静默取中位数；守卫 14：假性转变交叉校验。"""
import pytest

from fg_system.human30 import assess


def test_all_same_high_confidence():
    r = assess.judge_level([3, 3, 3])
    assert r["level"] == 3
    assert r["confidence"] == "high"
    assert r["straddling"] is False
    assert r["answers"] == [3, 3, 3]


def test_two_one_medium_confidence_straddling():
    r = assess.judge_level([2, 2, 3])
    assert r["level"] == 2
    assert r["confidence"] == "medium"
    assert r["straddling"] is True


def test_all_distinct_is_null_not_silent_median():
    """守卫 13：三题互异 ⇒ level=None，**不得**静默返回 2。"""
    r = assess.judge_level([1, 2, 3])
    assert r["level"] is None
    assert r["confidence"] == "low"
    assert r["straddling"] is True


def test_rejects_out_of_range():
    with pytest.raises(ValueError):
        assess.judge_level([0, 2, 3])
    with pytest.raises(ValueError):
        assess.judge_level([1, 2, 4])


def test_false_transformation_crosscheck_downgrades():
    """守卫 14：自评 L3 但命中该象限假性转变指标 ⇒ 降 confidence + 打标。"""
    r = assess.judge_level([3, 3, 3], quadrant="mind", ft_hits=["自称开放却拒绝异见"])
    assert r["level"] == 3
    assert r["false_transformation"] is True
    assert r["confidence"] in ("medium", "low")


def test_judge_all_quadrants_returns_four():
    answers = {"mind": [3, 3, 3], "body": [2, 2, 1],
               "spirit": [1, 1, 2], "vocation": [1, 2, 3]}
    out = assess.judge_all(answers)
    assert set(out) == {"mind", "body", "spirit", "vocation"}
    assert out["mind"]["level"] == 3
    assert out["body"]["level"] == 2
    assert out["spirit"]["level"] == 1
    assert out["vocation"]["level"] is None      # 互异
