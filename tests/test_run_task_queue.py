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


def test_auto_clean_triggers_above_threshold(tmp_path, monkeypatch):
    """堆积超阈值 ⇒ 每轮顺手归档 ✓（A 方案：自愈，不靠人记得下发）。"""
    from fg_system.dashboard import sync_health as sh
    moved = []
    monkeypatch.setattr(sh, "_bypass_stats",
                        lambda now: {"count": sh.BACKLOG_WARN + 10})
    monkeypatch.setattr(sh, "archive_backlog",
                        lambda **k: moved.append(1) or {"moved": 5, "dest": "/x"})
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    monkeypatch.setattr(q, "ACTIONS", {})
    q.run_once(commit=False)
    assert moved == [1], "超阈值时必须归档 ✗"


def test_auto_clean_skips_below_threshold(tmp_path, monkeypatch):
    """没超阈值 ⇒ 一个文件都不动 ✓（别每 10s 白扫一遍磁盘）。"""
    from fg_system.dashboard import sync_health as sh
    moved = []
    monkeypatch.setattr(sh, "_bypass_stats", lambda now: {"count": 5})
    monkeypatch.setattr(sh, "archive_backlog",
                        lambda **k: moved.append(1) or {"moved": 0})
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    monkeypatch.setattr(q, "ACTIONS", {})
    q.run_once(commit=False)
    assert moved == []


def test_agent_status_shape():
    """定时器状态必须可读且不抛 ✓（看板据此决定是否显示安装按钮）。"""
    st = q.agent_status()
    assert set(st) >= {"installed", "loaded", "label"}
    assert st["label"] == q.LABEL


def test_install_agent_refuses_off_mac(monkeypatch):
    """非 macOS ⇒ 明确拒绝并给原因 ✓（不能假装成功，否则用户以为装好了）。"""
    monkeypatch.setattr(q.sys, "platform", "win32")
    r = q.install_agent()
    assert r["ok"] is False and "macOS" in r["reason"]


def test_done_task_not_rerun(tmp_path, monkeypatch):
    """已有 result 且 status 非 pending ⇒ 不再执行 ✓（幂等，launchd 每 10s 会重复扫）。"""
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    hits = []
    monkeypatch.setattr(q, "ACTIONS", {"demo": lambda p: hits.append(1) or {"ok": True}})
    _put(str(tmp_path), "t4", "demo")
    q.run_once(commit=False)
    q.run_once(commit=False)
    assert len(hits) == 1, "已完成的任务被重复执行了 ✗"


# ------------------------------------------------ MT-87：清理某包的残留分片

def test_clean_sync_partial_removes_only_that_package(tmp_path, monkeypatch):
    """只删**指定包**的分片 ✓ —— 别把其它包、`.done` 一起删了 ✗。"""
    from fg_system.dashboard import sync_health
    monkeypatch.setattr(sync_health, "SHARD_IN", str(tmp_path))
    for n in ("sync_1028w_1.md", "sync_1028w_2.md",
              "sync_1028x_1.md", "sync_1028w_1.md.done"):
        (tmp_path / n).write_text("x", encoding="utf-8")
    r = q._act_clean_sync_partial({"pkg": "sync_1028w"})
    assert r["ok"] is True and r["count"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "sync_1028w_1.md.done", "sync_1028x_1.md"]


def test_git_commit_warns_when_push_fails(monkeypatch, capsys):
    """推送失败必须**留痕** ✓。

    原来 `except: pass` 把 commit/push 的一切失败吞掉 ✗ ⇒ 结果文件只留在 Mac 本地，
    Windows 端永远看不到任务结果 ✗（2026-10-28 实测：
    `t-…-clean_sync_partial.result.json` 至今没进 gitee ✗）。
    """
    class _R:
        def __init__(self, rc, err=""):
            self.returncode = rc
            self.stderr = err

    class _SP:
        SubprocessError = q.subprocess.SubprocessError

        @staticmethod
        def run(cmd, **kw):
            return _R(0) if cmd[1] in ("add", "commit") else _R(1, "denied")

    monkeypatch.setattr(q, "subprocess", _SP)
    q._git_commit([("t1", "done")])
    assert "推送失败" in capsys.readouterr().out


def test_clean_sync_partial_rejects_bad_pkg():
    """包名非法必须报错 ✓ —— 不许借 `..` / `/` / `*` 越出分片目录 ✗。"""
    for bad in ("", "..", "a/b", "a b", "*"):
        r = q._act_clean_sync_partial({"pkg": bad})
        assert r["ok"] is False, "非法包名 %r 被放行了 ✗" % bad
