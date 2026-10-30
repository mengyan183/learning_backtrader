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


def test_broken_task_file_is_quarantined(tmp_path, monkeypatch, capsys):
    """写坏的任务 json 必须**隔离** ✓ —— 否则每轮静默跳过、任务永久饿死 ✗。

    2026-10-29 实测：一个 json 末尾粘了 patch 头（`diff --git ...`）✗
    ⇒ `json.load` 抛 ValueError ⇒ 被 `except: continue` 吞掉 ✗
    ⇒ 日志里**完全没有这条任务**，也永远不会执行 ✗。
    """
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    bad = tmp_path / "t-20261029-1936-demo.json"
    bad.write_text('{"id": "x", "action": "demo"}\ndiff --git a/x b/x\n',
                   encoding="utf-8")

    assert q._load_pending() == []
    assert not bad.exists(), "坏文件没被隔离 ⇒ 下轮还会空转 ✗"
    assert (tmp_path / "t-20261029-1936-demo.json.broken").exists()
    assert "已隔离为 .broken" in capsys.readouterr().out


def test_pending_is_sorted_by_id(tmp_path, monkeypatch):
    """待执行任务按 **id** 升序（先进先出）✓。

    id 是 `t-YYYYmmdd-HHMMSS-<action>`，字典序恒等于时间序 ✓；
    而 `created_at` 可能缺失（缺失会排最前，抢跑 ✗）。
    """
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    for tid, created in (("t-20261029-2000-demo", ""),
                         ("t-20261029-1930-demo", "2026-10-29T19:30:00"),
                         ("t-20261029-1945-demo", "2026-10-29T19:45:00")):
        (tmp_path / (tid + ".json")).write_text(
            json.dumps({"id": tid, "action": "demo", "params": {},
                        "status": "pending", "created_at": created}),
            encoding="utf-8")

    assert [s["id"] for s in q._load_pending()] == [
        "t-20261029-1930-demo", "t-20261029-1945-demo", "t-20261029-2000-demo"]


def test_prune_queue_keeps_recent_and_never_drops_pending(tmp_path, monkeypatch):
    """只留最近 10 个**已完成**任务 ✓。

    🔴 未完成的任务（没有 `.result.json`）**一律不删** ✗ —— 删了就永远不会执行 ✗。
    """
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    for i in range(13):
        tid = "t-202601%02d-0000-demo" % i
        (tmp_path / (tid + ".json")).write_text("{}", encoding="utf-8")
        (tmp_path / (tid + ".result.json")).write_text("{}", encoding="utf-8")
    pend = "t-20251201-0000-pending"
    (tmp_path / (pend + ".json")).write_text("{}", encoding="utf-8")

    dropped = q._prune_queue(keep=10)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert (pend + ".json") in left, "未完成的任务被删了 ✗"
    assert len([n for n in left if n.endswith(".result.json")]) == 9, \
        "应留 9 个已完成（10 - 1 个未完成）+ 1 个未完成 = 10 个任务 ✗"
    assert len(dropped) == 8, "13 - 9 = 4 个任务 × 2 文件 = 8 ✗（实际 %d）" % len(dropped)


def test_futu_preflight_is_registered():
    """`futu_preflight` 必须在白名单里 ✓（下发方可调用）。"""
    assert "futu_preflight" in q.ACTIONS
    assert callable(q.ACTIONS["futu_preflight"])


def test_fetch_shoutu_history_is_registered():
    """`fetch_shoutu_history` 必须在白名单里 ✓ —— 回测依赖它的产物 ✗。"""
    assert "fetch_shoutu_history" in q.ACTIONS
    assert callable(q.ACTIONS["fetch_shoutu_history"])


def test_backtest_plan_is_registered():
    """`backtest_plan` 必须在白名单里 ✓（shoutu_fng.csv 只在 Mac 本地 ✗）。"""
    assert "backtest_plan" in q.ACTIONS
    assert callable(q.ACTIONS["backtest_plan"])


def test_key_diag_never_leaks_plaintext(tmp_path, monkeypatch):
    """`key_diag` **只回前缀与长度** ✓ —— 绝不回明文 ✗（结果会进 git ✗）。"""
    monkeypatch.setattr(q.os.path, "expanduser", lambda p: str(tmp_path))
    (tmp_path / ".credentials.yaml").write_text(
        "nvidia: nvapi-ABCDEFGHIJKLMNOP\n"
        "deepseek: sk-1234567890abcdefghij\n", encoding="utf-8")

    r = q._act_key_diag({"dir": str(tmp_path)})

    assert r["ok"] is True
    hits = r["result"]["hits"]
    kinds = {h["kind"] for h in hits}
    assert kinds == {"nvapi", "sk"}, hits
    blob = json.dumps(r, ensure_ascii=False)
    assert "ABCDEFGHIJKLMNOP" not in blob, "把 NVIDIA key 明文回传了 ✗"
    assert "1234567890abcdefghij" not in blob, "把 DeepSeek key 明文回传了 ✗"
    assert "nvapi-ABCD…" in blob, "前缀也没回（10 字符 + 省略号）"


def test_key_diag_missing_dir(tmp_path):
    """目录不存在 ⇒ 明确失败 ✓（别静默返回空）。"""
    assert q._act_key_diag({"dir": str(tmp_path / "nope")})["ok"] is False


def test_evolution_registries_are_committed():
    """`evolve_*` 改写的登记表必须纳入提交 ✓。

    2026-10-30 实测：`sync_1028dn` 因 Mac 上 `evolution/hypotheses.md`
    **有未提交修改** ⇒ 入库中止（冲突不覆盖）✗。
    根因是队列只提交 `docs/task-queue/`，而每日链的 `evolve_*` 会改写登记表 ✗。
    """
    assert "evolution/hypotheses.md" in q.TASK_OUTPUT_FILES
    assert "evolution/factors.md" in q.TASK_OUTPUT_FILES
    for f in q.TASK_OUTPUT_FILES:
        assert not f.startswith("/") and ".." not in f


def test_task_output_dirs_are_explicit_allowlist():
    """任务产物目录必须是**显式白名单** ✓ —— 绝不能用 `git add -A` ✗。

    2026-10-30 实测教训：`factor_backtest_probe --json evolution/...` 写的
    裁判产物没进 git ✗ ⇒ Windows 端只看到被 `output[-2000:]` 截断的 stdout ✗。
    """
    assert "evolution/experiments/factor-adoption" in q.TASK_OUTPUT_DIRS
    for d in q.TASK_OUTPUT_DIRS:
        assert isinstance(d, str) and d and not d.startswith("-")
        assert ".." not in d, "白名单里不能出现上级目录 ✗"


def test_fetch_pe_ratio_is_registered():
    """`fetch_pe_ratio` 必须在白名单里 ✓ —— C2 的 PE 源只能从 Mac 抓 ✗。"""
    assert "fetch_pe_ratio" in q.ACTIONS
    assert callable(q.ACTIONS["fetch_pe_ratio"])


def test_c1_backtest_is_registered():
    """`c1_backtest` 必须在白名单里 ✓ —— 回测裁判要在 Mac 跑（数据在本地 ✗）。"""
    assert "c1_backtest" in q.ACTIONS
    assert callable(q.ACTIONS["c1_backtest"])


def test_run_pipeline_is_registered():
    """`run_pipeline` 必须在白名单里 ✓（features 尾行缺因子时要能重算）。"""
    assert "run_pipeline" in q.ACTIONS
    assert callable(q.ACTIONS["run_pipeline"])


def test_factor_diag_is_registered():
    """`factor_diag` 必须在白名单里 ✓ —— VIX/TERM 为什么缺只能上 Mac 查 ✗。"""
    assert "factor_diag" in q.ACTIONS
    assert callable(q.ACTIONS["factor_diag"])


def test_net_probe_is_registered():
    """`net_probe` 必须在白名单里 ✓ —— 诊断代理只能从 Mac 本地探 ✗。"""
    assert "net_probe" in q.ACTIONS
    assert callable(q.ACTIONS["net_probe"])


def test_eval_baa10y_is_registered():
    """`eval_baa10y` 必须在白名单里 ✓（信用利差数据只在 Mac 本地 ✗）。"""
    assert "eval_baa10y" in q.ACTIONS
    assert callable(q.ACTIONS["eval_baa10y"])


def test_run_invest_research_is_registered():
    """`run_invest_research` 必须在白名单里 ✓（今天就能验证简报链路 ✗ 别干等明天）。"""
    assert "run_invest_research" in q.ACTIONS
    assert callable(q.ACTIONS["run_invest_research"])


def test_collect_reinstall_writes_back_result(tmp_path, monkeypatch, capsys):
    """延迟重装的结果必须**回写进任务结果** ✓。

    2026-10-29：`install_daily_plist` 对队列作业只能延迟 8 秒重装（当场 bootout
    会把自己杀掉 ✗）⇒ 它返回的 `ok:true` 只代表**拷贝成功** ✗，重装成没成无人回收 ✗。
    """
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    tid = "t-1"
    (tmp_path / (tid + ".result.json")).write_text(json.dumps({
        "id": tid, "action": "install_daily_plist",
        "status": "done", "output": "{}"}), encoding="utf-8")
    (tmp_path / (tid + ".reinstall.json")).write_text(json.dumps({
        "ok": True, "rc": 0, "at": "2026-10-29T14:00:00"}), encoding="utf-8")

    changed = q._collect_reinstall()

    assert changed == [tid]
    res = json.loads((tmp_path / (tid + ".result.json")).read_text(encoding="utf-8"))
    assert res["reinstall"]["ok"] is True and res["reinstall"]["rc"] == 0
    assert not (tmp_path / (tid + ".reinstall.json")).exists(), \
        "标记没删 ⇒ 下一轮会重复回写 ✗"
    assert "重装成功" in capsys.readouterr().out


def test_collect_reinstall_reports_failure(tmp_path, monkeypatch, capsys):
    """重装失败也必须**明确回写** ✓ —— 否则队列 agent 死了都没人知道 ✗。"""
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    tid = "t-2"
    (tmp_path / (tid + ".result.json")).write_text(json.dumps({
        "id": tid, "action": "install_daily_plist", "status": "done"}),
        encoding="utf-8")
    (tmp_path / (tid + ".reinstall.json")).write_text(json.dumps({
        "ok": False, "rc": 5, "at": "2026-10-29T14:00:00"}), encoding="utf-8")

    q._collect_reinstall()

    res = json.loads((tmp_path / (tid + ".result.json")).read_text(encoding="utf-8"))
    assert res["reinstall"]["ok"] is False
    out = capsys.readouterr().out
    assert "失败" in out and "rc=5" in out


def test_collect_reinstall_ignores_missing_result(tmp_path, monkeypatch):
    """结果文件不在时不能崩 ✓（标记仍要清掉，别让它永远挡着）。"""
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    (tmp_path / "t-3.reinstall.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8")
    assert q._collect_reinstall() == []
    assert not (tmp_path / "t-3.reinstall.json").exists()


def test_running_marker_roundtrip(tmp_path, monkeypatch):
    """「执行中」旁路标记的写/删 ✓ —— 不回写任务 json（崩溃后仍能重试）✗。"""
    monkeypatch.setattr(q, "QUEUE", str(tmp_path))
    q._mark_running("t-1")
    assert (tmp_path / "t-1.running").exists()
    q._clear_running("t-1")
    assert not (tmp_path / "t-1.running").exists()
    q._clear_running("t-1")                 # 重复删不报错 ✓


def test_install_daily_plist_is_registered():
    """`install_daily_plist` 必须在白名单里 ✓（plist 只改仓库副本不生效 ✗）。"""
    assert "install_daily_plist" in q.ACTIONS
    assert callable(q.ACTIONS["install_daily_plist"])


def test_try_push_pending_is_silent_without_upstream(monkeypatch, capsys):
    """没有上游 / 无待推提交 ⇒ **静默** ✓（launchd 每 10s 一轮，不能刷屏 ✗）。"""
    class _R:
        returncode = 1
        stdout = ""
        stderr = ""

    class _SP:
        SubprocessError = q.subprocess.SubprocessError

        @staticmethod
        def run(cmd, **kw):
            return _R()

    monkeypatch.setattr(q, "subprocess", _SP)
    monkeypatch.setattr(q, "_PUSH_RETRY", {"ts": 0.0})
    q._try_push_pending(interval=0)
    assert capsys.readouterr().out == ""


def test_try_push_pending_pushes_when_ahead(monkeypatch, capsys):
    """有未推送提交就补推 ✓ —— 上次推送失败后自愈 ✓。"""
    calls = []

    class _R:
        def __init__(self, rc, out=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = ""

    class _SP:
        SubprocessError = q.subprocess.SubprocessError

        @staticmethod
        def run(cmd, **kw):
            calls.append(cmd)
            return _R(0, "2\n") if "rev-list" in cmd else _R(0)

    monkeypatch.setattr(q, "subprocess", _SP)
    monkeypatch.setattr(q, "_PUSH_RETRY", {"ts": 0.0})
    q._try_push_pending(interval=0)
    assert any("push" in c for c in calls), "有 2 个待推提交却没推 ✗"
    assert "补推成功" in capsys.readouterr().out


def test_tail_logs_include_evolve_verify():
    """`evolve_verify` 日志必须在 tail 白名单里 ✓ —— 否则明天没法确认 `--quiet` 生效 ✗。"""
    assert "evolve_verify" in q.TAIL_LOGS
    assert q.TAIL_LOGS["evolve_verify"].endswith("evolve_verify.log")


def test_tail_logs_include_invest_stages():
    """简报阶段日志必须在白名单里 ✓ —— 超时被杀时它是唯一线索 ✗。"""
    assert "invest" in q.TAIL_LOGS
    assert q.TAIL_LOGS["invest"].endswith("invest_stages.log")


def test_install_evolve_tasks_reports_failure(monkeypatch):
    """定时器重装：脚本不存在 / 返回非 0 ⇒ `ok=False` ✓（不许静默成功 ✗）。"""
    monkeypatch.setattr(q, "ROOT", "/nonexistent-root")
    assert q._act_install_evolve_tasks({})["ok"] is False


def test_daily_log_tail_reads_only_whitelisted(tmp_path, monkeypatch):
    """`daily_log_tail` 只读**白名单**日志 ✓ —— 任意路径等于远程读文件 ✗。"""
    log = tmp_path / "d.log"
    log.write_text("\n".join("行%d" % i for i in range(100)), encoding="utf-8")
    monkeypatch.setattr(q, "TAIL_LOGS", {"daily": str(log)})
    r = q._act_daily_log_tail({"which": "daily", "lines": 5})
    assert r["ok"] is True and r["lines"] == 5
    assert r["tail"].strip().endswith("行99"), "tail 必须取**最后**几行 ✗"
    # 白名单外的名字一律拒绝（不能借它读任意文件）
    assert q._act_daily_log_tail({"which": "/etc/passwd"})["ok"] is False
    # lines 上限 200（文件只有 100 行 ⇒ 全给）
    assert q._act_daily_log_tail({"which": "daily", "lines": 9999})["lines"] == 100
    # 文件不存在 ⇒ 明确失败
    monkeypatch.setattr(q, "TAIL_LOGS", {"daily": str(tmp_path / "nope.log")})
    assert q._act_daily_log_tail({"which": "daily"})["ok"] is False


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
