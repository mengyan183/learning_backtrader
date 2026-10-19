"""MT-40：watcher 兜底入库成功后必须发回执（与失败分支对称）。

背景（2026-10-19 实测）：`sync_1019o` / `sync_1019p` 由 watcher 兜底路径
**入库成功**（写 `.done` / 清分片 / 提交 `c2f34f0`），但群里**没有任何回执**
⇒ 对端只能人工来问「是不是没收到」。

根因：bypass 主路径发完「已收齐 N 片」后中断（`send-fail.log` 无记录 ⇒
根本没走到发送），watcher 的 success 分支只写标记 + 清分片、**不发回执**。

纪律（同 `21ddbab`）：成功与失败都不能静默。
"""
import importlib.util
import os
import time
import types

import pytest

WATCHER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills", "fg-sync", "scripts", "fg-sync-watcher.py",
)

# stub 的 git 输出：让回执带 sha / 文件清单 / blob hash（与真实回执同形）
_GIT_OUT = {
    "rev-parse": "abc1234",
    "log": "fg-sync: sync_9999z 公司端同步 2026-10-19",
    "show": "docs/windows-tasks.md\nscripts/evolve_verify.py",
    "hash-object": "0f2ecc5dba0dcebd1234567890abcdef12345678",
}


def _load_watcher():
    spec = importlib.util.spec_from_file_location("fg_watcher_under_test", WATCHER_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _make_pkg(tmp_path, pkg="sync_9999z", n=2, age=600):
    """造一个「已收齐且滞留 ≥60s」的包（bypass 已不会再认领 ⇒ 走 watcher）。"""
    for i in range(1, n + 1):
        fp = tmp_path / f"{pkg}_{i}.md"
        fp.write_text(f"###FG:{pkg}:{i}/{n}###QUJD###FG:end###", encoding="utf-8")
        old = time.time() - age
        os.utime(fp, (old, old))
    return pkg


def _patch(monkeypatch, w, tmp_path, rc, out):
    """把 watcher 的 IN_DIR / bypass / subprocess.run 全部替换成可观测桩。"""
    monkeypatch.setattr(w, "IN_DIR", str(tmp_path))
    sent = []

    def _fake_send(text, chat_id):
        sent.append((text, chat_id))
        return "ok"

    fake_bypass = types.SimpleNamespace(send_feishu=_fake_send)
    monkeypatch.setattr(w, "_load_bypass", lambda: fake_bypass)

    def _fake_run(cmd, *a, **k):
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        if cmd and cmd[0] == "git":          # 回执用的 git 只读查询
            for key, val in _GIT_OUT.items():
                if key in cmd:
                    _R.stdout = val
                    break
        else:                                 # 入库命令本身
            _R.returncode = rc
            _R.stdout = out
        return _R()

    monkeypatch.setattr(w.subprocess, "run", _fake_run)
    return sent


def test_success_branch_sends_receipt(tmp_path, monkeypatch):
    """成功分支必须发一条回执，且含包名 / 提交 sha / 落地文件与 blob hash。"""
    w = _load_watcher()
    _make_pkg(tmp_path)
    sent = _patch(monkeypatch, w, tmp_path, rc=0, out="✅ 入库完成")

    assert w.main() == 0
    assert len(sent) == 1, "success 分支必须发回执（此前静默 ✗）"
    text, chat = sent[0]
    assert "9999z" in text and "已入库并推送" in text
    assert "abc1234" in text, "回执应带提交 sha，便于对端核对"
    assert "docs/windows-tasks.md" in text, "回执应列落地文件"
    assert "0f2ecc5dba0d" in text, "回执应带 blob hash，可与包内 index 行核对"
    assert chat == w.CHAT_ID


def test_success_branch_cleans_up_as_before(tmp_path, monkeypatch):
    """补回执不得改变既有清理语义：写 .done、清分片、清 sync_in.md。"""
    w = _load_watcher()
    _make_pkg(tmp_path)
    _patch(monkeypatch, w, tmp_path, rc=0, out="✅ 入库完成")

    assert w.main() == 0
    assert (tmp_path / "sync_9999z.done").exists()
    assert not (tmp_path / "sync_9999z_1.md").exists()
    assert not (tmp_path / "sync_9999z_2.md").exists()


def test_failure_branch_keeps_shards_and_reports(tmp_path, monkeypatch):
    """失败分支行为不变：发 ⛔ 回执并保留分片（可重发重试）。"""
    w = _load_watcher()
    _make_pkg(tmp_path, pkg="sync_9999y")
    sent = _patch(monkeypatch, w, tmp_path, rc=2, out="❌ 校验失败")

    assert w.main() == 0
    assert len(sent) == 1 and "⛔" in sent[0][0]
    assert (tmp_path / "sync_9999y_1.md").exists(), "失败必须保留分片"
    assert not (tmp_path / "sync_9999y.done").exists()


def test_no_new_commit_receipt_says_so(tmp_path, monkeypatch):
    """「无可提交」也算成功，但回执要把口径写清楚（不谎报提交 sha）。"""
    w = _load_watcher()
    _make_pkg(tmp_path, pkg="sync_9999x")
    sent = _patch(monkeypatch, w, tmp_path, rc=1,
                  out="⚠️ commit 失败（可能无变更可提交）")

    w.main()
    assert len(sent) == 1
    assert "无新提交" in sent[0][0]
    assert "abc1234" not in sent[0][0]


def test_incomplete_package_stays_silent(tmp_path, monkeypatch):
    """未收齐仍在静默窗口内（<10 分钟）⇒ 不发任何消息，避免刷屏。"""
    w = _load_watcher()
    fp = tmp_path / "sync_9999w_1.md"
    fp.write_text("###FG:sync_9999w:1/3###QUJD###FG:end###", encoding="utf-8")
    sent = _patch(monkeypatch, w, tmp_path, rc=0, out="")

    assert w.main() == 0
    assert sent == []
