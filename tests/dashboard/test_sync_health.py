# -*- coding: utf-8 -*-
"""同步链路体检的守卫（`fg_system/dashboard/sync_health.py`）。

【为什么需要 —— 2026-10-28 事故】`sync_1028a` 发出 32 片，Windows 侧
`--sent-status` 显示 **32/32 已发** ✓，Mac 侧却 65 条消息全积压在 OpenClaw
pending 队列（worker 未认领）⇒ bypass 没落盘 ⇒ 无回执 ✗。
Windows 只能看到「已发」和「gitee 有无新提交」两头，中间态完全黑箱 ✗。
⇒ 本模块在 Mac 本地读四个观测点，给出「卡在哪一段」的结论 ✓，这里锁住判定分支。
"""
import os
import time

from fg_system.dashboard import sync_health as sh


def _fake(tmp_path, monkeypatch):
    """把四个观测点指到临时目录，返回 (bypass_in, shard_in)。"""
    byp = tmp_path / "fg-sync-bypass-in"
    shard = tmp_path / "fg-sync-in"
    byp.mkdir()
    shard.mkdir()
    monkeypatch.setattr(sh, "OC", str(tmp_path))
    monkeypatch.setattr(sh, "BYPASS_IN", str(byp))
    monkeypatch.setattr(sh, "SHARD_IN", str(shard))
    monkeypatch.setattr(sh, "SEND_FAIL", str(shard / "send-fail.log"))
    monkeypatch.setattr(sh, "GW_LOG", str(tmp_path / "gateway.log"))
    return byp, shard


def test_unknown_when_no_openclaw(tmp_path, monkeypatch):
    """Windows / 未装 OpenClaw ⇒ unknown（不能报成 ok，那会掩盖问题）✓。"""
    monkeypatch.setattr(sh, "OC", str(tmp_path / "nope"))
    r = sh.collect()
    assert r["verdict"] == "unknown"
    assert "OpenClaw" in r["hint"]


def test_bypass_stuck_when_fresh_files_not_consumed(tmp_path, monkeypatch):
    """**核心守卫**：**刚**落盘的文件 + 分片目录空 + 最近没入库 ⇒ bypass 没被调用 ✓。"""
    byp, shard = _fake(tmp_path, monkeypatch)
    (byp / "msg1.md").write_text("###FG:sync_x:1/2###aGk=###FG:end###", encoding="utf-8")
    r = sh.collect()
    assert r["verdict"] == "bypass_stuck", r["hint"]
    assert r["bypass_in"]["count"] == 1


def test_historical_backlog_is_not_stuck(tmp_path, monkeypatch):
    """**回归守卫**（2026-10-28 Mac 实测误报）：插件层**历史堆积** + 最近刚成功入库
    ⇒ 链路是通的，**绝不能**判 bypass_stuck ✗。

    Mac 上该目录消费后从不清理，堆了 3939 个历史文件；第一版判定只看「目录非空」
    ⇒ 恒红 ✗。现在只看**近 15 分钟新落** + 「最近无入库」两个条件同时成立。
    """
    byp, shard = _fake(tmp_path, monkeypatch)
    old = time.time() - 9 * 86400          # 9 天前的历史文件
    for i in range(300):
        p = byp / ("old_%d.md" % i)
        p.write_text("x", encoding="utf-8")
        os.utime(p, (old, old))
    (shard / "sync_demo.done").write_text("abc", encoding="utf-8")   # 刚入库
    r = sh.collect()
    assert r["verdict"] == "ok", r["hint"]
    assert r["bypass_in"]["fresh"] == 0
    # 但堆积本身要给提示（卫生问题，不影响 verdict）✓
    assert r["warning"] and "300" in r["warning"]


def test_fresh_bypass_with_recent_ingest_is_not_stuck(tmp_path, monkeypatch):
    """刚有消息落盘、但**刚刚也成功入库过** ⇒ 链路通，不判 stuck（Mac 本次的实际情况）✓。"""
    byp, shard = _fake(tmp_path, monkeypatch)
    (byp / "msg1.md").write_text("###FG:sync_x:1/2###aGk=###FG:end###", encoding="utf-8")
    (shard / "sync_prev.done").write_text("abc", encoding="utf-8")
    r = sh.collect()
    assert r["verdict"] == "ok", r["hint"]


def test_shards_waiting_lists_missing_numbers(tmp_path, monkeypatch):
    """半收且滞留超阈值 ⇒ 报出**缺哪几片**（补发要按片号，不能只说「不齐」）✓。"""
    byp, shard = _fake(tmp_path, monkeypatch)
    old = time.time() - (sh.STUCK_SEC + 120)
    for seq in (1, 2, 4):                      # 缺第 3 片
        p = shard / ("sync_demo_%d.md" % seq)
        p.write_text("x", encoding="utf-8")
        os.utime(p, (old, old))
    r = sh.collect()
    assert r["verdict"] == "shards_waiting", r["hint"]
    assert r["packages"][0]["missing"] == [3]
    assert r["packages"][0]["total"] == 4


def test_receipt_failed_when_send_fail_log_not_empty(tmp_path, monkeypatch):
    """入库成功但回执发不出去 ⇒ 单独一档（与「没收到」是两回事）✓。"""
    byp, shard = _fake(tmp_path, monkeypatch)
    (shard / "send-fail.log").write_text("boom\n", encoding="utf-8")
    r = sh.collect()
    assert r["verdict"] == "receipt_failed", r["hint"]


def test_runtime_copy_detects_divergence(tmp_path, monkeypatch):
    """仓库版与运行时副本不一致必须报出来 ✓ —— 否则「改了没生效」永远无声 ✗。"""
    repo = tmp_path / "repo.py"
    run = tmp_path / "run.py"
    repo.write_text("v2", encoding="utf-8")
    run.write_text("v2", encoding="utf-8")
    monkeypatch.setattr(sh, "REPO_BYPASS", str(repo))
    monkeypatch.setattr(sh, "RUNTIME_BYPASS", str(run))
    assert sh.runtime_copy_status()["same"] is True

    run.write_text("v1-旧版", encoding="utf-8")     # 副本落后
    st = sh.runtime_copy_status()
    assert st["same"] is False, "副本落后必须判不一致 ✗"

    monkeypatch.setattr(sh, "RUNTIME_BYPASS", str(tmp_path / "nope.py"))
    st = sh.runtime_copy_status()
    assert st["runtime"] is False and st["same"] is None


def test_sync_runtime_copy_overwrites_with_backup(tmp_path, monkeypatch):
    """仓库版覆盖运行时副本：覆盖前必须留备份 ✓，覆盖后必须一致 ✓。"""
    repo = tmp_path / "repo.py"
    run_dir = tmp_path / "workspace"
    run_dir.mkdir()
    run = run_dir / "run.py"
    repo.write_text("v2-新版", encoding="utf-8")
    run.write_text("v1-旧版", encoding="utf-8")
    monkeypatch.setattr(sh, "REPO_BYPASS", str(repo))
    monkeypatch.setattr(sh, "RUNTIME_BYPASS", str(run))

    r = sh.sync_runtime_copy()
    assert r["ok"] is True, r
    assert run.read_text(encoding="utf-8") == "v2-新版"
    assert r["same"] is True
    assert r["backup"] and os.path.isfile(r["backup"]), "覆盖前必须备份旧副本 ✗"
    with open(r["backup"], encoding="utf-8") as f:
        assert f.read() == "v1-旧版"


def test_sync_runtime_copy_noop_without_runtime_dir(tmp_path, monkeypatch):
    """运行时目录不存在（Windows / 未装 OpenClaw）⇒ 报原因，不抛 ✓。"""
    repo = tmp_path / "repo.py"
    repo.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sh, "REPO_BYPASS", str(repo))
    monkeypatch.setattr(sh, "RUNTIME_BYPASS", str(tmp_path / "nope" / "run.py"))
    r = sh.sync_runtime_copy()
    assert r["ok"] is False and r["reason"]


def test_archive_backlog_moves_only_old_files(tmp_path, monkeypatch):
    """清理只挪**够老**的文件，且**目录必须还在**（插件按固定路径写盘 ✗）。"""
    byp, shard = _fake(tmp_path, monkeypatch)
    old = time.time() - 3600
    for i in range(3):
        p = byp / ("old_%d.md" % i)
        p.write_text("x", encoding="utf-8")
        os.utime(p, (old, old))
    fresh = byp / "fresh.md"
    fresh.write_text("y", encoding="utf-8")          # 刚落的，不能挪

    r = sh.archive_backlog()
    assert r["moved"] == 3, r
    assert os.path.isdir(str(byp)), "目录被挪走了 ⇒ 插件后续写盘会失败 ✗"
    assert (byp / "fresh.md").is_file(), "刚落的文件不能挪（可能正在处理）✗"
    assert os.path.isdir(r["dest"])
    assert len(os.listdir(r["dest"])) == 3


def test_archive_backlog_noop_when_dir_missing(tmp_path, monkeypatch):
    """Windows / 未装 OpenClaw ⇒ 不报错，返回原因（页面显示「无需清理」）✓。"""
    monkeypatch.setattr(sh, "BYPASS_IN", str(tmp_path / "nope"))
    r = sh.archive_backlog()
    assert r["moved"] == 0 and r["reason"]


def test_ok_when_recent_done_marker(tmp_path, monkeypatch):
    """有 `.done` 且新鲜 ⇒ ok（别把正常状态报成异常）✓。"""
    byp, shard = _fake(tmp_path, monkeypatch)
    (shard / "sync_demo.done").write_text("abc", encoding="utf-8")
    r = sh.collect()
    assert r["verdict"] == "ok", r["hint"]
    assert r["last_ingest"]["name"] == "sync_demo.done"


def test_archive_backlog_prunes_old_archive_dirs(tmp_path, monkeypatch):
    """归档目录超过 `keep_days` 必须删掉 ✓ —— 只挪不删会无限涨 ✗。

    2026-10-29 用户口径：**历史归档只保留最近 3 天** ✓。
    """
    byp, _ = _fake(tmp_path, monkeypatch)
    old = byp / "archive_1019-0300"
    old.mkdir()
    (old / "a.md").write_text("x", encoding="utf-8")
    fresh = byp / "archive_1029-0300"
    fresh.mkdir()
    (fresh / "b.md").write_text("x", encoding="utf-8")
    msg = byp / "msg.md"
    msg.write_text("x", encoding="utf-8")

    old_ts = time.time() - 10 * 86400          # 10 天前
    os.utime(str(old), (old_ts, old_ts))
    os.utime(str(msg), (old_ts, old_ts))       # 30 分钟前的才会被挪走

    r = sh.archive_backlog(now=time.time(), keep_days=3)

    assert r["moved"] == 1, "超 30 分钟的消息没被归档 ✗"
    assert r["pruned"] == 1, "超 3 天的归档目录没被删 ✗"
    assert not old.exists(), "10 天前的归档还在 ✗"
    assert fresh.exists(), "3 天内的归档被误删了 ✗"


def test_archive_backlog_keeps_all_when_keep_days_zero(tmp_path, monkeypatch):
    """`keep_days=0` ⇒ 只归档不轮转 ✓（留个关掉的口子）。"""
    byp, _ = _fake(tmp_path, monkeypatch)
    old = byp / "archive_1019-0300"
    old.mkdir()
    msg = byp / "msg.md"
    msg.write_text("x", encoding="utf-8")
    old_ts = time.time() - 10 * 86400
    os.utime(str(old), (old_ts, old_ts))
    os.utime(str(msg), (old_ts, old_ts))

    r = sh.archive_backlog(now=time.time(), keep_days=0)

    assert r["pruned"] == 0 and old.exists()
