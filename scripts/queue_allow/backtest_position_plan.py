# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/backtest_position_plan.py` ✓。

为什么放行（2026-11-24）：建仓规则回测只在 Mac 上能跑（依赖
`Data/raw/shoutu_history.csv` + `shoutu_fng.csv`，两者都不在 git 里）✗
⇒ 远程跑一次验证「数据来源构成」与 `--json` 的 `sources` 字段 ✓
本脚本只读数据并打印，不写仓库文件（`--json` 需显式指定路径，默认不写）✓
"""
