# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/price_crosscheck.py` ✓。

为什么放行（2026-11-24）：只读 `prices.csv` 与 `shoutu_history.csv`，
比对同 (date, symbol) 的价格偏差，不写盘 ✓
"""
