# -*- coding: utf-8 -*-
"""抓取节流与重试测试（第 12.14 条）。

RED 证据不是假设，而是**实测**：连续抓 12 个标的时从第 8 个起全部失败
（**连 SPY 都失败**，而 SPY 显然有数据）——这是数据源**限流**。
原实现只在**失败后**固定 sleep 2 秒，对「成功但过于密集」的请求毫无作用，
而限流恰恰由密集的**成功**请求触发。
"""
import urllib.error

import pytest

from fg_system import config
from fg_system.data import fetch


class _Bad:
    """open 必失败。"""

    def open(self, req, timeout=None):
        raise OSError("boom")


class _OK:
    def __init__(self, body=b"hello"):
        self.body = body

    def open(self, req, timeout=None):
        import io
        return io.BytesIO(self.body)


# ---------------------------------------------------------------- 请求前节流

def test_throttle_waits_when_calls_too_close():
    slept = []
    fetch._LAST_CALL[0] = 100.0
    fetch._throttle(clock=lambda: 100.0, sleep=slept.append)
    assert slept == [pytest.approx(config.FETCH_MIN_INTERVAL)]


def test_throttle_no_wait_when_interval_elapsed():
    slept = []
    fetch._LAST_CALL[0] = 0.0
    fetch._throttle(clock=lambda: 1e6, sleep=slept.append)
    assert slept == []


def test_throttle_updates_last_call():
    fetch._LAST_CALL[0] = 0.0
    fetch._throttle(clock=lambda: 42.0, sleep=lambda s: None)
    assert fetch._LAST_CALL[0] == 42.0


def test_throttle_is_applied_before_every_attempt(monkeypatch):
    """**核心回归**：每次尝试前都必须节流，不能只在失败后 sleep。"""
    calls = []
    monkeypatch.setattr(fetch, "_opener", lambda url: _Bad())
    monkeypatch.setattr(fetch, "_throttle", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "FETCH_RETRIES", 4)
    with pytest.raises(RuntimeError):
        fetch._get("http://x")
    assert len(calls) == 4, "每次尝试前都要节流"


# ---------------------------------------------------------------- 指数退避

def test_backoff_grows_exponentially():
    b = config.FETCH_BACKOFF_BASE
    assert fetch._backoff(0, rng=lambda: 1.0) == pytest.approx(b)
    assert fetch._backoff(1, rng=lambda: 1.0) == pytest.approx(b * 2)
    assert fetch._backoff(3, rng=lambda: 1.0) == pytest.approx(b * 8)


def test_backoff_is_capped():
    assert fetch._backoff(99, rng=lambda: 1.0) == pytest.approx(config.FETCH_BACKOFF_MAX)


def test_backoff_has_jitter_in_50_to_100_percent():
    """抖动取 [50%, 100%]，避免多次重试同时打过去（惊群）。"""
    b = config.FETCH_BACKOFF_BASE
    assert fetch._backoff(0, rng=lambda: 0.0) == pytest.approx(b * 0.5)
    assert fetch._backoff(0, rng=lambda: 1.0) == pytest.approx(b)


def test_get_retries_full_count_then_raises(monkeypatch):
    slept = []
    monkeypatch.setattr(fetch, "_opener", lambda url: _Bad())
    monkeypatch.setattr(fetch, "_throttle", lambda *a, **k: None)
    monkeypatch.setattr(fetch.time, "sleep", slept.append)
    monkeypatch.setattr(config, "FETCH_RETRIES", 3)
    with pytest.raises(RuntimeError):
        fetch._get("http://x")
    assert len(slept) == 3, "每次失败后都要退避"


def test_get_does_not_retry_on_404(monkeypatch):
    """404 是**永久失败**，重试只会白耗限流额度。"""
    n = [0]

    class NotFound:
        def open(self, req, timeout=None):
            n[0] += 1
            raise urllib.error.HTTPError("http://x", 404, "nf", {}, None)

    monkeypatch.setattr(fetch, "_opener", lambda url: NotFound())
    monkeypatch.setattr(fetch, "_throttle", lambda *a, **k: None)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        fetch._get("http://x")
    assert n[0] == 1, "404 必须立即放弃"


def test_get_returns_body_on_success(monkeypatch):
    monkeypatch.setattr(fetch, "_opener", lambda url: _OK(b"hello"))
    monkeypatch.setattr(fetch, "_throttle", lambda *a, **k: None)
    assert fetch._get("http://x") == b"hello"


def test_opener_is_reused(monkeypatch):
    """opener 必须复用（原实现每次请求都新建，含 SSL 上下文）。

    2026-10-06 起 `_OPENER` 是 `{"direct": opener, "proxy": opener}` 字典
    （按域名分流代理）—— 复用判据改为清空后两次调用返回同一对象。
    """
    fetch._OPENER.clear()
    assert fetch._opener("http://direct.example") is fetch._opener("http://direct.example")
    assert fetch._opener() is fetch._opener(), "无 url 时走 direct 桶，同样应复用"
    fetch._OPENER.clear()


# ---------------------------------------------------------------- assetclass 回退

_ROWS_STOCKS = (b'{"data":{"tradesTable":{"rows":[{"date":"09/18/2026",'
                b'"close":"$10.00","volume":"1,000","open":"$9.50",'
                b'"high":"$10.20","low":"$9.40"}]}}}')
_EMPTY = b'{"data":{"tradesTable":{"rows":[]}}}'


def test_fetch_symbol_falls_back_to_stocks(monkeypatch):
    """`etf` 返回空表时必须回退 `stocks`（实测 AXTI / CRCL 就是这样）。"""
    seen = []

    def fake_get(url, retries=None):
        seen.append(url)
        return _EMPTY if "assetclass=etf" in url else _ROWS_STOCKS

    monkeypatch.setattr(fetch, "_get", fake_get)
    df = fetch.fetch_symbol("AXTI")
    assert len(seen) == 2 and "assetclass=stocks" in seen[1]
    assert len(df) == 1
    assert df.iloc[0]["close"] == pytest.approx(10.0), "stocks 格式的 $ 必须被剥离"


def test_fetch_symbol_does_not_try_stocks_when_etf_works(monkeypatch):
    """`etf` 有数据时**不得**多发一次请求——那会白耗限流额度。"""
    seen = []
    monkeypatch.setattr(fetch, "_get",
                        lambda url, retries=None: seen.append(url) or _ROWS_STOCKS)
    df = fetch.fetch_symbol("TQQQ")
    assert len(seen) == 1
    assert len(df) == 1


def test_fetch_symbol_returns_empty_frame_when_both_empty(monkeypatch):
    monkeypatch.setattr(fetch, "_get", lambda url, retries=None: _EMPTY)
    df = fetch.fetch_symbol("NOPE")
    assert df.empty
    assert list(df.columns) == fetch.PRICE_COLUMNS
