# 贪恐系统自我进化方案（evolution-plan）

> 状态：草案待审（issue #3 的 20 个文件补传后，方案依赖方可落地）
> 日期：2026-10-01
> 定位：**在项目纪律内的研究通道**。LLM 是建议者，回测是裁判，人工是审批者，生产路径逐位不变。

---

## 1. 为什么需要"自我进化"，以及它在这里的边界

贪恐系统的核心资产不是某一版参数，而是**防过拟合纪律**（config.py 全部参数标注"先验值，禁止优化"；第 8 条流程：先改文档 → 再改代码 → 再回测；OOS 样本外禁止调参；483 个测试锁定行为）。

因此本方案的"进化"**不是**"LLM 自动调参 + 回测择优"——那正是本系统最反对的过拟合机器。

**定义**：自我进化 = 系统在**研究通道**内自动生成可证伪的改进假说 → 自动完成变体实现与验证 → 产出带证据的变更提案 → 由人工按第 8 条流程审批采纳。**生产路径（config.py / 核心信号 / 等价性守卫）在采纳前逐位不变。**

## 2. 进化闭环（6 阶段）

```
① 信号生产      pipeline.py → Data/features.csv / portfolio_features.csv（每日收盘）
   ↓
② 基准回测      fg_system/backtest/runner.py（恢复后），IS/OOS 划分，输出基准绩效 JSON
   ↓
③ LLM 体检      Hermes(GLM) 读绩效 + features 尾部 → 体检报告（弱信号/异常日/损耗漂移/极端规则触发）
   ↓
④ 假说生成      可证伪假说 JSON（含不成立判据）→ evolution/hypotheses.md
   ↓
⑤ 变体验证      shoutu_variants 模式：新增 VARIANTS 条目 + 等价性守卫测试 + 变体回测
   ↓
⑥ 门控采纳      OOS 不恶化 + 测试全绿 → 第 8 条流程变更提案 → 人工审批 → 才动 config.py
```

### 阶段说明

- **① 信号生产**：现状已有（pipeline.py），无需改动。进化只读 features 输出，不侵入。
- **② 基准回测**：依赖 `fg_system/backtest/*`（runner/strategy/feed/attribution/crypto_runner）恢复。基准绩效落 `evolution/baseline.json`（年化、最大回撤、Calmar、逐年、分市场归因），任何变体都必须与之对比。
- **③ LLM 体检**：输入 = 基准绩效 + features 尾部（含 zone/核心仓/弹药/熔断/极端标记）+ 实盘快照（scripts/portfolio_check.py 恢复后）。Hermes(GLM) 每日收盘后跑，输出结构化体检报告（JSON）。**判据先行**：体检只报"现象"，不直接给结论。
- **④ 假说生成**：每条假说必须包含三要素——**假设 / 检验方法 / 不成立判据**。缺少任一要素的假说不入库（防 LLM 空谈）。登记到 `evolution/hypotheses.md`（编号 H-xxx，状态：open / verifying / adopted / falsified）。
- **⑤ 变体验证**：复用 `shoutu_variants.VARIANTS` 的成熟模式——新增变体 = 加一个 VARIANTS 条目 + 一条等价性守卫测试（"默认参数逐位相同"红线）。LLM 生成变体代码草稿，人工复核后落入 `evolution/experiments/`，生产代码零改动。
- **⑥ 门控采纳**：采纳判据（硬条件，全部满足才生成提案）：
  1. 等价性守卫测试全绿（默认行为逐位不变）；
  2. OOS 区间绩效**不劣于**基准（不要求必须更优——更稳也是进化）；
  3. 无新增前视偏差（§10 红线）；
  4. 变更提案按第 8 条流程格式书写（依据/口径/回测证据/风险），由人工审批。

## 3. 记忆与复盘层（借鉴 Robot-Investment-Assistant-of-US-Stock）

该仓库的 **memory/ 记忆机制**（每日日志 + 长期记忆 + 目标文档）对本系统有直接参考价值——进化需要"经验沉淀"，否则每次分析都是白板：

| 借鉴点 | 移植到本系统 | 用途 |
|---|---|---|
| `memory/YYYY-MM-DD.md` 每日日志 | `evolution/memory/YYYY-MM-DD.md` | 记录当日体检、假说、实验结果、采纳/证伪决策 |
| 长期记忆（MEMORY.md） | `evolution/LESSONS.md` | 编号教训库（沿用 trading-discipline.md 第 12 条体例）：证伪记录、踩坑、参数废弃原因 |
| 目标/约束文档（SOUL/USER） | `evolution/GOALS.md` | 进化目标与红线（收益-回撤约束、禁止优化清单、审批边界） |

**规则**：每次 LLM 分析前先读 `LESSONS.md` + 最近 7 天日志（防止重复提出已被证伪的假说——这是"记忆即进化"的关键）。

## 4. 工具分工（当前 Mac 环境）

| 环节 | 工具 | 频率 | 说明 |
|---|---|---|---|
| 调度/执行 | OpenClaw（cron + agent） | 每日 | 定时跑 pipeline → 回测 → 触发体检；把假说落成变体草稿 |
| 体检/假说 | Hermes（GLM 云端） | 每日收盘后 | 快、中文好；GLM 限流时自动切 NVIDIA deepseek（fallback 已配置） |
| 深研/归因 | Harness（NVIDIA deepseek） | 周度 | 慢但深；复杂归因、长上下文分析 |
| 实时粗分类 | Ollama 本地小模型 | 实时 | 未来候选：新闻情绪因子等低门槛高频任务 |
| **裁判** | backtrader + pytest | 每次验证 | **LLM 永不判决**；等价性守卫 + OOS 判据是硬闸门 |
| 审批 | 人工（用户） | 采纳时 | 第 8 条流程最终签字 |

## 5. MVP 落地清单（依赖文件恢复后执行）

```
evolution/
├── GOALS.md            # 进化目标与红线
├── hypotheses.md       # 假说登记表（H-xxx）
├── LESSONS.md          # 长期教训库
├── memory/             # 每日实验日志
├── baseline.json       # 基准绩效
└── experiments/        # 变体代码草稿 + 回测结果

scripts/
├── evolve_baseline.py  # 跑基准回测 → baseline.json
├── evolve_review.py    # 调 Hermes(8642) 体检 → 假说 JSON → hypotheses.md
└── evolve_variant.py   # 假说 → VARIANTS 草稿 + 守卫测试 + 变体回测 → 变更提案
```

**依赖文件（issue #3 待 Windows 补传）**：`fg_system/backtest/*`（回测裁判）、`fg_system/cli.py`（status/audit 入口）、`fg_system/audit.py`（纪律审计）、`fg_system/evolution.py`（**第 14 条"进化就绪度"——恢复后须先对齐其定义，避免本方案与之冲突**）、`scripts/portfolio_check.py` 相关脚本。

## 6. 红线清单（进化也不许做的事）

1. **LLM 永不直接写 config.py**——任何参数变更必须走第 8 条流程提案。
2. **永不绕过等价性守卫**——"分析里的规则 ≠ 生产的规则"是本系统第一教训。
3. **OOS 禁止调参**——样本外只有一次发言权（验收），没有试错权。
4. **证伪即成果**——假说不成立照常入库归档（falsified），教训写入 LESSONS.md；不允许静默丢弃反证。
5. **不自动上线**——STAGE 闸门（development/usage）不变；进化产物是"提案 + 证据"，采纳权永远在人工。

## 7. 修订记录（A-4 进化就绪度对齐，2026-10-08）

执行 docs/readiness-alignment-checklist.md（evolution.py 已补传 ce44ae1，issue #3 关闭）。

**1. 代码就绪度定义**：`fg_system/evolution.py::readiness()` / `shoutu_readiness()`
- 就绪度 = **守猪待兔数据积累天数 vs `config.RANK_WINDOW`**（分位数口径何时生效），
  返回 `stage / shoutu_mode / 逐标的数据表(days/needed/remaining/mode/first/last) / next_upgrade`。
- 模块 docstring 明确"**只做观测，不改任何参数**"（第 14.1 条），瓶颈口径 = 数据（第 14.5 条）。

**2. 与六阶段对比结论：互补而非冲突**
| 维度 | 代码（evolution.py） | 本方案六阶段 |
|---|---|---|
| 就绪度语义 | **数据积累就绪**（percentile 口径何时生效） | **流程闸门就绪**（回测基准/守卫/审批） |
| 覆盖范围 | 第 14 条数据就绪 | 第 13 条进化闭环 |
| 冲突 | 无——两者正交；代码回答"数据还差多少天"，方案回答"流程走到哪一步" |  |

按检查单第 4 步：无严格/宽松冲突，属互补，**不做任何代码/方案改动**，仅记录。

**3. 红线对照**：LLM 不判案（模块只观测）✅ / OOS 禁调参（无调参逻辑）✅ / 等价性守卫（无生产改动）✅ / 无前视偏差（只读数据文件）✅ / 人工审批（不产生变更）✅

**4. 待办联动**：本方案阶段②基准回测的"就绪"由 A-2（evolve_baseline.py → baseline.json）承担，产出后 evolution.py 如需引用可在研究通道内新增只读函数，仍走本纪律。
