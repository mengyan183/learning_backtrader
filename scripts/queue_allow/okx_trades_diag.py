# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/okx_trades_diag.py` ✓。

为什么放行（2026-11-27）：需 Mac 上的 `Data/trades.csv` / `positions.csv` /
`accounts.csv`（均未跟踪）✗ 且要实测 ClashX 代理到 OKX 的连通性 ✓
本脚本**只读**、只做 HTTP 探测，不写任何文件 ✓
"""
