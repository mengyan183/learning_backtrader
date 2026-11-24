# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/corr_matrix.py` ✓。

为什么放行（2026-11-24）：第 4E 条（假分散禁令）的 step ③ 需要真实相关性
数据。本脚本只读 `Data/raw/prices.csv` 并打印矩阵，不写盘 ✓
"""
