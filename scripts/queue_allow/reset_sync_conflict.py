# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/reset_sync_conflict.py` ✓。

为什么放行（2026-11-25）：`fg_sync_ingest` 先解包写工作区、再 commit ✗
commit 被纪律门禁拦下后，文件留在工作区未提交 ⇒ 下次同步报冲突卡死 ✗
而 `run_git` 白名单没有 `checkout` ⇒ 只能靠本脚本 ✓
本脚本**只回滚显式列出的文件**、默认 dry-run、限定 6 个安全前缀 ✓
"""
