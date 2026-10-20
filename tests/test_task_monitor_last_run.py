# -*- coding: utf-8 -*-
"""task_monitor._task_last_run：候选日志取「最新 mtime」的契约测试。

背景（2026-10-20）：部分脚本把输出重定向到**自写日志**（如 logs/auto-update.log），
而 plist 的 StandardOutPath（*.out.log）因此永远 0 字节 ⇒ 只看 .out.log 会把
「最近运行时间」读成很久以前，看板任务页于是显示「最新执行时间差 3 天以上」
（实测 fg-auto-update 停在 10-13、shoutu-history 停在 10-15，而任务每天在跑）。
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import task_monitor as tm


def _touch(p, mtime):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x\n", encoding="utf-8")
    os.utime(p, (mtime, mtime))


def test_last_run_picks_newest_among_candidates(tmp_path, monkeypatch):
    """候选里 .out.log 是旧的、自写日志是新的 ⇒ 必须取新的那个（本次修复点）。"""
    monkeypatch.setattr(tm, "REPO", tmp_path)
    old = time.mktime(time.strptime("2026-10-13 02:00", "%Y-%m-%d %H:%M"))
    new = time.mktime(time.strptime("2026-10-20 02:00", "%Y-%m-%d %H:%M"))
    _touch(tmp_path / "logs" / "auto-update.out.log", old)
    _touch(tmp_path / "logs" / "auto-update.log", new)
    monkeypatch.setitem(tm.TASK_LOG, "com.xingguo.fg-auto-update",
                        ["logs/auto-update.log", "logs/auto-update.out.log"])

    ts, fp = tm._task_last_run("com.xingguo.fg-auto-update")
    assert ts == "2026-10-20 02:00"
    assert fp is not None and fp.name == "auto-update.log"


def test_last_run_falls_back_when_first_candidate_missing(tmp_path, monkeypatch):
    """首选缺失时回落到候选，不能因为没有首选就返回 None。"""
    monkeypatch.setattr(tm, "REPO", tmp_path)
    mt = time.mktime(time.strptime("2026-10-15 06:35", "%Y-%m-%d %H:%M"))
    _touch(tmp_path / "logs" / "x.out.log", mt)
    monkeypatch.setitem(tm.TASK_LOG, "com.example.t", ["logs/x.log", "logs/x.out.log"])

    ts, fp = tm._task_last_run("com.example.t")
    assert ts == "2026-10-15 06:35"
    assert fp.name == "x.out.log"


def test_last_run_returns_none_when_no_log(tmp_path, monkeypatch):
    """候选全不存在 ⇒ (None, None)，不抛异常。"""
    monkeypatch.setattr(tm, "REPO", tmp_path)
    monkeypatch.setitem(tm.TASK_LOG, "com.example.none", ["logs/nope.log"])
    assert tm._task_last_run("com.example.none") == (None, None)


def test_last_run_unknown_label_is_safe():
    """未登记 label ⇒ (None, None)，不抛异常（页面显示「—」而不是崩）。"""
    assert tm._task_last_run("com.example.unknown") == (None, None)


def test_every_monitored_task_declares_a_candidate():
    """每个受监控任务都必须有候选日志，否则任务页永远只有「—」。"""
    for label in tm.TASKS:
        assert tm.TASK_LOG.get(label), label
