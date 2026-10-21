# -*- coding: utf-8 -*-
"""`scripts/feishu_send.py` 的**已发台账**（WT-46，2026-10-19）。

动机：本机 hook 会在 5s 截断 stdout ✗ ⇒ 只能从日志数「已发」行 ⇒ 数不到就误判
「缺片」⇒ 盲补（当晚 5 次 ✗）。台账落盘后 ⇒ `--sent-status` 一查即可 ✓。
"""
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "feishu_send.py")


def _load():
    spec = importlib.util.spec_from_file_location("feishu_send", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fs = _load()


def test_pkg_of():
    assert fs._pkg_of("sync_1019s-t003.txt") == "sync_1019s"
    assert fs._pkg_of("bootstrap-mac.sh") == ""      # 非分片 ⇒ 无包名
    assert fs._pkg_of("") == ""


def test_ledger_add_then_status(tmp_path, monkeypatch):
    """落台账 ⇒ 状态可读；缺片能被准确报出（不靠 stdout ✓）。"""
    monkeypatch.setattr(fs, "TEXT_DIR", str(tmp_path))
    fs._ledger_add("sync_x-t001.txt", 1, 4)
    fs._ledger_add("sync_x-t002.txt", 2, 4)
    fs._ledger_add("sync_x-t004.txt", 4, 4)

    assert (tmp_path / "sync_x.sent").exists()
    missing = fs.sent_status("sync_x")
    assert missing == [3]                     # 只缺第 3 片 ✓


def test_ledger_status_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "TEXT_DIR", str(tmp_path))
    for i in (1, 2):
        fs._ledger_add("sync_y-t%03d.txt" % i, i, 2)
    assert fs.sent_status("sync_y") == []


def test_ledger_status_without_records(tmp_path, monkeypatch, capsys):
    """无台账 ⇒ 不得假装「已发全」✗；要明确报「一片都未确认」✓。"""
    monkeypatch.setattr(fs, "TEXT_DIR", str(tmp_path))
    missing = fs.sent_status("sync_z")
    assert len(missing) > 100                  # 保守返回大范围 ⇒ 调用方会去查日志 ✓
    assert "无记录" in capsys.readouterr().out


def test_ledger_dedup_same_shard(tmp_path, monkeypatch):
    """同一片重复发送（幂等重发）⇒ 台账多条记录，但状态仍按**序号**去重 ✓。"""
    monkeypatch.setattr(fs, "TEXT_DIR", str(tmp_path))
    fs._ledger_add("sync_w-t001.txt", 1, 2)
    fs._ledger_add("sync_w-t001.txt", 1, 2)   # 重发
    fs._ledger_add("sync_w-t002.txt", 2, 2)
    assert fs.sent_status("sync_w") == []


def test_cli_sent_status_returns_zero(tmp_path, monkeypatch, capsys):
    """CLI `--sent-status` 不碰浏览器，直接返回 0 ✓。"""
    monkeypatch.setattr(fs, "TEXT_DIR", str(tmp_path))
    fs._ledger_add("sync_v-t001.txt", 1, 1)
    monkeypatch.setattr("sys.argv", ["feishu_send.py", "--sent-status", "sync_v"])
    assert fs.main() == 0
    assert "已发" in capsys.readouterr().out
