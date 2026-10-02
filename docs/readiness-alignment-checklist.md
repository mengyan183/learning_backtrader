# 进化就绪度对齐检查单

> 目的：`fg_system/evolution.py`（issue #3 待补传）定义第 14 条"进化就绪度"，
> 补传后**先按本检查单对齐**，避免本方案（docs/evolution-plan.md）与代码定义冲突。
> 状态：⬜ 阻塞（evolution.py 未补传）· 本检查单已就绪，补传后直接执行。

## 对齐步骤

### 1. 定位代码中的就绪度定义
- 搜索 `fg_system/evolution.py`：`readiness` / `就绪` / `evolution_ready` / `ready`
- 找到就绪度判定函数（可能基于：数据完整性 / 回测基准存在 / 变体守卫通过等）

### 2. 与 docs/evolution-plan.md 六阶段对比
| evolution-plan.md 定义 | 代码实现（待填） | 冲突？ |
|---|---|---|
| 阶段 ① 假说生成：LLM 体检 → 登记 | | |
| 阶段 ② 基准回测：backtest runner + baseline.json | | |
| 阶段 ③ LLM 体检（已自动化） | | |
| 阶段 ④ 假说验证（已自动化） | | |
| 阶段 ⑤ 变体验证：OOS 不劣化才通过 | | |
| 阶段 ⑥ 门控采纳：人工审批后才动 config.py | | |

### 3. 红线对照
- [ ] LLM 永不判决（回测 + pytest 唯一裁判）
- [ ] OOS 禁调参（先变体后审批）
- [ ] 等价性守卫（默认行为逐位不变）
- [ ] 无新增前视偏差
- [ ] 第 8 条流程人工审批

### 4. 冲突处理
- 若代码就绪度**比本方案严格** → 以代码为准，更新 docs/evolution-plan.md 并注明
- 若代码就绪度**比本方案宽松** → 以本方案为准（更严），在 evolution.py 注释中标注，不改代码逻辑
- 任何冲突都记录到 docs/evolution-plan.md "修订记录"，不静默二选一

### 5. 验收
- [ ] 对齐结论写入 docs/evolution-plan.md 修订记录
- [ ] `docs/roadmap.md` 第一层"对齐进化就绪度"标记 ✅
