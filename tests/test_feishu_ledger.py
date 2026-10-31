# -*- coding: utf-8 -*-
"""`scripts/feishu_send.py` 的台账（2026-10-31）。

失败也落台账 ⇒ 「试过但失败」和「从没试过」能分开 ✓。
"""
import pytest


def test_ledger_records_failures(tmp_path, monkeypatch, capsys):
    """失败也要落台账 ✓ —— 否则「试过但失败」和「从没试过」分不开 ✗。

    2026-10-31 实测：`sync_1028er` 连试 4 次都显示「台账无记录」✗，
    完全看不出是「没发过」还是「发过 4 次都失败」✗ ⇒ 白重试 4 轮 ✗。
    """
    import importlib.util
    import os

    from fg_system import config

    spec = importlib.util.spec_from_file_location(
        "feishu_send",
        os.path.join(config.ROOT, "scripts", "feishu_send.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    monkeypatch.setattr(m, "TEXT_DIR", str(tmp_path))
    monkeypatch.setattr(m, "_pkg_of", lambda n: "demo")

    m._ledger_add("demo-t001.txt", 1, 1, ok=False)
    m._ledger_add("demo-t001.txt", 1, 1, ok=False)

    missing = m.sent_status("demo")
    out = capsys.readouterr().out
    assert "全部失败" in out, "失败没显示 ✗：%s" % out
    assert "×2" in out, "失败次数没统计 ✗：%s" % out
    assert "换个包名" in out, "没给出「换包名」的提示 ✗"
    assert missing, "失败时也要返回待发序号 ✗"


def test_ledger_old_format_still_ok(tmp_path, monkeypatch, capsys):
    """旧台账（**没有第 4 列**）必须仍然算成功 ✓（向后兼容 ✗ 不能一改就全废）。"""
    import importlib.util
    import os

    from fg_system import config

    spec = importlib.util.spec_from_file_location(
        "feishu_send",
        os.path.join(config.ROOT, "scripts", "feishu_send.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    monkeypatch.setattr(m, "TEXT_DIR", str(tmp_path))
    (tmp_path / "old.sent").write_text(
        "1/2\told-t001.txt\t2026-10-31T10:00:00\n", encoding="utf-8")

    m.sent_status("old")
    out = capsys.readouterr().out
    assert "已发 **1/2** 片" in out, out
