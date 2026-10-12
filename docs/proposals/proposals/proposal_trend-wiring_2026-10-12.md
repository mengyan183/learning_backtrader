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

**公式（选项 i，推荐）**：在 `run_equity_v2()` 中，追加趋势列后对 target 整体打折：

```
us["target_position"] = us["target_position"] * us["trend"].fillna(1.0)
```

- `trend` 为连续系数（`market_signal.trend_factor_series`，QQQ/BTC 均线关系）；`trend < 1.0` = blocked（打折），`trend = 1.0` = 不挡，warmup NaN 保持 NaN；
- 参考先例：`shoutu_core_series` 的 `* sat * trend`（pipeline.py:665）——趋势系数乘进仓位是既有口径；
- 贴合原始设计意图：归因对照"÷factor 还原"的前提正是 **target 整体打折**（WT-14 修复前语义）。

**备选（选项 ii，未推荐）**：`target = core × trend + ammo`——弹药（极端恐惧加仓）不受趋势过滤影响。理由不推荐：弹药加仓在趋势下行期同样面临亏损风险，且与归因对照语义（target 整体）不一致；如需弹药豁免可后续以变体实验验证。

## 3. 影响面

| 维度 | 影响 |
|---|---|
| 仓位 | 413 天（16.37%）target 下调至 0~1 倍；其余交易日不变 |
| 回测 | 净值/MDD/逐年表现全变（须全量重跑对比） |
| 归因 | with_trend = 打折路径 vs without_trend = 原样 ⇒ 贡献度可真实测量；verdict 基于新数据 |
| 生产 | `run_equity_v2()` 输出 target 变化 ⇒ 每日链、简报、dashboard 同步反映 |
| 测试 | pipeline/attribution 测试更新 + 新断言 |

**不改变**：CORE_CAP、MARKET_CORE_RATIO、ammo 逻辑、加密路径、A1 变体路径。

## 4. 验收标准

1. `run_equity_v2()` 抽样验证：blocked 日 target = v1 target × trend；非 blocked 日不变；warmup 保持 NaN
2. 回测对比（全量/逐年/MDD）与接线前并列登记
3. `cli attribution` 重跑：贡献度、effective 判定（对照 = 接线前的原样路径语义）
4. 新增/更新测试 + 增量 pytest 绿 + 全量回归绿
5. 文档登记（decision-log + 提案归档）

## 5. 审批请求（C-3）

- [ ] 批准接线（选项 i：target × trend 整体打折）
- [ ] 或改为选项 ii（core × trend + ammo）
- [ ] 或驳回（维持现状：趋势过滤仅标记、归因贡献 0）

**注意**：接线属**规则/仓位变更**（trading-discipline 第 8 条），审批通过后才可实施；核心仓上限**不**在本提案内调整。
