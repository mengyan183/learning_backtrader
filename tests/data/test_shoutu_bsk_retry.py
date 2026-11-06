# -*- coding: utf-8 -*-
"""`scripts/fetch_shoutu.py` 的 bsk 重试测试（2026-11-06）。

**为什么要锁**：重试分支曾写成「检查 `bsk()` 的返回值」✗ —— 而 `bsk()` 在
rc≠0 时**直接 raise** ✗ ⇒ 重试是死代码 ✗ ⇒ `fetch_shoutu_history` 在 Mac 上
连挂 23 天（最后日期停在 2026-10-14）✗。
"""
import importlib.util
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "scripts", "fetch_shoutu.py")


def _load():
    spec = importlib.util.spec_from_file_location("fetch_shoutu", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bsk_eval_retries_after_cooperate_error(monkeypatch):
    """`shared page control` 类失败 ⇒ observe 一次再重试，第二次返回结果。"""
    fs = _load()
    calls = []

    def fake_bsk(args, session=None):
        calls.append(list(args))
        if len(calls) == 1:
            raise RuntimeError(
                "bsk ['evaluate', 'js'] failed rc=1: error: shared page control "
                "or observation changed")
        return "OK"

    monkeypatch.setattr(fs, "bsk", fake_bsk)
    assert fs.bsk_eval("js", "s1") == "OK"
    # 重试前必须先重建控制上下文（observe + cooperate sync）再 evaluate
    assert calls == [["evaluate", "js"], ["observe"], ["cooperate", "sync"],
                     ["evaluate", "js"]]


def test_bsk_sync_swallows_errors(monkeypatch):
    """重建上下文的子命令失败**不得抛出**（否则会盖住真正的 evaluate 错误）。"""
    fs = _load()

    def fake_bsk(args, session=None):
        raise RuntimeError("unknown command: %s" % args[0])

    monkeypatch.setattr(fs, "bsk", fake_bsk)
    assert fs.bsk_sync("s1") is None


def test_bsk_eval_escalates_to_cooperate_sync(monkeypatch):
    """`observe` 也不管用时必须再试 `cooperate sync`（bsk 提示的恢复动作）。

    2026-11-06 实测：只补 `observe` 仍报同一个错 ✗（14:08 回执）。
    """
    fs = _load()
    calls = []

    def fake_bsk(args, session=None):
        calls.append(list(args))
        n_eval = sum(1 for c in calls if c[0] == "evaluate")
        if args[0] == "evaluate" and n_eval <= 2:
            raise RuntimeError(
                "error: shared page control or observation changed")
        return "OK"

    monkeypatch.setattr(fs, "bsk", fake_bsk)
    assert fs.bsk_eval("js", "s1") == "OK"
    assert ["cooperate", "sync"] in calls
    assert sum(1 for c in calls if c[0] == "evaluate") == 3


def test_bsk_eval_reraises_unrelated_error(monkeypatch):
    """非 cooperate 类错误 ⇒ **不重试**，原样抛出（避免把真错误吞掉）。"""
    fs = _load()
    calls = []

    def fake_bsk(args, session=None):
        calls.append(list(args))
        raise RuntimeError("bsk failed rc=1: syntax error")

    monkeypatch.setattr(fs, "bsk", fake_bsk)
    with pytest.raises(RuntimeError):
        fs.bsk_eval("js", "s1")
    assert calls == [["evaluate", "js"]]
