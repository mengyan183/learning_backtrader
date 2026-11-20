# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/fetch_trades_futu.py` ✓。

为什么放行（2026-11-20）：清仓后想**立刻**看到券商成交流水，而不是等
次日 05:30 的每日链 ✗ —— 该脚本只调富途 `history_deal_list_query`，
写 `Data/trade_log_futu.csv`（**不覆盖**手工 `trade_log.csv` ✓）。

⚠️ 只读券商 + 只写仓库内文件 ✓，不改系统、不装包 ✗。
"""
