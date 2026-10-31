# 回测裁判：ene_pos（negative）→ CRCG OOS

- 生成：2026-10-31 16:22 · scripts/factor_backtest_probe.py
- 口径：因子 756 日滚动分位 → 仓位 0.2~1.0 线性映射（无参数先验）；T 信号 shift(1) → T+1 生效；换仓成本 0.0008/单位换手；OOS 起 2024-10-04（240 日）
- 判定：**PASS（OOS 年化 > B0 且回撤不劣化）**

| 指标 | 策略（OOS） | B0 买入持有 | 样本内 |
|---|---|---|---|
| OOS 年化 | -33.92% | -73.73% | nan% |
| 最大回撤 | -58.4% | -87.1% | nan% |
| Sharpe | -0.35 | -0.38 | nan |
| Calmar | -0.58 | -0.85 | nan |

> 由 scripts/factor_backtest_probe.py 生成 · 确定性判定，无 LLM 判决；
> 仅作 C-3 审批证据，不直接改动生产。