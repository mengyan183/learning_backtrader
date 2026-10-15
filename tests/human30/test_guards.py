# tests/human30/test_guards.py
# -*- coding: utf-8 -*-
"""设计 §9.2 的守卫 1~6（Human 3.0 v2）。

1 不进口判决层 / 2 产物不进仓位 / 3 🟡 入口需登记 /
4 失败确定性降级 / 5 输出无数字分数 / 6 输出无交易动词
"""
import glob
import json
import os
import re

import pytest

from fg_system.human30 import assess, llm, metatype, render

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TITLE = "HUMAN 3.0 DEVELOPMENT ASSESSMENT RESULTS"
LEVELS = {"mind": 3, "body": 2, "spirit": 1, "vocation": 2}
PHASES = {"mind": "discovery", "body": "dissonance",
          "spirit": "dissonance", "vocation": "uncertainty"}


# ---------------------------------------------------------------- 守卫 1
# 判决层模块名特征（设计 §9.2-1）
_DECISION_HINTS = ("pipeline", "signal", "backtest", "strategy", "risk")


def _iter_repo_py():
    """全仓 .py（排除 tests/ 与 human30 包内部 ✓）。"""
    for p in glob.glob(os.path.join(_REPO, "**", "*.py"), recursive=True):
        rel = os.path.relpath(p, _REPO).replace("\\", "/")
        if rel.startswith("tests/") or rel.startswith("fg_system/human30/"):
            continue
        yield rel, p


def test_human30_not_imported_by_decision():
    """守卫 1：**判决层**任何模块不得 import human30 ✗。

    ⚠️ 判别力说明：本守卫只在**含判决层的完整仓库**里有效 ✓。
    部分提取工作区（如 lb-p2 ✗）里判决层缺失 ⇒ **显式 skip** ✗（不静默通过 ✗）。
    """
    scanned, decision, hits = [], [], []
    for rel, p in _iter_repo_py():
        try:
            src = open(p, encoding="utf-8").read()
        except OSError:
            continue
        scanned.append(rel)
        base = os.path.basename(rel).lower()
        if any(h in base for h in _DECISION_HINTS):
            decision.append(rel)
            if re.search(r"^\s*(from|import)\s+.*\bhuman30\b", src, re.M):
                hits.append(rel)
    assert hits == [], "判决层 import 了 human30：%s" % hits
    if not decision:
        pytest.skip("本工作区无判决层模块（部分提取 ✗）：已扫 %d 个文件 %s —— "
                    "守卫 1 的判别力需在**完整仓库**（Mac）验证 ✓"
                    % (len(scanned), scanned))


# ---------------------------------------------------------------- 守卫 2
def test_metatype_never_reaches_position():
    """守卫 2：🟡 产物**不得**出现在仓位相关符号里 ✗。"""
    forbidden = ["target_position", "ZONE_EDGES", "CORE_CAP"]
    src = open(os.path.join(_REPO, "fg_system", "human30", "metatype.py"),
               encoding="utf-8").read()
    for name in forbidden:
        assert name not in src, "metatype.py 出现仓位符号：%s" % name
    src2 = open(os.path.join(_REPO, "fg_system", "human30", "render.py"),
                encoding="utf-8").read()
    for name in forbidden:
        assert name not in src2, "render.py 出现仓位符号：%s" % name


# ---------------------------------------------------------------- 守卫 3
def test_metatype_requires_registered_exception(tmp_path, monkeypatch):
    """守卫 3：未登记 ⇒ **两个** 🟡 入口都抛（调用时检查 ✓ §9.3）。"""
    p = tmp_path / "log.md"
    p.write_text("空日志", encoding="utf-8")
    monkeypatch.setattr(llm, "DECISION_LOG", str(p))
    with pytest.raises(RuntimeError):
        metatype.generate(LEVELS, client=lambda x: "{}")
    with pytest.raises(RuntimeError):
        assess.judge_via_llm({"mind": [{"q": "q", "a": "a"}]}, client=lambda x: "{}")


def test_guard3_not_on_import_path():
    """守卫 3 的**负向**：包 import 路径上不得有登记检查 ✗。"""
    p = os.path.join(_REPO, "fg_system", "human30", "__init__.py")
    src = open(p, encoding="utf-8").read()
    assert "require_exception" not in src
    assert "is_exception_registered" not in src


# ---------------------------------------------------------------- 守卫 4
def test_metatype_failure_degrades_deterministically():
    """守卫 4：client 抛错 ⇒ 两次结果**逐位相同** ✓。"""
    def boom(prompt):
        raise OSError("no llm")
    a = metatype.generate(LEVELS, client=boom)
    b = metatype.generate(LEVELS, client=boom)
    assert a["degraded"] is True
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_judge_failure_degrades_deterministically():
    def boom(prompt):
        raise OSError("no llm")
    fixed = {q: [2, 2, 2] for q in ("mind", "body", "spirit", "vocation")}
    a = assess.judge_via_llm({"mind": [{"q": "q", "a": "a"}]},
                             client=boom, fixed_answers=fixed)
    b = assess.judge_via_llm({"mind": [{"q": "q", "a": "a"}]},
                             client=boom, fixed_answers=fixed)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---------------------------------------------------------------- 守卫 5
def test_no_numeric_score_in_rendered_output():
    """守卫 5：渲染输出**无数字分数 / Level 数字** ✗（剥掉固定标题后查 ✓）。"""
    t = render.render_report(levels=LEVELS, phases=PHASES,
                             metatype={"metatype": "X", "narrative": "y"},
                             lifestyle=None, cross=None, degraded=False)
    body = t.replace(TITLE, "")
    assert not re.search(r"\d+\s*/\s*100", body)
    assert not re.search(r"Level\s*[123]", body)
    assert not re.search(r"\b\d+\.\d+\b", body)


def test_brief_block_has_no_score_digits(tmp_path, monkeypatch):
    """守卫 5 扩展：简报节同样禁分数数字 ✗。"""
    from fg_system.human30 import store as _st
    p = tmp_path / "h.json"
    monkeypatch.setattr(_st, "DATA_PATH", str(p))
    _st._save({"records": [{
        "date": "2026-10-15", "mind": 70.0, "body": 60.0,
        "spirit": 40.0, "vocation": 65.0, "note": "",
    }]})
    from fg_system.human30 import metatype as _mt, render as _rd
    rec = _st.latest()
    t = "\n".join(_rd.quadrant_lines(rec["levels"], rec["phases"])
                  + [_rd.metatype_line(_mt.deterministic_metatype(rec["levels"]))])
    assert not re.search(r"\bL[123]\b", t)
    assert not re.search(r"\d+\.\d+", t)


# ---------------------------------------------------------------- 守卫 6
def test_output_no_trade_verbs():
    """守卫 6：渲染输出无交易动词 ✗。"""
    t = render.render_report(levels=LEVELS, phases=PHASES,
                             metatype={"metatype": "X", "narrative": "y"},
                             lifestyle=None, cross=None, degraded=False)
    for v in ["减仓", "加仓", "买入", "卖出", "仓位", "止损", "清仓", "抄底"]:
        assert v not in t, "输出含交易动词：%s" % v
