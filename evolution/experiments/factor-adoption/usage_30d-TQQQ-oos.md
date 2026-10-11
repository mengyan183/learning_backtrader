# 回测裁判：usage_30d（negative）→ TQQQ OOS

- 生成：2026-10-11 16:13 · scripts/factor_backtest_probe.py
- 口径：因子 756 日滚动分位 → 仓位 0.2~1.0 线性映射（无参数先验）；T 信号 shift(1) → T+1 生效；换仓成本 0.0008/单位换手；OOS 起 2024-10-01（191 日）
- 判定：**FAIL（OOS 未优于 B0，不采纳候选入生产）**

| 指标 | 策略（OOS） | B0 买入持有 | 样本内 |
|---|---|---|---|
| OOS 年化 | 47.20% | 67.18% | nan% |
| 最大回撤 | -24.0% | -33.8% | nan% |
| Sharpe | 1.30 | 1.10 | nan |
| Calmar | 1.96 | 1.99 | nan |

> 由 scripts/factor_backtest_probe.py 生成 · 确定性判定，无 LLM 判决；
> 仅作 C-3 审批证据，不直接改动生产。