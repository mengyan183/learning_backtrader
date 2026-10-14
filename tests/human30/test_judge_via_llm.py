# tests/human30/test_judge_via_llm.py
# -*- coding: utf-8 -*-
"""🟡 追问主路径 + 失败确定性降级 + 守卫 3。

降级语义（2026-10-14 裁定 ✓）：transcript 是**自由文本** ✗ ⇒ 不得机械映射成 1/2/3 ✗。
  · 有 `fixed_answers` ⇒ 走 judge_all(fixed_answers) ✓（真降级 ✓）
  · 无 `fixed_answers` ⇒ level=None + fallback="fixed_questionnaire" ✓（诚实未判定 ✓）
"""
import json

import pytest

from fg_system.human30 import assess, llm

QUADS = ("mind", "body", "spirit", "vocation")

TRANSCRIPT = {
    "mind": [{"q": "遇到与你世界观矛盾的观念，第一反应？", "a": "先找反面证据"}],
    "body": [], "spirit": [], "vocation": [],
}

GOOD = {
    "mind": {"level": 3, "confidence": "high", "phase": "discovery",
             "traits": {"knowledge": 3, "experience": 2, "skill": 2}},
    "body": {"level": 2, "confidence": "medium", "phase": "dissonance",
             "traits": {"knowledge": 2, "experience": 2, "skill": 2}},
    "spirit": {"level": 1, "confidence": "low", "phase": "dissonance",
               "traits": {"knowledge": 1, "experience": 1, "skill": 1}},
    "vocation": {"level": 2, "confidence": "medium", "phase": "uncertainty",
                 "traits": {"knowledge": 2, "experience": 2, "skill": 1}},
}

FIXED = {q: [2, 2, 2] for q in QUADS}


def _client(payload):
    def c(prompt):
        return payload if isinstance(payload, str) else json.dumps(payload)
    return c


def _boom(prompt):
    raise OSError("no llm")


def test_ok_path():
    r = assess.judge_via_llm(TRANSCRIPT, client=_client(GOOD))
    assert r["degraded"] is False
    assert r["via"] == "injected"
    assert r["mind"]["level"] == 3
    assert set(r) >= {"mind", "body", "spirit", "vocation", "degraded", "via"}


def test_client_raises_with_fixed_answers_uses_judge_all():
    """真降级：给了固定问卷答案 ⇒ 结果与 judge_all 一致 ✓。"""
    r = assess.judge_via_llm(TRANSCRIPT, client=_boom, fixed_answers=FIXED)
    assert r["degraded"] is True
    assert r["via"] == "deterministic"
    base = assess.judge_all(FIXED)
    for q in QUADS:
        assert r[q]["level"] == base[q]["level"]


def test_client_raises_without_fixed_answers_is_undetermined():
    """无固定问卷答案 ⇒ 诚实"未判定" ✓（**不猜** ✗）。"""
    r = assess.judge_via_llm(TRANSCRIPT, client=_boom)
    assert r["degraded"] is True
    assert r["via"] == "deterministic"
    assert r["fallback"] == "fixed_questionnaire"
    for q in QUADS:
        assert r[q]["level"] is None
        assert r[q]["confidence"] == "low"


def test_bad_json_degrades_undetermined():
    r = assess.judge_via_llm(TRANSCRIPT, client=_client("这不是 JSON"))
    assert r["degraded"] is True
    assert r["fallback"] == "fixed_questionnaire"
    for q in QUADS:
        assert r[q]["level"] is None


def test_empty_transcript_degrades():
    r = assess.judge_via_llm({}, client=_client(GOOD))
    assert r["degraded"] is True
    for q in QUADS:
        assert r[q]["level"] is None


def test_illegal_level_degrades():
    bad = json.loads(json.dumps(GOOD))
    bad["mind"]["level"] = 9          # 非法层级 ⇒ 不得静默接受 ✗
    r = assess.judge_via_llm(TRANSCRIPT, client=_client(bad))
    assert r["degraded"] is True
    for q in QUADS:
        assert r[q]["level"] is None


def test_illegal_phase_degrades():
    bad = json.loads(json.dumps(GOOD))
    bad["body"]["phase"] = "nonsense"
    r = assess.judge_via_llm(TRANSCRIPT, client=_client(bad))
    assert r["degraded"] is True


def test_missing_traits_key_degrades():
    bad = json.loads(json.dumps(GOOD))
    del bad["spirit"]["traits"]["skill"]
    r = assess.judge_via_llm(TRANSCRIPT, client=_client(bad))
    assert r["degraded"] is True


def test_determinism_of_degradation():
    """守卫 4 前置：两次降级结果**逐位相同** ✓。"""
    a = assess.judge_via_llm(TRANSCRIPT, client=_boom, fixed_answers=FIXED)
    b = assess.judge_via_llm(TRANSCRIPT, client=_boom, fixed_answers=FIXED)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_unregistered_raises(tmp_path, monkeypatch):
    """守卫 3：未登记 ⇒ 抛（**调用时**检查 ✓）。"""
    p = tmp_path / "log.md"
    p.write_text("空日志", encoding="utf-8")
    monkeypatch.setattr(llm, "DECISION_LOG", str(p))
    with pytest.raises(RuntimeError) as e:
        assess.judge_via_llm(TRANSCRIPT, client=_client(GOOD))
    assert "H-REV-001" in str(e.value)


def test_import_does_not_require_registration(tmp_path, monkeypatch):
    """§9.3：登记检查**不得**在 import 路径上 ✗。"""
    p = tmp_path / "log.md"
    p.write_text("空", encoding="utf-8")
    monkeypatch.setattr(llm, "DECISION_LOG", str(p))
    import importlib
    importlib.reload(assess)          # 未登记也能 import ✓
    assert hasattr(assess, "judge_via_llm")
