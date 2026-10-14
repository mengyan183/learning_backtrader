# tests/human30/test_assess_phase_traits.py
# -*- coding: utf-8 -*-
"""相位（1 题三选一）与 Traits（3 题三档）判定。"""
import pytest

from fg_system.human30 import assess


def test_judge_phase_maps_three_options():
    assert assess.judge_phase("stale") == "dissonance"
    assert assess.judge_phase("exploring") == "uncertainty"
    assert assess.judge_phase("integrating") == "discovery"


def test_judge_phase_unknown_when_missing():
    assert assess.judge_phase(None) == "unknown"
    assert assess.judge_phase("") == "unknown"


def test_judge_phase_rejects_bad_value():
    with pytest.raises(ValueError):
        assess.judge_phase("whatever")


def test_judge_traits_maps_three_tiers():
    t = assess.judge_traits({"knowledge": "yes", "experience": "some", "skill": "no"})
    assert t == {"knowledge": 3, "experience": 2, "skill": 1}


def test_judge_traits_rejects_bad_value():
    with pytest.raises(ValueError):
        assess.judge_traits({"knowledge": "maybe", "experience": "some", "skill": "no"})


def test_phase_label_helper():
    assert assess.phase_label("dissonance") == "失调"
    assert assess.phase_label("unknown") == "未知"
