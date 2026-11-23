# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/vix_factor_check.py` ✓。

为什么放行：只**读** `Data/` 下的 CSV 并打印中间值，不写盘、不改状态 ✓。
用途：定位「vix 源有数据但 features 为空」（2026-11-23）✓
"""
