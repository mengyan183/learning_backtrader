# -*- coding: utf-8 -*-
"""§4.5 抄底三黑进简报：触发条件 + 不与「集中优势兵力」矛盾。"""
import sys

sys.path.insert(0, "scripts")

from invest_research import behavior_checklist   # noqa: E402


def _snap(fg_index=None, drawdown=None):
    return {"fg": {"fg_index": fg_index, "drawdown": drawdown}}


def test_extreme_fear_includes_three_black():
    """极度恐惧档（fg_index=10 ⇒ zi==0）⇒ 含抄底三黑①/②/③。"""
    t = behavior_checklist(_snap(fg_index=10))
    assert t
    assert "抄底三黑①" in t
    assert "抄底三黑②" in t
    assert "抄底三黑③" in t


def test_extreme_fear_no_concentrate_wording():
    """锁住矛盾已修：极度恐惧清单**不含**「集中优势兵力」。"""
    t = behavior_checklist(_snap(fg_index=10))
    assert "集中优势兵力" not in t


def test_drawdown_first_batch_triggers_checklist():
    """关键回归：回撤 ≥ 首档（20%）且指数中性 ⇒ **也**返回抄底三黑。

    证明「真正抄底时它会出现」（指数不极端也能触发）。
    """
    t = behavior_checklist(_snap(fg_index=50, drawdown=0.25))   # 小数形态
    assert t
    assert "抄底三黑①" in t
    assert "抄底三黑②" in t
    assert "抄底三黑③" in t
    assert "集中优势兵力" not in t


def test_drawdown_percent_literal_compatible():
    """百分数字面量（25.0）与小数（0.25）等价 ⇒ 同样触发。"""
    t = behavior_checklist(_snap(fg_index=50, drawdown=25.0))
    assert t
    assert "抄底三黑①" in t


def test_shallow_drawdown_neutral_returns_none():
    """回撤 < 20% 且指数中性 ⇒ 返回 None（不误报）。"""
    assert behavior_checklist(_snap(fg_index=50, drawdown=0.05)) is None


def test_missing_drawdown_does_not_crash():
    """回撤字段缺失 ⇒ 不崩（返回 None 或既有行为）。"""
    assert behavior_checklist(_snap(fg_index=50, drawdown=None)) is None
    assert behavior_checklist(_snap(fg_index=50)) is None


def test_no_markdown_emphasis_in_plain_text_brief():
    """🔴 简报是**纯文本** ⇒ 不得出现 markdown 粗体标记 `**`（会原样显示）。"""
    for snap in ({"fg": {"fg_index": 10}},
                 {"fg": {"fg_index": 50, "drawdown": 0.25}},
                 {"fg": {"fg_index": 90}}):
        t = behavior_checklist(snap) or ""
        assert "**" not in t, "简报文本含 markdown 粗体标记：%r" % t
