# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/restart_hermes.py` ✓。

为什么放行（2026-11-24）：`evolve_review.py` 因 Hermes(8642) 超时连续失败 ✗
本脚本只探端口 + 尝试 `launchctl kickstart`，不改仓库文件 ✓
"""
