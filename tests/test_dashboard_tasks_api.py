# -*- coding: utf-8 -*-
"""dashboard 定时任务监控 API 测试（T-2026-10-14）。

覆盖：GET /api/tasks 结构与字段完整性；POST /api/tasks/retry 白名单校验
（非法 target 400）；互斥锁生效（存在存活进程时 409）。
不触发真实抓取脚本（不测 Popen 实际执行）。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def client():
    from fg_system.dashboard import server
    h = server.make_handler(lambda: {"date": "2026-10-14", "fg_index": 50.0},
                            prices_path=None, auth=None)
    return h.test_client()


def test_tasks_api_shape(client):
    r = client.get("/api/tasks")
    assert r.status_code == 200
    d = r.get_json()
    assert set(d) >= {"checked_at", "all_ok", "issues", "data", "tasks"}
    assert len(d["data"]) >= 10          # 12 类数据
    assert len(d["tasks"]) >= 7          # 7 个 launchd 任务
    for row in d["data"]:
        assert set(row) >= {"name", "last", "lag", "tol", "ok"}
    for row in d["tasks"]:
        assert set(row) >= {"label", "registered", "ok"}


def test_retry_unknown_target_rejected(client):
    r = client.post("/api/tasks/retry", json={"target": "nonsense"})
    assert r.status_code == 400


def test_retry_lock_conflict_409(client):
    from fg_system import config as cfg
    lock_p = os.path.join(cfg.DATA_DIR, "task_retry.lock")
    os.makedirs(os.path.dirname(lock_p), exist_ok=True)
    with open(lock_p, "w", encoding="utf-8") as f:
        # 用当前进程 PID —— os.kill(pid, 0) 会成功 ⇒ 视为"已有重试在跑"
        json.dump({"target": "fedwatch", "pid": os.getpid()}, f)
    try:
        r = client.post("/api/tasks/retry", json={"target": "fedwatch"})
        assert r.status_code == 409
    finally:
        if os.path.exists(lock_p):
            os.remove(lock_p)
