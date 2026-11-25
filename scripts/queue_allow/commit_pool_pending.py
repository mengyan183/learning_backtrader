# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/commit_pool_pending.py` ✓。

为什么放行（2026-11-25）：`fix_1125e` 的 commit 被 §8 门禁拦下后，
文件留在 Mac 工作区未提交 ✗ 再发同名包 patch 打不上（内容已存在）⇒ 被跳过 ✗
⇒ 死锁。本脚本把「3 个脏文件 + 一个 docs 变更」放进**同一个 commit** ✓
安全：文件列表显式给出、限定 6 个安全前缀、提交前自检门禁条件、默认 dry-run ✓
"""
