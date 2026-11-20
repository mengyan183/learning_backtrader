# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/putcall_ffill_compare.py` ✓。

为什么放行：第 12.58 条的 ffill 限幅 A/B（只读，`pipeline.run(write=False)`）✓。
⚠️ 只读或只写仓库内文件 ✓，不改系统、不装包 ✗。
"""
