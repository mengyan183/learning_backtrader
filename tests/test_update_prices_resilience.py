# -*- coding: utf-8 -*-
"""`update_prices` 的失败熔断 ✓（2026-11-20 每日链实测 1364s 才失败）。

背景：网络断时 39 标的 × 5 次重试 × 35s 超时 ⇒ 这一步跑了 23 分钟 ✗，
每日链白等；而失败原因（`rc=1`）要等到最后才暴露 ✗。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fg_system.data import fetch as F  # noqa: E402


@pytest.fixture()
def no_sleep(monkeypatch):
    monkeypatch.setattr(F.time, "sleep", lambda _s: None)


def test_aborts_after_consecutive_failures(tmp_path, monkeypatch, no_sleep):
    """连续失败到阈值就停 ✓ —— 不许把 39 个标的全撞一遍超时 ✗。"""
    calls = []

    def boom(sym, **_kw):
        calls.append(sym)
        raise RuntimeError("net down")

    monkeypatch.setattr(F, "fetch_symbol", boom)
    with pytest.raises(RuntimeError, match="提前结束"):
        F.update_prices(path=str(tmp_path / "p.csv"),
                        symbols=["A", "B", "C", "D", "E"], max_fail=2)
    assert len(calls) == 2, "熔断后不该继续抓：%s" % calls


def test_aborts_on_deadline(tmp_path, monkeypatch):
    """总预算到点就收 ✓ —— 即便每个标的都能成功。"""
    clock = {"t": 0.0}

    def slow_now():
        clock["t"] += 100.0          # 每次看表都跳 100s
        return clock["t"]

    monkeypatch.setattr(F.time, "time", slow_now)
    monkeypatch.setattr(F.time, "sleep", lambda _s: None)
    monkeypatch.setattr(F, "fetch_symbol",
                        lambda sym, **_kw: F.pd.DataFrame(
                            columns=F.PRICE_COLUMNS))
    with pytest.raises(RuntimeError, match="预算"):
        F.update_prices(path=str(tmp_path / "p.csv"),
                        symbols=["A", "B", "C"], deadline_s=150)


def test_partial_data_is_saved_before_raising(tmp_path, monkeypatch, no_sleep):
    """已取到的数据必须**先落盘**再抛错 ✓ —— 不能因为一个标的失败全丢 ✗。"""
    ok = F.pd.DataFrame([{"symbol": "A", "date": "2026-11-20",
                          "open": 1.0, "high": 1.0, "low": 1.0,
                          "close": 1.0, "volume": 100}])

    def flaky(sym, **_kw):
        if sym == "A":
            return ok
        raise RuntimeError("net down")

    monkeypatch.setattr(F, "fetch_symbol", flaky)
    path = tmp_path / "p.csv"
    with pytest.raises(RuntimeError):
        F.update_prices(path=str(path), symbols=["A", "B", "C"],
                        max_fail=2)
    assert path.exists(), "部分数据没落盘 ✗"
    text = path.read_text(encoding="utf-8")
    assert "A" in text and "2026-11-20" in text
