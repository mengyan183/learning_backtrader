# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/env_check.py` ✓。

为什么放行：每日链报 `No module named 'fg_system'` 时要远程确认
「解释器 / cwd / 包位置 / 数据新鲜度」✗ —— 否则只能让用户手动在 Mac 上跑 ✗。

⚠️ 只读或只写仓库内文件 ✓，不改系统、不装包 ✗。
"""
