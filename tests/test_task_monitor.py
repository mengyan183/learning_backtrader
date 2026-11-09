# -*- coding: utf-8 -*-
"""task_monitor（定时任务与数据新鲜度监控）pytest。"""
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import task_monitor as tm  # noqa: E402


def _make(tmp_path, name, rel, col="date", days_ago=0):
    """在 tmp 下造一个数据文件：date 列为 today - days_ago。"""
    d = date.today().isoformat() if days_ago == 0 else (
        date.fromordinal(date.today().toordinal() - days_ago).isoformat())
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("%s,x\n%s,1\n" % (col, d), encoding="utf-8")


def test_all_fresh_returns_zero(tmp_path, monkeypatch):
    """全部数据新鲜 + 任务注册在位 → 退出 0。"""
    monkeypatch.setattr(tm, "REPO", tmp_path)
    monkeypatch.setattr(tm, "STATE_FILE", tmp_path / "monitor_state.json")
    monkeypatch.setattr(tm, "DATA_CHECKS", [
        ("f1", "Data/raw/a.csv", "date", 3),
        ("f2", "Data/raw/b.csv", "date", 7),
    ])
    _make(tmp_path, "a", "Data/raw/a.csv")
    _make(tmp_path, "b", "Data/raw/b.csv")
    monkeypatch.setattr(tm, "TASKS", ["com.test.one", "com.test.two"])
    monkeypatch.setattr(
        tm.subprocess, "run",
        lambda *a, **k: type("R", (), {"stdout": "PID\tSTAT\tcom.test.one\nPID\tSTAT\tcom.test.two\n"})())
    assert tm.main([]) == 0


def test_stale_detected_returns_one(tmp_path, monkeypatch, capsys):
    """数据停更超过容忍 → 退出 1 且输出停更项。"""
    monkeypatch.setattr(tm, "REPO", tmp_path)
    monkeypatch.setattr(tm, "STATE_FILE", tmp_path / "monitor_state.json")
    monkeypatch.setattr(tm, "DATA_CHECKS", [("vix", "Data/raw/vix.csv", "date", 4)])
    _make(tmp_path, "vix", "Data/raw/vix.csv", days_ago=10)
    monkeypatch.setattr(tm, "TASKS", [])
    monkeypatch.setattr(tm.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "PID\tSTAT\tlaunchd\n"})())
    assert tm.main([]) == 1
    assert "数据停更" in capsys.readouterr().out


def test_missing_file_reported(tmp_path, monkeypatch, capsys):
    """文件缺失 → 退出 1 且输出缺失项。"""
    monkeypatch.setattr(tm, "REPO", tmp_path)
    monkeypatch.setattr(tm, "STATE_FILE", tmp_path / "monitor_state.json")
    monkeypatch.setattr(tm, "DATA_CHECKS", [("prices", "Data/raw/prices.csv", "date", 3)])
    monkeypatch.setattr(tm, "TASKS", [])
    monkeypatch.setattr(tm.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "PID\tSTAT\tlaunchd\n"})())
    assert tm.main([]) == 1
    assert "文件缺失" in capsys.readouterr().out


def _make_symbols(tmp_path, rel, rows):
    """造一个带 symbol 列的守猪待兔长表：`rows = [(date, symbol), ...]`。"""
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    body = "date,symbol,score\n" + "".join("%s,%s,1\n" % r for r in rows)
    p.write_text(body, encoding="utf-8")


def _stub_launchctl(monkeypatch):
    monkeypatch.setattr(tm.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": ""})())


def test_shoutu_history_empty_whitelist_skips_stale_alert(tmp_path, monkeypatch):
    """白名单为空 ⇒ **不判停更**（服务端对这些标的本来就没有历史）。

    2026-11-09 实测：8 个美股标的服务端全返回 `data: []` ⇒ 尾行永远停在
    2026-10-14 ⇒ 每天报「停更 26 天」的假告警。
    """
    monkeypatch.setattr(tm, "REPO", tmp_path)
    monkeypatch.setattr(tm, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(tm, "DATA_CHECKS",
                        [("shoutu_history", "Data/raw/sh.csv", "date", 7)])
    monkeypatch.setattr(tm, "SHOUTU_HISTORY_WHITELIST", [])
    monkeypatch.setattr(tm, "TASKS", [])
    _stub_launchctl(monkeypatch)
    _make_symbols(tmp_path, "Data/raw/sh.csv", [("2020-01-01", "CONL")])

    st = tm.collect_status()
    assert st["data"][0]["ok"] is True
    assert not any("shoutu_history" in i for i in st["issues"])


def test_shoutu_history_whitelist_only_counts_listed_symbols(tmp_path, monkeypatch):
    """白名单非空 ⇒ 只看白名单内标的的日期（白名单外的停更不算异常）。"""
    monkeypatch.setattr(tm, "REPO", tmp_path)
    monkeypatch.setattr(tm, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(tm, "DATA_CHECKS",
                        [("shoutu_history", "Data/raw/sh.csv", "date", 7)])
    monkeypatch.setattr(tm, "TASKS", [])
    _stub_launchctl(monkeypatch)
    _make_symbols(tmp_path, "Data/raw/sh.csv",
                  [("2020-01-01", "CONL"), (date.today().isoformat(), "YINN")])

    monkeypatch.setattr(tm, "SHOUTU_HISTORY_WHITELIST", ["YINN"])
    assert tm.collect_status()["data"][0]["ok"] is True

    monkeypatch.setattr(tm, "SHOUTU_HISTORY_WHITELIST", ["CONL"])
    st = tm.collect_status()
    assert st["data"][0]["ok"] is False
    assert any("shoutu_history" in i for i in st["issues"])


def test_missing_task_reported(tmp_path, monkeypatch, capsys):
    """定时任务未注册 → 退出 1 且输出任务名。"""
    monkeypatch.setattr(tm, "REPO", tmp_path)
    monkeypatch.setattr(tm, "STATE_FILE", tmp_path / "monitor_state.json")
    monkeypatch.setattr(tm, "DATA_CHECKS", [])
    monkeypatch.setattr(tm, "TASKS", ["com.fg.daily"])
    monkeypatch.setattr(tm.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "PID\tSTAT\tlaunchd\n"})())
    assert tm.main([]) == 1
    assert "com.fg.daily" in capsys.readouterr().out
