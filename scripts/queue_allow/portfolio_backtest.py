# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/portfolio_backtest.py` ✓。

为什么放行（2026-11-20）：第 12.47 条改了因子权重（波动率族 40.5%→30%），
**策略层回测未重跑** ⇒ 需要拿新权重下的收益/回撤/Sharpe 与旧基线对比 ✓

旧基线：`evolution/experiments/portfolio/portfolio-oos.md`（2026-10-11，旧权重）
  OOS 年化 37.66% / 最大回撤 -26.07% / Sharpe 1.26 / Calmar 1.44

⚠️ 该脚本读 **`Data/features.csv`**（不是现算）⇒ **必须先 `run_pipeline`
   重算 features**，否则跑出来的还是旧权重的结果 ✗
⚠️ 会覆写 `evolution/experiments/portfolio/portfolio-oos.{md,json}` ✗
   —— 覆盖前请确认旧基线已被本次对比记录下来 ✓
"""
