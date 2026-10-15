# -*- coding: utf-8 -*-
"""P0：交易前检查单的「视角自问」两项（nuwa 结合方案 P0）。

纪律：
- 视角 = 思维顾问 / 研究参考，**永不进信号、不改任何确定性规则**（红线）。
- 文案确定性模板，**不调 LLM**。
- `behavior_checklist` 只在极端档位（zi==0 / 回撤达首档 / zi==4）返回文本；
  两个调用点把 `_PERSPECTIVE_PROMPTS` 追加到该文本末尾（本测试验证**真实组装路径**）。
- 非极端档位 `behavior_checklist` 返回 None ⇒ 简报无「行为检查清单」节（保持既有行为）。
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location(
        "invest_research", REPO / "scripts" / "invest_research.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ir = _load()


def _snap(fg_index=None, drawdown=None):
    """最小 snap：behavior_checklist 只读 snap['fg']['fg_index'] 与 snap['fg']['drawdown']。"""
    fg = {}
    if fg_index is not None:
        fg["fg_index"] = fg_index
    if drawdown is not None:
        fg["drawdown"] = drawdown
    return {"date": "2026-10-15", "fg": fg}


def _stub(monkeypatch, name, value):
    """把模块级重依赖替换为离线固定值（不碰 Data/、不联网）。"""
    monkeypatch.setattr(ir, name, value)


def _patch_assembly(monkeypatch):
    """把 build_brief_sections 里的重依赖全部打桩，只保留行为检查清单节。"""
    from fg_system import fed as _fed
    monkeypatch.setattr(_fed, "fed_context", lambda: {})
    monkeypatch.setattr(_fed, "fed_brief_text", lambda _c: "（fed 打桩）")
    _stub(monkeypatch, "_freshness_block", lambda: None)
    _stub(monkeypatch, "build_snapshot_lines", lambda snap: "（快照打桩）")
    _stub(monkeypatch, "risk_brief_text", lambda snap: None)
    _stub(monkeypatch, "action_brief_text", lambda snap: None)
    _stub(monkeypatch, "_human30_brief", lambda: None)
    _stub(monkeypatch, "_factor_breakdown", lambda: None)
    _stub(monkeypatch, "news_text", lambda news: "（新闻打桩）")
    _stub(monkeypatch, "_major_contradiction", lambda: None)
    _stub(monkeypatch, "kb_evidence", lambda snap, n=2: [])
    _stub(monkeypatch, "_kb_brief_text", lambda hits: "（知识库打桩）")
    _stub(monkeypatch, "_source_footnote", lambda snap: "（来源打桩）")


def _checklist_section(secs):
    """取「行为检查清单」节的正文；无该节返回 None。"""
    for item in secs:
        if isinstance(item, tuple) and "行为检查清单" in item[0]:
            return item[1]
    return None


def _has_perspective(txt):
    return (
        txt is not None
        and "🟡 思维顾问" in txt
        and "芒格审视" in txt
        and "塔勒布审视" in txt
    )


class TestPerspectivePromptsOnExtremes:
    def test_extreme_fear_appends_perspective(self, monkeypatch):
        """① zi == 0（极度恐惧）⇒ 检查清单节末尾追加视角自问两项。"""
        _patch_assembly(monkeypatch)
        secs = ir.build_brief_sections(_snap(fg_index=10), None, None, None)
        txt = _checklist_section(secs)
        assert _has_perspective(txt), txt

    def test_extreme_greed_appends_perspective(self, monkeypatch):
        """② zi == 4（极度贪婪）⇒ 检查清单节末尾追加视角自问两项。"""
        _patch_assembly(monkeypatch)
        secs = ir.build_brief_sections(_snap(fg_index=90), None, None, None)
        txt = _checklist_section(secs)
        assert _has_perspective(txt), txt

    def test_drawdown_first_batch_appends_perspective(self, monkeypatch):
        """③ 回撤 ≥ 20%（首档）⇒ 检查清单节末尾追加视角自问两项。"""
        _patch_assembly(monkeypatch)
        secs = ir.build_brief_sections(_snap(fg_index=50, drawdown=0.25), None, None, None)
        txt = _checklist_section(secs)
        assert _has_perspective(txt), txt

    def test_non_extreme_has_no_checklist(self, monkeypatch):
        """④ 非极端（zi==2 且回撤 5%）⇒ behavior_checklist 返回 None，简报无检查清单节。"""
        _patch_assembly(monkeypatch)
        snap = _snap(fg_index=50, drawdown=0.05)
        assert ir.behavior_checklist(snap) is None
        secs = ir.build_brief_sections(snap, None, None, None)
        assert _checklist_section(secs) is None


class TestBranchTextUnchanged:
    """守卫：3 个分支的**原文案**未被改动（视角只在末尾追加）。"""

    def test_extreme_fear_branch_text_unchanged(self):
        out = ir.behavior_checklist(_snap(fg_index=10))
        assert out.startswith("极度恐惧档位 · 行为检查清单【研究参考】")
        assert "抄底三黑③档差没拉开" in out
        assert "芒格审视" not in out          # 原文案不含视角

    def test_extreme_greed_branch_text_unchanged(self):
        out = ir.behavior_checklist(_snap(fg_index=90))
        assert out.startswith("极度贪婪档位 · 行为检查清单【研究参考】")
        assert "集中度检查" in out

    def test_drawdown_branch_text_unchanged(self):
        out = ir.behavior_checklist(_snap(fg_index=50, drawdown=0.25))
        assert out.startswith("回撤已达首档（弹药开始释放）· 行为检查清单【研究参考】")

    def test_perspective_constant_markers(self):
        p = ir._PERSPECTIVE_PROMPTS
        assert "🟡 思维顾问" in p
        assert "芒格审视" in p and "塔勒布审视" in p
