# 规则敏感性分析汇总（阶段 1️⃣）

> 生成时间：2026-10-09。纪律：只测量不改参；结论进文档，调参走阶段 2 变体 + 审批。
> 口径：复用 `pipeline.run(write=False)` 重算 target_position（与每日链同源）；
> 回测 = 生产同款 runner；IC = fg_index 对次日收益 Spearman 秩相关。

## 已产出

| 参数组 | 标的 | 表 | 敏感区间结论（2026-10-09 首检） |
|---|---|---|---|
| 熔断线（circuit） | TQQQ | [sensitivity_circuit_TQQQ.md](sensitivity_circuit_TQQQ.md) | **贪婪侧不敏感**（85 熔断线 80/85/90 → 年化 14.9%~15.1%，回撤均 -43.1%）；**恐惧侧敏感**（极恐线 5 → 年化 12.65%、回撤改善至 -36.7%，但收益损失 > 回撤收益 ⇒ 当前 10 合理） |
| 档位买卖线（zone） | TQQQ | [sensitivity_zone_TQQQ.md](sensitivity_zone_TQQQ.md) | 两端内收（[25,40,60,75]）→ 年化 13.1%、回撤 -46.1% 为最差 ⇒ **买卖线两端对收益敏感，基准 [20,40,60,80] 处于稳健区间** |

## 待扫

- 目标仓位（core_cap）组、减仓阈值（trim）组：网格已定义（sensitivity_scan.py），
  Windows 端可执行（双端分工表 B 类）；Mac 已跑 circuit/zone 首检。

## 下一步

- 阶段 1 结论进文档后，如发现需调参 → 走阶段 2 变体（已跑 V-ATR，OOS 不采纳，
  见 evolution/experiments/variant_h007_2026-10-09.md）+ C-2/C-3 审批。
