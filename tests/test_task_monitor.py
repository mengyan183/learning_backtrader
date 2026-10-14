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
