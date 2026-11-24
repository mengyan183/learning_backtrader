# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/memory_digest.py` ✓。

为什么放行（2026-11-24）：只**读** `evolution/memory/` 并打印，
不写盘、不改仓库 ✓。用于把「Mac 本地才有」的记忆文件带回到回执里。
"""
