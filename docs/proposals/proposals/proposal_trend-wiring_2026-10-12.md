# 提案：趋势过滤接线进 v1 美股生产路径（trend-wiring）

- **编号**：P-2026-10-12-trend-wiring
- **日期**：2026-10-12
- **状态**：**待审批（C-3）**
- **流程**：C-2 提案 → C-3 人工审批 → 实施

---

## 1. 背景与根因链

1. **WT-14 裁决 B（2026-10-12）**：`attribution.without_trend` 的"÷0.5 还原"前提（target 已按 TREND_FILTER_FACTOR 打折）**不成立**——v1 `run()` 的 `target = core_position + ammo`（pipeline.py:96）从未乘趋势系数；Mac 实证 blocked 行 target/core 比值中位 1.198（绝非 0.5）。修复 = 对照原样返回（WT-22，已入库）。
2. **WT-22 收口实跑（2026-10-12）**：`python -m fg_system.cli attribution` → with = without = **0.754331**，贡献度 **0.00%**（阈值 2.00%），blocked 413 天（16.37%），verdict = effective False。
3. **根因（本次核实）**：趋势过滤在 v1 生产路径**只标记、未执行**：
   - `run_equity_v2()`（pipeline.py:668）= v1 `run()` + **追加** trend/trend_blocked 列，target 逐字不变；
   - 全仓唯一 `* trend` 乘法在 `shoutu_core_series`（pipeline.py:665，守猪待兔/变体路径），**非 v1 生产仓位**；
   - ⇒ 413 天里系统**以为自己有趋势保护，实际仓位从未被趋势改变**。

**结论**：贡献度 0 是真实测量，但根因是**未接线**，不是"趋势过滤经测无效"。verdict 建议"降低核心仓上限"属错误触发（应基于干净测量再定仓位规则）。

## 2. 变更内容（接线）

**目标**：让趋势过滤真正作用于 v1 美股生产仓位，使归因可测、纪律闭环。

**公式（终版 = 选项 ii，2026-10-12 变体数据定夺）**：在 `run_equity_v2()` 中，
对**核心仓**打折、**弹药豁免**（极端恐惧加仓保留逆势逻辑）：

```python
# shift 语义对齐（v1 target_position 整体 shift(1)，§10.3）：
# target[T] = core[T-1] × trend[T-1] + ammo[T-1]
prev_trend = trend.shift(1).fillna(1.0)
prev_core = us["core_position"].shift(1)
prev_ammo = us["ammo_position"].shift(1).fillna(0.0)
wired = prev_core * prev_trend + prev_ammo
us["target_position"] = wired.where(us["target_position"].notna())
```

- `trend` 为离散系数（`market_signal.trend_factor_series`：close<MA200 → 0.5，
  否则 1.0；QQQ/BTC 均线关系）；`trend < 1.0` = blocked（核心仓打折 0~1 倍），
  `trend = 1.0` = 不挡，warmup NaN 保持 NaN；
- 参考先例：`shoutu_core_series` 的 `* sat * trend`（pipeline.py:665）——趋势系数
  乘进仓位是既有口径；
- **选项选择历程**：初实施选项 i（target 整体 × trend）后跑对照变体 V-TREND-AMMO
  （弹药豁免），OOS 全面优于 V-H7（离散全打折）：TQQQ 年化 23.12% vs 19.62%、
  SOXL 52.12% vs 45.79%、UPRO 16.09% vs 13.71% ⇒ **数据定夺终版取选项 ii**。

## 3. 影响面

| 维度 | 影响 |
|---|---|
| 仓位 | 413 天（16.37%）核心仓下调至 0~1 倍（弹药豁免）；其余交易日不变 |
| 回测 | 净值/MDD/逐年表现全变（接线后全量重跑：1336 passed） |
| 归因 | with_trend = 打折路径 vs without_trend = 还原未打折（core+ammo）⇒
  贡献度真实测量：**-5.97%（收益换回撤：MDD -12.52% vs -14.24%）** |
| 生产 | `run_equity_v2()` 输出 target 变化 ⇒ 每日链、简报、dashboard 同步反映 |
| 测试 | pipeline/attribution 测试更新 + 新断言（接线 5 用例 + 归因还原 2 用例） |

**不改变**：CORE_CAP、MARKET_CORE_RATIO、ammo 逻辑、加密路径、A1 变体路径。

## 4. 验收标准（已全部达成，2026-10-12）

1. `run_equity_v2()` 逐行验证：`target[T] = core[T-1]×trend[T-1] + ammo[T-1]`；
   非 blocked 日与 v1 原样；warmup 保持 NaN —— `tests/test_pipeline_trend_wiring.py` 5 passed
2. 回测对比（全量/逐年/MDD）与接线前并列登记 —— `evolution/experiments/variant_h007_2026-10-12.md`
3. `cli attribution` 重跑：贡献度 -5.97%、effective=True（对照 = 还原未打折版）——
   with 0.690116 / without 0.749778 / MDD -12.52% vs -14.24%
4. 新增/更新测试 + 全量回归绿 —— **1336 passed / 0 fail**
5. 文档登记（decision-log + 提案归档）✓

## 5. 审批记录（C-3，2026-10-12）

- [x] 用户"好的"批准接线方向（选项 i 实施 + 选项 ii 对照变体）
- [x] 变体数据定夺：**终版 = 选项 ii（core×trend + ammo，弹药豁免）**
- [ ] 或驳回（维持现状：趋势过滤仅标记、归因贡献 0）—— 未发生

**注意**：接线属**规则/仓位变更**（trading-discipline 第 8 条），用户已人工确认
（C-3 闭环）；核心仓上限**不**在本提案内调整（归因显示贡献有效、非接近零，
选项 A「降核心仓上限」触发条件不成立）。
