# tests/human30/test_render_report.py
# -*- coding: utf-8 -*-
"""§7 官方输出格式 + §7.1 硬约束。"""
import re

from fg_system.human30 import render

LEVELS = {"mind": 3, "body": 2, "spirit": 1, "vocation": 2}
PHASES = {"mind": "discovery", "body": "dissonance",
          "spirit": "dissonance", "vocation": "uncertainty"}
TRADE_VERBS = ["减仓", "加仓", "买入", "卖出", "仓位", "止损", "清仓", "抄底", "杠杆"]
TITLE = "HUMAN 3.0 DEVELOPMENT ASSESSMENT RESULTS"


def _body(text):
    """剥掉固定标题（`Human 3.0` 是**系统名** ✓，不是分数 ✗）后再查数字。

    裁定（2026-10-14）：§7.1 约束的是「分数与 Level 数字」✗，
    不含产品名 `Human 3.0` ✓。
    """
    return text.replace(TITLE, "")


def _full():
    return render.render_report(
        levels=LEVELS, phases=PHASES,
        metatype={"metatype": "The Integrator", "narrative": "你在整合中前进。",
                  "degraded": False},
        lifestyle=None, cross=None, degraded=False)


def test_has_official_sections():
    t = _full()
    for key in ("HUMAN 3.0 DEVELOPMENT ASSESSMENT RESULTS", "YOUR METATYPE",
                "YOUR LIFESTYLE ARCHETYPE", "QUADRANT BREAKDOWN",
                "CROSS-QUADRANT DYNAMICS", "GLITCH ASSESSMENT"):
        assert key in t, "缺字段：%s" % key


def test_levels_rendered_without_digits():
    """🔴 model.LEVELS 名自带 '1.0 ' ⇒ 必须剥掉 ✗。"""
    t = _full()
    assert "顺从者" in t or "Conformist" in t      # 剥掉了前缀，仍保留词 ✓
    assert "1.0 顺从者" not in t


def test_no_numeric_score():
    t = _full()
    assert not re.search(r"\d+\s*/\s*100", _body(t))
    assert not re.search(r"Level\s*[123]", _body(t))
    assert not re.search(r"\b\d+\.\d+\b", _body(t))


def test_no_bare_digits_at_all():
    """更严：剥掉固定标题后**一个数字都不许有** ✗。"""
    t = _full()
    assert not re.search(r"\d", _body(t)), "输出含数字：%r" % re.findall(r".{0,12}\d.{0,12}", _body(t))


def test_no_trade_verbs():
    t = _full()
    for v in TRADE_VERBS:
        assert v not in t, "输出含交易动词：%s" % v


def test_ai_fields_marked():
    assert "AI 复盘（🟡 研究参考，非系统信号）" in _full()


def test_degraded_marks_not_official():
    t = render.render_report(levels=LEVELS, phases={}, metatype=None,
                             lifestyle=None, cross=None, degraded=True)
    assert "非原框架的追问判定" in t


def test_no_glitch_recommendation():
    """§7.1-4：只做风险提示，**不做**具体 Glitch 推荐 ✗。"""
    t = _full()
    assert "Most aligned with your development" not in t
    assert "建议自然发展" in t or "谨慎" in t or "可考虑" in t


def test_unknown_level_renders_undetermined():
    lv = {"mind": None, "body": None, "spirit": None, "vocation": None}
    t = render.render_report(levels=lv, phases={}, metatype=None,
                             lifestyle=None, cross=None, degraded=True)
    assert "未判定" in t
    assert not re.search(r"\d", _body(t))
