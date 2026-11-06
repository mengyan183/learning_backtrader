# -*- coding: utf-8 -*-
"""`scripts/fetch_shoutu.py` 的 bsk 上下文/重试测试（2026-11-06）。

**为什么要锁**（四轮实测踩出来的）：

1. 重试分支曾写成「检查 `bsk()` 的返回值」✗ —— 而 `bsk()` 在 rc≠0 时**直接
   raise** ✗ ⇒ 重试是死代码 ✗ ⇒ `fetch_shoutu_history` 在 Mac 上连挂 23 天。
2. 补了 `observe` 仍失败 ✗；补 `cooperate sync` 仍失败 ✗。
3. 最终 `bsk evaluate --help` 写明：`--context <CONTEXT>` 是
   「Control context returned by cooperate sync，**shared-tab 动作必填**」✗
   ⇒ 真正的缺失环节是 **sync 的返回值必须传给每次 evaluate** ✗
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


def test_bsk_eval_passes_context_from_sync(monkeypatch):
    """没有 context 的 evaluate 失败后 ⇒ sync 拿 context ⇒ 带上重试成功。"""
    fs = _load()
    calls = []

    def fake_bsk(args, session=None):
        calls.append(list(args))
        if args[0] == "cooperate":
            return "CTX1\n"
        if args[0] == "evaluate" and "--context" not in args:
            raise RuntimeError(
                "error: shared page control or observation changed")
        return "OK"

    monkeypatch.setattr(fs, "bsk", fake_bsk)
    assert fs.bsk_eval("js", "s1") == "OK"
    assert ["evaluate", "js", "--context", "CTX1"] in calls


def test_bsk_eval_uses_cached_context_without_resync(monkeypatch):
    """已 sync 过 ⇒ 直接带 context 调，不再多付一次 observe+sync。"""
    fs = _load()
    fs._CTX["s1"] = "CTX0"
    calls = []

    def fake_bsk(args, session=None):
        calls.append(list(args))
        return "OK"

    monkeypatch.setattr(fs, "bsk", fake_bsk)
    assert fs.bsk_eval("js", "s1") == "OK"
    assert calls == [["evaluate", "js", "--context", "CTX0"]]


@pytest.mark.parametrize("out,expected", [
    ('{"context": "CTX9"}', "CTX9"),          # ① JSON
    ("synced\ncontext: CTX9\n", "CTX9"),      # ② 前缀行
    ("CTX9", "CTX9"),                          # ③ 裸 token（单行无空格）
    ("refused\nwait then sync\n", ""),         # 认不出 ⇒ 不硬猜
])
def test_parse_context_forms(out, expected):
    """context 有三种可能形态，都不能盲取最后一行（dsh 提醒）。"""
    assert _load()._parse_context(out) == expected


def test_bsk_sync_returns_and_caches_context(monkeypatch):
    """`cooperate sync` 的输出解析成 context 并缓存。"""
    fs = _load()

    def fake_bsk(args, session=None):
        if args[0] == "cooperate":
            return "context: CTX9\n"
        return ""

    monkeypatch.setattr(fs, "bsk", fake_bsk)
    assert fs.bsk_sync("s2") == "CTX9"
    assert fs._CTX["s2"] == "CTX9"


def test_bsk_sync_swallows_errors(monkeypatch):
    """sync/observe 失败**不得抛出**（否则会盖住真正的 evaluate 错误）。"""
    fs = _load()

    def fake_bsk(args, session=None):
        raise RuntimeError("unknown command: %s" % args[0])

    monkeypatch.setattr(fs, "bsk", fake_bsk)
    assert fs.bsk_sync("s1") == ""


def test_bsk_eval_reraises_unrelated_error(monkeypatch):
    """非上下文类错误 ⇒ **不重试**，原样抛出（避免把真错误吞掉）。"""
    fs = _load()
    calls = []

    def fake_bsk(args, session=None):
        calls.append(list(args))
        raise RuntimeError("bsk failed rc=1: syntax error")

    monkeypatch.setattr(fs, "bsk", fake_bsk)
    with pytest.raises(RuntimeError):
        fs.bsk_eval("js", "s1")
    assert calls == [["evaluate", "js"]]


def test_bsk_help_prints_cli_surface(monkeypatch, capsys):
    """失败诊断必须把 CLI 面貌**打到 stdout**（否则任务回执里看不到）。"""
    fs = _load()
    monkeypatch.setattr(fs, "bsk", lambda args, session=None: "usage: bsk ...")
    fs._bsk_help()
    out = capsys.readouterr().out
    assert "### bsk step --help" in out
    assert "### bsk cooperate --help" in out
