# -*- coding: utf-8 -*-
"""`scripts/feishu_send.py` 的 bsk **会话生命周期**测试（2026-10-27 泄漏修复）。

🔴 **背景** ✗：`Bsk.run()` 给**所有**命令追加 `--session` ✗ ⇒
`bsk session stop <sid> --session <sid>` **非法** ✗ ⇒ `check=False` 把错误吞掉 ✗
⇒ **会话永远停不掉** ✗ ⇒ 每次发送泄漏一个 ⇒ 累积 10+ 后
`bsk observe` **挂起不返回** ✗（实测表现为「发送环节不稳」✗）。

本文件锁住：会话生命周期命令**不得**带 `--session` ✓；普通命令**必须**带 ✓。
"""
import importlib.util
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    spec = importlib.util.spec_from_file_location(
        "feishu_send", os.path.join(REPO, "scripts", "feishu_send.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fs = _load()


class _Proc:
    def __init__(self, out="", rc=0):
        self.stdout = out
        self.stderr = ""
        self.returncode = rc


@pytest.fixture
def calls(monkeypatch):
    """记录所有 `bsk` 调用 ✓（`session start` 返回假 sid ✓）。"""
    box = []

    def fake_run(cmd, **kw):
        box.append(list(cmd))
        if "start" in cmd:
            return _Proc(out="abc123\n")
        return _Proc(out="")

    monkeypatch.setattr(fs.subprocess, "run", fake_run)
    return box


def test_start_does_not_pass_session_flag(calls):
    """🔴 `session start` 时还没有会话 ⇒ 不得带 `--session` ✗。"""
    b = fs.Bsk()
    sid = b.start(no_focus=False)
    assert sid == "abc123"
    assert "--session" not in calls[0]


def test_stop_does_not_pass_session_flag(calls):
    """🔴 **核心回归**：`session stop` 不得带 `--session` ✗（带则非法 ⇒ 泄漏 ✗）。"""
    b = fs.Bsk()
    b.start(no_focus=True)
    b.stop()
    stop_cmd = [c for c in calls if "stop" in c][0]
    assert "--session" not in stop_cmd, "stop 命令带了 --session ⇒ 会静默失败 ✗"
    assert stop_cmd == ["bsk", "session", "stop", "abc123"]


def test_reap_stops_all_sessions(calls):
    """发送前必须先收割残留会话 ✓。"""
    fs.Bsk().reap()
    assert calls[-1] == ["bsk", "session", "stop", "--all"]


def test_regular_command_still_uses_session(calls):
    """普通命令**必须**带 `--session` ✓（否则操作不到目标会话 ✗）。"""
    b = fs.Bsk()
    b.start()
    b.run("observe", "--json")
    obs = [c for c in calls if "observe" in c][0]
    assert obs == ["bsk", "observe", "--json", "--session", "abc123"]


def test_stop_clears_session(calls):
    b = fs.Bsk()
    b.start()
    b.stop()
    assert b.session is None
