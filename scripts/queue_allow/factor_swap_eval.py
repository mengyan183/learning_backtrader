# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/factor_swap_eval.py` ✓。

为什么放行（2026-11-20，第 12.55 条）：评估「替换 `term`」的候选因子
（`credit_spread` / `erp`），量三件事 —— 数据可用性、与 `vix` 的正交性、
单因子 IC ✓

⚠️ 该脚本 `pipeline.run` **不写文件**（`load_wide()` + 纯计算）✓
⚠️ `credit_spread` 的真实 CSV（`fred_baa10y_avail.csv`）**只在 Mac**，
   本地跑会报「数据不存在」⇒ 必须在 Mac 上跑才有完整结果 ✓
"""
