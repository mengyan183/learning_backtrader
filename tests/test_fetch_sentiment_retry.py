# -*- coding: utf-8 -*-
"""`fetch_sentiment.py` 的重试 ✓（2026-11-20：CBOE CDN 偶发 SSL 读超时）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_sentiment as FS  # noqa: E402


class _Boom:
    def __init__(self, calls, fail_times):
        self.calls = calls
        self.fail_times = fail_times

    def open(self, req, timeout=None):
        self.calls.append(timeout)
        if len(self.calls) <= self.fail_times:
            raise TimeoutError("The read operation timed out")

        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"ok"
        return _R()


def test_fetch_retries_then_raises(monkeypatch):
    """3 次都失败 ⇒ 抛最后一个异常 ✓（不是静默返回空串 ✗）。"""
    calls = []
    monkeypatch.setattr(FS.urllib.request, "build_opener",
                        lambda h: _Boom(calls, 99))
    monkeypatch.setattr(FS.time, "sleep", lambda _s: None)
    with pytest.raises(TimeoutError):
        FS.fetch("https://cdn/x.csv", retries=3)
    assert len(calls) == 3


def test_fetch_succeeds_on_retry(monkeypatch):
    """第 2 次成功 ⇒ 直接返回 ✓（这才是加 retry 的目的）。"""
    calls = []
    monkeypatch.setattr(FS.urllib.request, "build_opener",
                        lambda h: _Boom(calls, 1))
    monkeypatch.setattr(FS.time, "sleep", lambda _s: None)
    assert FS.fetch("https://cdn/x.csv", retries=3) == "ok"
    assert len(calls) == 2
