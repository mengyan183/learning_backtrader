# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/fetch_shoutu_api.py` ✓。

为什么放行（2026-11-20）：`shoutu_fng.csv` 停在 **2026-10-14**（滞后 36 天），
而简报的「守猪待兔系数」是减仓/加仓判断的输入 ✗ —— 数据停更等于信号失效 ✗。
需要远程跑一次 `--dry-run` 看 API 到底报什么（额度 / key / 网络）✓。

⚠️ 只调 partner API 读数据 ✓；**必须用 `--dry-run`**（不带会覆盖当日快照 ✗）。
"""
