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


def test_bypass_stuck_when_plugin_layer_has_files(tmp_path, monkeypatch):
    """**核心守卫**：文件已到插件层、分片目录却空 ⇒ bypass 没被调用（本次事故形态）✓。"""
    byp, shard = _fake(tmp_path, monkeypatch)
    (byp / "msg1.md").write_text("###FG:sync_x:1/2###aGk=###FG:end###", encoding="utf-8")
    r = sh.collect()
    assert r["verdict"] == "bypass_stuck", r["hint"]
    assert r["bypass_in"]["count"] == 1


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


def test_ok_when_recent_done_marker(tmp_path, monkeypatch):
    """有 `.done` 且新鲜 ⇒ ok（别把正常状态报成异常）✓。"""
    byp, shard = _fake(tmp_path, monkeypatch)
    (shard / "sync_demo.done").write_text("abc", encoding="utf-8")
    r = sh.collect()
    assert r["verdict"] == "ok", r["hint"]
    assert r["last_ingest"]["name"] == "sync_demo.done"
