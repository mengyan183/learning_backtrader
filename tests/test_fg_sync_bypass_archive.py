# -*- coding: utf-8 -*-
"""bypass 消费后必须把源消息挪走（2026-10-28 根治）。

【背景】`~/.openclaw/tmp/fg-sync-bypass-in/` 以前**只写不清** ⇒ 19 天堆了 3956 个文件 ✗，
连看板体检都被误判成「bypass 没被调用」（bypass_stuck 恒红 ✗）。
⇒ 消费成功后自动挪进 `archive_<MMDD>/`（**只挪不删**，可回看原始消息 ✓）。
"""
import importlib.util
import os
import time

BYPASS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills", "fg-sync", "scripts", "fg-sync-bypass.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("fg_sync_bypass_mod", BYPASS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_archives_source_inside_bypass_dir(tmp_path, monkeypatch):
    """在约定目录里 ⇒ 挪进 archive_<MMDD>/，原路径消失但**内容还在** ✓。"""
    mod = _load()
    monkeypatch.setattr(mod, "BYPASS_IN", str(tmp_path))
    src = tmp_path / "msg1.md"
    src.write_text("###FG:x:1/1###aGk=###FG:end###", encoding="utf-8")

    mod._archive_source(str(src))

    assert not src.exists(), "源文件必须挪走（否则会无限堆积 ✗）"
    dest = tmp_path / ("archive_" + time.strftime("%m%d"))
    assert (dest / "msg1.md").is_file(), "必须保留内容（只挪不删）✓"


def test_does_not_touch_files_outside_bypass_dir(tmp_path, monkeypatch):
    """不在 `fg-sync-bypass-in/` 里的文件**一个都不能动** ✓（防误挪）。"""
    mod = _load()
    inside = tmp_path / "fg-sync-bypass-in"
    inside.mkdir()
    monkeypatch.setattr(mod, "BYPASS_IN", str(inside))
    outside = tmp_path / "elsewhere.md"
    outside.write_text("x", encoding="utf-8")

    mod._archive_source(str(outside))

    assert outside.is_file(), "目录外的文件被挪走了 ✗"


def test_missing_dir_does_not_raise(tmp_path, monkeypatch):
    """目录不存在（非 Mac / 未装 OpenClaw）⇒ 静默跳过，不能影响主流程 ✓。"""
    mod = _load()
    monkeypatch.setattr(mod, "BYPASS_IN", str(tmp_path / "nope"))
    ghost = tmp_path / "gone.md"
    ghost.write_text("x", encoding="utf-8")
    mod._archive_source(str(ghost))       # 不抛即通过
