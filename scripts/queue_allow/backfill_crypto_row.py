# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/backfill_crypto_row.py` ✓。

为什么放行（2026-11-27）：需 Mac 上的 `Data/positions.csv` / `accounts.csv`
（均未跟踪）✗ 且 11-26 的 crypto 行已被静默删除、代理又对 OKX 不通 ✓
安全：默认 dry-run、幂等（目标日已有 crypto 行则跳过）、
      note 里强制标注「推断值」、只动 crypto 行不碰 stock ✓
"""
