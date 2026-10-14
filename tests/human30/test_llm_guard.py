# tests/human30/test_llm_guard.py
# -*- coding: utf-8 -*-
"""守卫 3：🟡 入口必须先有 H-REV-001 登记；客户端必须可注入。"""
import pytest

from fg_system.human30 import llm


def test_registered_in_real_repo():
    """真实仓库里 H-REV-001 已登记（P0 连带义务 ✓）。"""
    assert llm.is_exception_registered() is True


def test_not_registered_raises(tmp_path):
    p = tmp_path / "decision-log.md"
    p.write_text("# 空日志\n\n无任何登记\n", encoding="utf-8")
    assert llm.is_exception_registered(str(p)) is False
    with pytest.raises(RuntimeError) as e:
        llm.require_exception(str(p))
    assert "H-REV-001" in str(e.value)


def test_require_exception_ok():
    llm.require_exception()      # 真实仓库 ⇒ 不抛


def test_call_llm_uses_injected_client():
    seen = {}

    def fake(prompt):
        seen["prompt"] = prompt
        return "OK"

    text, via = llm.call_llm("你好", client=fake)
    assert text == "OK"
    assert via == "injected"
    assert seen["prompt"] == "你好"


def test_call_llm_default_client_is_hermes_first(monkeypatch):
    """默认客户端先试 Hermes；失败抛错（**不**在此层吞异常 ⇒ 由上层降级 ✓）。"""
    called = []

    def boom(url, body, headers, timeout):
        called.append(url)
        raise OSError("no server")

    monkeypatch.setattr(llm, "_post_json", boom)
    with pytest.raises(Exception):
        llm.call_llm("hi", client=None, allow_nvidia=False)
    assert called, "未尝试 Hermes"
