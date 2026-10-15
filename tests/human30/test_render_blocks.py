# -*- coding: utf-8 -*-
"""P5：看板/简报共用的去数字片段。"""
import re

from fg_system.human30 import render

LEVELS = {"mind": 3, "body": 2, "spirit": 1, "vocation": 2}
PHASES = {"mind": "discovery", "body": "dissonance",
          "spirit": "dissonance", "vocation": "uncertainty"}
VERBS = ["减仓", "加仓", "买入", "卖出", "仓位", "止损", "清仓", "抄底", "杠杆"]


def _all():
    return "\n".join(render.quadrant_lines(LEVELS, PHASES)
                     + [render.lifestyle_line({"name": "The Integrator", "problem": "X"}),
                        render.metatype_line({"metatype": "Y", "degraded": True}),
                        render.metatype_line({"metatype": "Y", "degraded": False}),
                        render.degraded_note()])


def test_no_digits():
    assert not re.search(r"\d", _all())


def test_no_trade_verbs():
    for v in VERBS:
        assert v not in _all()


def test_quadrant_lines_shape():
    lines = render.quadrant_lines(LEVELS, PHASES)
    assert len(lines) == 4
    assert all("：" in ln for ln in lines)


def test_unknown_level_is_undetermined():
    lv = {k: None for k in LEVELS}
    assert "未判定" in "\n".join(render.quadrant_lines(lv, {}))


def test_metatype_line_marks_ai_and_degrade():
    assert render.AI_PREFIX in render.metatype_line({"metatype": "Y"})
    assert "非原框架" in render.metatype_line({"metatype": "Y", "degraded": True})


def test_deterministic_metatype_no_digits():
    from fg_system.human30 import metatype
    r = metatype.deterministic_metatype(LEVELS)
    assert r["degraded"] is True
    assert not re.search(r"\d", r["metatype"])
