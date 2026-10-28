# -*- coding: utf-8 -*-
"""`scripts/dispatch_task.py` 的包名约束（2026-10-28）。

【背景】任务下发默认 id 形如 `t-20261028-1935-clean_sync_partial` ✗，
若直接拼成包名 `task-t-…` ⇒ 带连字符 ⇒ Mac 端标记正则
`###FG:([A-Za-z0-9_]+):(\\d+)/(\\d+)###` **整包匹配不到** ✗
⇒ 分片被静默忽略、任务永远不执行（与 `pack_one.py` 同款坑 ✗）。
"""
import importlib.util
import os
import re

from fg_system import config

_SPEC = os.path.join(config.ROOT, "scripts", "dispatch_task.py")


def _load():
    spec = importlib.util.spec_from_file_location("dispatch_task", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dt = _load()


def test_pkg_name_is_marker_safe():
    """默认 id（带连字符）生成的包名必须只含 `[A-Za-z0-9_]` ✓。"""
    pkg = dt._pkg_of("t-20261028-1935-clean_sync_partial")
    assert re.fullmatch(r"[A-Za-z0-9_]+", pkg), "包名含非法字符 ⇒ Mac 端认不出分片 ✗"
    assert pkg.startswith("task_")
