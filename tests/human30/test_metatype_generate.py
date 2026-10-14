# tests/human30/test_metatype_generate.py
# -*- coding: utf-8 -*-
"""🟡 Metatype 生成 + 确定性降级 + 守卫 3。"""
import json

import pytest

from fg_system.human30 import llm, metatype

LEVELS = {"mind": 3, "body": 2, "spirit": 1, "vocation": 2}


def _client(text):
    return lambda prompt: text


def _boom(prompt):
    raise OSError("no llm")


def test_ok_path():
    payload = json.dumps({"metatype": "The Integrator", "narrative": "你在整合中前进。"})
    r = metatype.generate(LEVELS, client=_client(payload))
    assert r["degraded"] is False
    assert r["via"] == "injected"
    assert r["metatype"] == "The Integrator"
    assert r["narrative"]


def test_ok_path_with_json_fence():
    text = '```json\n{"metatype": "X", "narrative": "y"}\n```'
    r = metatype.generate(LEVELS, client=_client(text))
    assert r["degraded"] is False
    assert r["metatype"] == "X"


def test_client_raises_degrades():
    r = metatype.generate(LEVELS, client=_boom)
    assert r["degraded"] is True
    assert r["via"] == "deterministic"
    assert r["metatype"]
    assert not any(ch.isdigit() for ch in r["metatype"])   # 不含数字 ✓


def test_bad_json_degrades():
    r = metatype.generate(LEVELS, client=_client("不是 JSON"))
    assert r["degraded"] is True
    assert r["metatype"]


def test_empty_name_degrades():
    r = metatype.generate(LEVELS, client=_client('{"metatype": "  ", "narrative": "x"}'))
    assert r["degraded"] is True


def test_fallback_has_no_digits_with_unknown_level():
    """有 None 层级时降级也不得崩、不得含数字 ✓。"""
    lv = {"mind": None, "body": 1, "spirit": 1, "vocation": 1}
    r = metatype.generate(lv, client=_boom)
    assert r["degraded"] is True
    assert r["metatype"]
    assert not any(ch.isdigit() for ch in r["metatype"])


def test_determinism_of_degradation():
    a = metatype.generate(LEVELS, client=_boom)
    b = metatype.generate(LEVELS, client=_boom)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_unregistered_raises(tmp_path, monkeypatch):
    """守卫 3：未登记 ⇒ 抛（**调用时**检查 ✓）。"""
    p = tmp_path / "log.md"
    p.write_text("空日志", encoding="utf-8")
    monkeypatch.setattr(llm, "DECISION_LOG", str(p))
    with pytest.raises(RuntimeError) as e:
        metatype.generate(LEVELS, client=_client("{}"))
    assert "H-REV-001" in str(e.value)


def test_import_does_not_require_registration(tmp_path, monkeypatch):
    """§9.3：登记检查**不得**在 import 路径上 ✗。"""
    p = tmp_path / "log.md"
    p.write_text("空", encoding="utf-8")
    monkeypatch.setattr(llm, "DECISION_LOG", str(p))
    import importlib
    importlib.reload(metatype)
    assert hasattr(metatype, "generate")
