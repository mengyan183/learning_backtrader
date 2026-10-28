# -*- coding: utf-8 -*-
"""任务队列执行器守卫（`scripts/run_task_queue.py`）。

【为什么】（2026-10-28 用户拍板）看板上每来一个一次性需求就加一个按钮 ✗ ⇒
改成「Windows 下发 json → Mac 执行白名单 action → 结果回写」✓。
这里锁三件事：**未知 action 不许静默跳过**、**异常必须留痕**、**已完成的别重复跑**。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts"))
import run_task_queue as q  # noqa: E402


def _put(queue, tid, action, status="pending"):
    spec = {"id": tid, "action": action, "params": {}, "status": status,
            "created_at": "2026-10-28T16:00:00"}
    with open(os.path.join(queue, tid + ".json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)


def _result(queue, tid):
    p = os.path.join(queue, tid + ".result.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def test_runs_whitelisted_action(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    calls = []
    monkeypatch.setattr(q, "ACTIONS", {"demo": lambda p: calls.append(p) or {"ok": True}})
    _put(str(tmp_path), "t1", "demo")

    done = q.run_once(commit=False)
    assert done == [("t1", "done")]
    assert calls == [{}], "action 必须真的被调用一次"
    r = _result(str(tmp_path), "t1")
    assert r["status"] == "done" and r["rc"] == 0


def test_unknown_action_fails_loudly(tmp_path, monkeypatch):
    """未知 action **不能静默跳过** ✗ —— 否则下发方以为还在排队。"""
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    monkeypatch.setattr(q, "ACTIONS", {})
    _put(str(tmp_path), "t2", "rm_rf_everything")

    done = q.run_once(commit=False)
    assert done == [("t2", "failed")]
    r = _result(str(tmp_path), "t2")
    assert "未知 action" in r["output"] and r["rc"] != 0


def test_exception_is_recorded(tmp_path, monkeypatch):
    """action 抛异常也要落 result ✓（否则页面永远显示 pending）。"""
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))

    def boom(_p):
        raise RuntimeError("炸了")

    monkeypatch.setattr(q, "ACTIONS", {"demo": boom})
    _put(str(tmp_path), "t3", "demo")
    q.run_once(commit=False)
    r = _result(str(tmp_path), "t3")
    assert r["status"] == "failed" and "炸了" in r["output"]


def test_done_task_not_rerun(tmp_path, monkeypatch):
    """已有 result 且 status 非 pending ⇒ 不再执行 ✓（幂等，launchd 每 10s 会重复扫）。"""
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    hits = []
    monkeypatch.setattr(q, "ACTIONS", {"demo": lambda p: hits.append(1) or {"ok": True}})
    _put(str(tmp_path), "t4", "demo")
    q.run_once(commit=False)
    q.run_once(commit=False)
    assert len(hits) == 1, "已完成的任务被重复执行了 ✗"
