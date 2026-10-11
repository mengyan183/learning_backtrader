# 贪恐系统迭代路线图（Roadmap）

> 目标：在"数据裁判 + 人工审批"的慢闭环纪律下，让系统持续产生**可验证、可追溯、可回退**的改进。
> 状态标记：⬜ 未开始 / 🔄 进行中 / ✅ 完成
> 最后更新：2026-10-11（纳入《贪恐系统发展迭代规划 v1.0》为下游执行视图）

## 当前状态基线（2026-10-09）

- ✅ 双端同步链路全通（2026-10-09）：公司 Windows → 飞书 → OpenClaw(Mac) → 仓库，855 片大包（117 文件）全量入库并推送；白名单误伤修复（.gitignore/.gitattributes 放行、.git 目录仍拒）、push 卡死根治（GH_TOKEN 绕过 keychain）；进度文档（README/NEXT-SESSION/变更记录索引）同步更新
- ✅ 数学模型落地（2026-10-06）：HMM 状态识别 / 档位转移马尔可夫矩阵 / EVT 阈值校准 / 贝叶斯假说信心（fg_system/models/ + scripts/model_report.py → Data/model_report_*.json；零新依赖纯 numpy）
- ✅ 未落地/受阻塞实现统一登记：docs/blocked-registry.md（A 外部依赖 / B 数据积累 / C 回测后 / D 可先做）
- ✅ 变更记录总索引 + 覆盖审计：docs/变更记录/README.md（89 commits vs 6 份记录，缺口已列明）
- ✅ 数据：COIN 1254 行、CONL 690 行（FutuOpenD 真实行情）、守猪待兔历史 3606 行入库
- ✅ 假说引擎：H-001~H-009 登记，H-003/H-004 adopted；每日 05:30（launchd）+ 18:00（OpenClaw cron，结果推飞书）自动重检
- ✅ 记忆层：GOALS / hypotheses / LESSONS(L-001~L-004) / memory 每日日志
- ✅ 持仓卡看板：三态覆盖 + 守猪待兔官方口径已上线
- ✅ E1 多智能体投研流水线（invest_research.py，飞书推送实测成功）
- ✅ E2 概念漂移监控（drift_monitor.py：滚动 IC/ICIR，逆向指标语义，异常推飞书，已接入每日链）
- ✅ E4 因子引擎地基（fg_system/factors/eval.py：滚动 IC/ICIR/多前瞻衰减）
- ✅ E5 Copilot 持仓问答（portfolio-qa 技能 + OpenClaw 默认 GLM，飞书/网页可用）
- ✅ 不依赖回测任务全部清零：就绪度对齐检查单 / 情绪子信号（VIX 全历史 + OKX 资金费率入库+看板）/ 观察池扩池-数据侧（NVDL/TSLL/FNGU/FAS/TNA/SQQQ 入库，白名单未动）
- ✅ 回测裁判恢复：`fg_system/backtest/*` 已还原（issue #3 关闭）+ 基准 baseline.json 已产出（A 类阻塞全部解除）

## 第一层：解锁回测裁判（近期，唯一硬前置）

| 动作 | 说明 | 验收 |
|---|---|---|
| ✅ 补传回测文件 | issue #3 的 20 个文件（runner/strategy/feed/attribution/crypto_runner + cli/audit/evolution.py） | 相关测试全绿（ce44ae1 + 78e4c44 + 831f450，全量 838 passed） |
| ✅ 恢复基准 | `evolve_baseline.py` 产出 `baseline.json`（年化/回撤/Calmar/逐年/分市场归因，IS/OOS 划分） | baseline.json 已产出（2026-10-08，scripts/evolve_baseline.py，IS 截至 2024-09-30 / OOS 自 2024-10-01，时间序 80/20） |
| ✅ 解锁 H-005/H-007 | portfolio_features.csv 重建后分箱统计、布尔位回撤比较 | 两假说出验证结论（2026-10-08：H-005 rejected / H-007 adopted，详见 evolution/hypothesis_results.md；H-010~H-022 虚构列口径审计见 hypotheses.md） |
| ✅ 对齐进化就绪度 | `fg_system/evolution.py` 的"进化就绪度"定义与本方案核对（检查单已就绪：docs/readiness-alignment-checklist.md，待文件补传后执行） | 文档确认无冲突（2026-10-08，结论见 evolution-plan.md 修订记录） |

## 第二层：自动重检 → 自动提案（中期，回测恢复后）

| 动作 | 说明 | 验收 |
|---|---|---|
| ✅ 变体实验设施 | `evolve_variant.py`：adopted 假说 → VARIANTS 草稿 + 等价性守卫测试（默认参数逐位相同红线）+ 变体回测 | **2026-10-08 完成**：variants.py / evolve_variant.py / test_variant_guard.py（4 passed，全量 842 passed）；V-H7 三标的 OOS 均不采纳（负结果如实登记，提案草稿 evolution/experiments/variant_h007_2026-10-08.md，裁决 Y 纳入长期观察） |
| ✅ 变更提案自动化 | 回测 OOS 不劣化 → 按第 8 条流程自动生成提案（依据/口径/回测证据/风险） | **2026-10-08 完成**：evolve_propose.py → evolution/proposals/（V-H7 三标的自动生成，判定确定性） |
| ✅ 人工审批闭环 | 提案推飞书 → 用户签字 → 才动 config.py | **2026-10-08 完成（C-3）**：evolve_approve.py（list 扫描未审批提案 / --status Y\|N\|Z 回写审批位）→ V-H7 三份提案已全部审批（Z 观察） |
| ✅ 阶段 6 复盘/周报 | 每周自动汇总（adopted/falsified/数据缺口/风险）推飞书 | **2026-10-08 完成（C-4）**：evolve_weekly.py → evolution/weekly/weekly-2026-W41.md，--push 接 feishu_send |

**本层已全部完成：进化闭环（6 阶段）全自动运转，人只做最后签字。**

## 第三层：信号源与覆盖扩展（远期，可选）

| 方向 | 说明 | 纪律要求 |
|---|---|---|
| 多资产情绪合成 | 守猪待兔 A股/港股/加密已有布点 → 跨市场情绪因子 | 走门控采纳，禁止直接调参 |
| 个股指数扩池 | 从 6 只扩展到更宽标的池（TQQQ/SOXL/UPRO 已接入） | 新增标的走 SHOUTU_SYMBOLS 流程（数据侧已就绪：OBSERVE_SYMBOLS 观察池入库；策略侧 C-9 已完成 6 映射，白名单未动） |
| 极端规则校准 | 85 熔断 / 10 极恐用积累实盘快照做参数校准 | OOS 禁调参，必须变体 + 人工审批 |
| 实盘-回测归因校验 | 预测 vs 实际每日归因，检验信号与执行的偏差 | 数据只读，不改策略 |

## 扩展规划（跳出当前架构，参考市面同类产品）

> 调研参考：TradingAgents / QuantAgents / ContestTrade（多智能体投研）、Qlib / QuantConnect / vn.py / 米筐（量化平台）、CNN Fear&Greed / CFGI / CoinGlass / Market Mood（情绪指数）、FinRL-X / OpenBB（开源金融 AI）、walk-forward 方法学（对抗概念漂移）。
> 原则：所有方向仍在"数据裁判 + 人工审批"纪律内；每个子项都走变体 + 门控采纳。

### E1 多信号合成投研层（多智能体流水线）
- ✅ 多智能体流水线已上线（invest_research.py：Hermes 情绪 → NIM 归因 → 本地裁判 → 飞书推送）
- ✅ 情绪子信号数据接入：加密资金费率（OKX，走代理）+ VIX 全历史（CBOE）+ 看板展示
- ✅ 期权 Put-Call（B-6，2026-10-08 免 key 双层链路落地：官方批量 CSV + 每日页面；检验 total IC 0.044 / IR 0.58 / 恐慌端次日+0.14%>贪婪端+0.01%，1449 样本）；✅ 新闻/社媒情绪（B-7，2026-10-08 NewsAPI 免费 key 落地：大盘/加密/标的词表打分 → news_sentiment.csv，🟡 研究参考）、个股广度
- 风险：多智能体"虚假共识"（辩论强化偏见）→ 必须独立裁判 + 每个子信号单独走门控

### E2 walk-forward 滚动进化（对抗概念漂移）
- ✅ 漂移监控器已上线（滚动 IC 下降检测 → 告警推飞书；系统指数实测为稳定逆向指标 IC -0.36）
- ✅ 季度 walk-forward 重标定流程（**2026-10-08 完成（C-5）**：evolve_walkforward.py + launchd com.fg.quarterly-walkforward 1/4/7/10 月 1 日 08:00；V-H7 首轮重检：34~35/40 窗不劣化/等价 ⇒ 维持观察）
- ✅ 假说绩效衰减自动降级（**2026-10-08 完成（C-11）**：evolve_decay.py 确定性判据，近窗衰减 ≥2/4 horizon → decayed；F-007/F-009 accumulating 登记）

### E3 回测=实盘同代码的执行闭环
- 目标仓位计算共用同一份代码（QuantConnect/FinRL-X 组合语义统一，杜绝逻辑漂移）
- ✅ 富途已接：自动推送目标仓位确认到飞书 → 人工审批 → 一键执行（**2026-10-08 完成（C-6）**：execution_confirm.py 确认清单 + --finalize 可执行指令；系统不自动下单）
- 护栏：熔断、最大仓位、大单人工审批；执行自动化必须在纪律红线内

### E4 AI 因子引擎
- ✅ 因子检验核心已交付（fg_system/factors/eval.py：滚动 IC/ICIR/多前瞻衰减）
- ✅ 个股系统指数扩展成正式因子库（**2026-10-08 完成（C-7）**：新增 F-007 守猪待兔温度 / F-008 极恐标记 / F-009 资金费率，scripts/factor_screen_extend.py；F-007/F-009 样本不足登记积累中）
- ✅ 因子注册/检验/跟踪衰减流程文档化（factors.md 登记表 F-001~F-009 + 首批候选 IC/IR 初检，见 D-2）

### E5 主动投资 Copilot
- ✅ 持仓问答已接通（portfolio-qa 技能 + OpenClaw 默认 GLM，飞书/网页入口实测成功）
- ✅ 扩展问"归因/假说状态/漂移监控"等能力（fg-qa skill 已支持多问题类型 + kb-search 知识库路由，见 D-3）

### 扩展规划落地顺序
| 阶段 | 方向 | 前置 | 状态 |
|---|---|---|---|
| 近期（回测恢复后） | E2 重标定流程 + E3 执行确认流 | 基准回测 | E2 监控✅ / 重标定✅（C-5）/ E3✅（C-6） |
| 中期 | E1 情绪子信号补全 + 多智能体深化 | 数据管线稳定 | E1 主链路✅ / Put-Call✅（B-6）/ 新闻情绪✅（B-7） |
| 远期 | E4 因子库 + E5 Copilot 深化 | E1/E2 沉淀 | E4 因子库✅（C-7）/ E5 主链路✅ |

### 扩展纪律（新增）
- 不引入黑箱（RL/深度模型）作为裁判：只借鉴其"环境/组合语义统一"，可追溯优先
- 每个扩展子项独立走"假说 → 变体 → 审批"；未批准的扩展不落地
- 扩展设施同样受防过度工程约束

## 量化升级路线（2026-10-07 用户确认）

> 目标：在"数据裁判 + 人工审批"纪律内，把贪恐系统从"规则直觉"逐步升级为
> "规则+统计验证"的量化闭环。核心原则：**量化是验证手段，不是黑箱裁判**；
> 每一级都必须能被回测证伪，且走门控采纳。

### 已有量化地基（现状盘点）
- ✅ 数学模型包：HMM 状态识别 / 档位转移马尔可夫矩阵 / EVT 阈值校准 /
  贝叶斯假说信心（fg_system/models/，零新依赖纯 numpy）
- ✅ 因子检验框架：滚动 IC/ICIR/多前瞻衰减（fg_system/factors/eval.py，E4）
- ✅ 概念漂移监控：滚动 IC 下降检测 → 告警（E2，实测系统指数 IC -0.36 稳定逆向）
- ✅ 回测裁判已恢复：`fg_system/backtest/*` 已还原，issue #3 于 2026-10-08 关闭；
  `evolution/baseline.json` 已产出 ⇒ 阶段 1/2 的前置**已解除**（本行原为 🔴「唯一硬前置」，已过时）

### 升级路径（回测恢复后按序执行）

| 阶段 | 内容 | 验收 | 纪律 |
|---|---|---|---|
| 1️⃣ 规则敏感性分析 | 现有规则全部参数化后进回测：档位买卖线（±50/60/70）、减仓阈值（P1 1% 规则）、熔断（85/10）、目标仓位 | 每参数一张 IC/收益/回撤敏感性表，标出"敏感区间" | 只测量不改参；结论进文档 |
| 2️⃣ 经典量化手段 | 逐个走变体+门控采纳：①ATR 止损参数化 ②波动率目标仓位（vol targeting）③杠杆ETF 相关性风险预算（有效敞口，防 YINN/GDXU 同跌）④动能/均线过滤（防贪婪档追高） | 每个手段一个变体回测，OOS 不劣化才提案 | OOS 禁调参；等价性守卫 | ✅ **2026-10-09 全部落地**：V-ATR/V-VOL（①②）归档（9c56eeb）；V-CORR（③）三标的全维持观察（Z 审批）；V-MA（④）仅 TQQQ 维持；V-H7 长期观察 |
| 3️⃣ walk-forward 重标定 | 漂移告警后季度滚动重标定（变体+审批，非直接调参）；弱假说自动降级归档 | 重标定流程跑通一次 | 借鉴 ContestTrade 内部竞赛 | ✅ **2026-10-09 跑通**：evolve_walkforward.py + 全变体重检（V-CORR 27/27/26 维持等）+ launchd 季度自动调度（1/4/7/10 月 1 日 08:00）；C-11 衰减自动降级已落地 |
| 4️⃣ 因子库化 | 个股系统指数 → 正式因子库：LLM 生成因子草稿 → IC/IR/衰减检验 → 合格入库 | 因子注册/检验/衰减文档 + 首个非系统因子入库 | 每因子独立门控 | ✅ **2026-10-09 落地**：C-7 新增 F-007 守猪待兔温度 / F-008 极恐标记 / F-009 资金费率（F-007/F-009 样本积累中）；IC/IR/衰减框架 E4 已就绪 |

#### 阶段 1️⃣ 实施清单（2026-10-09 拆解 → ✅ 2026-10-09 已由 Mac 端完成）

> **状态更正**：原定位"Windows 端可执行（唯一未被阻塞）"已过时——本清单已由 Mac 于 2026-10-09 执行完毕（`evolution/sensitivity/` 四组表已产出，见下），Windows 端不再重复此任务，转做全量 pytest 回归与 B 类数据分析。
>
> 原依赖说明：依赖已解除（baseline.json 产出）；纯本地计算不依赖公网。

**目标**：现有规则全部参数化后进回测，输出每参数敏感性表 + "敏感区间"结论，**只测量不改参**。

**参数化范围**（4 组，每组一张表）：

| 参数组 | 参数 | 扫描范围 | 输出 |
|---|---|---|---|
| 档位买卖线 | `buy_line` / `sell_line`（个股线） | 各从 ±40~±80，步长 5 | IC / 收益 / 回撤敏感性表 + 敏感区间 |
| 减仓阈值 | P1 1% 规则阈值 | 0.5%~3%，步长 0.5% | 同上 |
| 熔断 | 熔断线（85） / 极恐线（10） | 75~95 / 5~20，步长 2~5 | 同上 |
| 目标仓位 | `core_position` 基准值 | 0~50%，步长 5% | 同上 |

**交付物**（✅ 均已产出，2026-10-09）：
1. `evolution/sensitivity/sensitivity_circuit_TQQQ.md`（熔断线 75~95 / 极恐线 5~20 扫描）
2. `evolution/sensitivity/sensitivity_zone_TQQQ.md`（档位边界 [20,40,60,80] 扫描）
3. `evolution/sensitivity/sensitivity_core_TQQQ.md`（目标仓位 0~50% 扫描）
4. `evolution/sensitivity/sensitivity_trim_TQQQ.md`（减仓阈值扫描）
5. 汇总 `evolution/sensitivity/README.md`（敏感区间一览 + 与现状参数对照）

**验收**（✅ 已过）：
- 4 组参数各产出 ≥1 张敏感性表（IC/收益/回撤三指标）
- 每张表标出"敏感区间"与"稳定区间"
- 结论进文档，**未改任何 config.py 参数**（只测量不改参纪律落实）

**执行结论（摘要）**：circuit（贪婪侧不敏感/恐惧侧极恐线 5 敏感）、zone（基准 [20,40,60,80] 稳健）、core（两端敏感、0.45 居中合理）、trim（阈值未介入回测路径）。

**纪律**：
- 只测量不改参——看到敏感区间**不调参**，结论先进文档
- 后续如需调整：走阶段 2️⃣ 变体 + OOS 不劣化 + 人工审批（C-2/C-3）
- 复用 C 系列设施：提案/审批/周报已在 Mac 自动化，Windows 只产出敏感性证据

**依赖**：`pip install vectorbt`（唯一新增回测依赖，见框架选型决策）；数据用 Mac 同步来的 `Data/raw/prices.csv` 全量历史。

### 主要权衡（诚实预期）
- **回测可能证伪现有规则**：如"贪婪档位追高是否长期有效""双引擎减仓是否优于
  简单固定减仓"——证伪是量化升级的**价值**，不是失败
- **过拟合风险**：敏感性分析容易"看到就想调"——所以测量与调参必须分离
  （阶段 1 只测不改，阶段 2 才走变体）
- **防过度工程**：量化工具服务于"可验证的交易改进"，不追求工具数量

### 框架选型决策（2026-10-07 确认）

> 原则：**用 5% 功能扛 100% 复杂度 = 不划算**。按当前规模（单机、日线、
> 24+8 标的、规则级验证）选择最简可维护方案。

| 环节 | 选型 | 理由 |
|---|---|---|
| 回测（主） | 恢复本地 `fg_system/backtest/*`（issue #3） | 先恢复不迁移；数据管线已直连，迁移是纯负担 |
| 回测（扫描） | **vectorbt**（唯一新增回测依赖） | 向量化极快，一个循环扫完参数网格，阶段 1 敏感性分析首选 |
| 因子研究 | 自研 `eval.py`（已有，不引库） | 已等价覆盖 Alphalens 核心（滚动 IC/ICIR/衰减） |
| 组合/风险 | **PyPortfolioOpt** 借鉴代码（风险平价/波动率目标）+ arch（GARCH） | 轻量 numpy 系；阶段 2 仓位算法用 |
| 实盘执行 | 富途 OpenAPI 直连（已接）+ 人工审批 | 纪律红线：不引入自动执行 |

**明确不引入**（及其理由）：
- **Qlib**：AI 因子挖掘/模型输出形态与"回测唯一裁判、模型只出假说"纪律冲突（黑箱裁判风险）
- **QuantConnect LEAN**：云规模多市场回测、自带数据格式绑定，单机需求用不上
- **vn.py**：国内券商实盘对接强项，系统实盘已直连富途，无新增价值
- 边界：若未来走到多市场高频 / 因子库规模化 / 多人协作，LEAN（云回测）与
  Qlib（因子挖掘）才值得回头评估


## 纪律红线（不可突破）

1. **LLM 永不判决**：回测 + pytest 是唯一裁判，LLM 只出假说与草稿
2. **OOS 禁止调参**：任何参数改动必须先跑变体，OOS 不劣化才进提案
3. **等价性守卫**：默认行为逐位不变是硬红线
4. **无新增前视偏差**（§10 红线）
5. **人工审批**：第 8 条流程最终签字后才动 config.py

## 风险与监控

- **数据断供**：05:30 `sync_positions.py`（FG_SYNC_MODE=live）依赖富途/OKX 可达，中断会静默断数据 → 每周看 `/tmp/fg_daily.log` + 飞书推送异常时人工检查
- **同步链路稳定性**：公司端 → 飞书 → OpenClaw(Mac) 依赖模型可用性与网关健康；429 限流/模型不可用会拖长响应（已用 fallback 链 + 旁路绕过，见 docs/fg-sync-accelerate.md）
- **过度工程**：进化设施本身要克制，核心产出永远是"可验证的交易改进"，不是工具数量

## 2026-10-11 规划纳入（下游执行视图）

> 完整版：《贪恐系统发展迭代规划 v1.0》`docs/2026-10-11-贪恐系统发展迭代规划.md`（289 行、9 章节、48 来源 URL，用户已评审通过）。
> 本表把 17 个落地项（R1.x 近期 / M2.x 中期 / L3.x 远期）映射进既有三层结构，作为 roadmap 的执行视图；
> 落地时按章节把条目同步进 `NEXT-SESSION.md` / `blocked-registry.md` / `evolution/hypotheses.md`。

| 编号 | 优先级 | 落地项 | 映射到既有层 | 状态 |
|---|---|---|---|---|
| R1.1 | P0 | `factor_screen.py` 升级为 Qlib 式评测协议（IC/RankIC/ICIR + 分组累计净值 + 多空对冲 + 含/不含成本双口径） | 量化升级·阶段 4️⃣ 因子库化（裁判补全） | ✅ 2026-10-11（28 报告跑通；17 pytest；全量 1119 通过） |
| R1.2 | P0 | 未来函数审计工具化（freqtrade lookahead 思想 → pytest 可执行） | 纪律红线（第 4 条）工具化 | ✅ 2026-10-11（审计器 PASS：违规 0 / 白名单 8 / 数据层通过；6 pytest；全量 1125 通过） |
| R1.3 | P1 | 分因子独立 0–100 报告（简报分项表 + dashboard /api/factors；仅展示不进合成） | 扩展规划·E1 深化（透明度） | ✅ 2026-10-11（fecb7be）分因子独立报告：factor_zone/factor_score_summary 进 index.py；简报新增「六因子独立分项」确定性节；dashboard GET /api/factors + 因子卡档位徽标；6 条测试 |
| R1.4 | P1 | 归一化/档位对照实验（A 现状 / B qjr1997 式 z-score / C 动态档位），walk-forward 裁判比较，**生产不动** | 量化升级·阶段 1️⃣ 敏感性延伸 | ✅（三方案 IC 同向；C 动态档位信号更清晰；生产不改，决策-log 第 8 条） |
| R1.5 | P2 | `drift_monitor.py` 数据质量闸门（断点/跳空/极端值检测 + push-alert） | E2 概念漂移（数据保障） | ✅（--quality 三路检测 + freshness_warning.txt 合并写 + 30 日窗口防历史误报） |
| R1.6 | P2 | B 类数据积累持续推进（H-001 7/20、F-009/F-010 accumulating），简报标注样本进度 | B 类数据积累（blocked-registry） | 🔄 |
| R1.7 | P2 | `evolve_review` 假说登记列名校验（虚构列引用自动 `pending-revise`，杜绝 H-042~H-044 类污染） | 纪律工具化（评测池卫生） | ✅ 2026-10-11（bc79af5）假说登记列名校验质量门：脆弱「第 N 列」/虚构列名自动 pending-revise；H-042~H-044 修订为真实列名；6 条测试 |
| M2.1 | P0 | 组合级回测层（bt 思想 A/B 对照：引入 bt vs 自实现），三标的白名单组合净值/成本/回撤 | 量化升级·阶段 2️⃣ 延伸（组合层） | ✅ 2026-10-11（scripts/portfolio_backtest.py 内化方案 B；A/B 决策记录 evolution/experiments/portfolio/decision.md；组合 OOS 37.66% vs B0 75.45%、回撤 -26.07% vs -61.70%、Sharpe 1.26 vs 1.00；与 baseline 单标的口径逐一核对一致） |
| M2.2 | P0 | 🟡→生产验证通道正式化（候选因子→评测→回测裁判→C-3 审批→更新 WEIGHTS，文档化并跑通一次） | 第二层·自动提案延伸 | ✅ 2026-10-11（docs/factor-adoption-pipeline.md；F-011 跑通：评测通过→回测 FAIL→提案待 C-3 审批） |
| M2.3 | P1 | 权重/档位敏感性升级（权重扰动→fg_index→组合回测扫描，进 C-3 审批模板） | 量化升级·阶段 1️⃣ 延伸 | ✅ 2026-10-11（scripts/weight_sensitivity.py；六因子 ±10% 组合 OOS 年化 35.6%~46.7% 稳健；evolve_propose 提案模板 §6 已写入「审批须附敏感性表」） |
| M2.4 | P1 | 情绪子因子候选池（news_sentiment / stablecoin_breadth，注册 F 系列，**不进合成**先进评测池） | 扩展规划·E1 深化 | ✅ 2026-10-11（c65e10d）情绪子因子候选池：news_sentiment(F-010)/stablecoin_breadth(F-013) 注册评测池，不进合成；F-013 首检逆向通过待回测裁判；8 条测试 |
| M2.5 | P2 | walk-forward 季度报告自动化（对接 evolve_weekly，自动产出维持/归档/观察建议） | E2/C-5 深化 | ✅（--decision 2026Q4：维持 7 / 归档 8；季度调度带决策） |
| L3.1 | P1 | 向量化参数扫描（vectorbt 思想：先基准实验，固定 numba/seed/cache；只做扫描层） | 量化升级·回测扫描层 | ✅（vec_run 等价性 12 组全过；64 组网格 8.0x 提速；自实现不引 vectorbt） |
| L3.2 | P1 | 组合风险度量（自实现轻量 CVaR/HRP → 评估 PyPortfolioOpt/Riskfolio-Lib；优化器输出仅参考） | 量化升级·阶段 2️⃣ 风险延伸 | ✅ 2026-10-11（e24d2a3）组合风险度量：risk.py 自实现 CVaR/HRP（纯 numpy+scipy）；OOS 等权组合 CVaR95 -4.02%/VaR95 -2.47%；HRP 参考权重 TQQQ 48.2%/SOXL 2.8%/UPRO 49.0%；与纪律第 9 条对照登记 decision-log；9 条测试 |
| L3.3 | P2 | 实时链路增强（futu_realtime 输入 market_signal，dashboard /realtime；只读） | 扩展规划·E3（盘中预览） | ✅ 2026-10-11（futu_realtime build_market_signal 结构化：type/factor_drivers/in_trading_hours/freshness_ts；dashboard 徽章升级读 market_signal 带盘中/盘外+行情新鲜度标注；/realtime 只读 no-store；7 条测试） |
| L3.4 | P3 | A 股扩展评估（AKShare QVIX/funddb 恐贪可行性，独立支线 or 合并，出评估报告） | 第三层·信号源扩展 | ✅ 2026-10-11（docs/ashare-expansion-assessment.md：AKShare QVIX 免 key 可用可复刻 vix/price 因子逻辑；第三方恐贪指数无 API 不采信；结论=独立支线可行、不与美股合成混入；P3 待启动） |
| L3.5 | P3 | 知识库闭环增强（invest_research 可选引用 kb_search + human30 复盘规则化提炼，非 LLM 判决） | 扩展规划·E5 深化 | ✅ 2026-10-11（invest_research --kb 注入知识库观点参考（标注来源/非判决/失败降级）；human30 insight_summary 确定性复盘洞察：打卡纪律/主导水平/短板聚焦/窗口趋势，无 LLM；6 条测试） |

## 数据源观察项（2026-10-11，用户已按建议拍板）

| 数据源 | 判断 | 状态 |
|---|---|---|
| **FRED**（美联储免费宏观数据库，免 key CSV） | 高价值：fed 因子官方长期数据源（DFF 1954 至今 / T10Y2Y 2000 至今），补 fedwatch 历史不足、作政策表交叉校验基准 | ✅ 数据层已接入（scripts/fetch_fred.py，增量幂等，仅入 Data/raw 不改生产计算）；接入合成权重走 M2.2 评测门控 |
| **QuantPedia**（量化策略百科） | 中：因子思想库（M2.4 候选池/E 类待验证思路来源）——借思想不自引，其回测指标不可直接采信 | 观察，不落地 |
| **Seeking Alpha**（海外投研社区） | 低：观点社区非数据 API，与市场级情绪系统错位，付费墙多 | 不建议 |

**执行顺序**：P0 链 `R1.1 → M2.1 → M2.3/L3.1/L3.2`、`R1.1 → M2.2 → M2.4`；R1.2/R1.5/R1.7 全程横切（纪律工具化 + 评测池卫生）。
**纪律锚点**（与规划 §5 一致）：全部落地项确定性优先；不引入黑箱裁判（Qlib RD-Agent/vn.py/LEAN/zipline bundle 明确排除，取舍见规划 §3）；🟡 未经回测裁判不进合成权重；OOS 禁直接调参；免 key 优先；数字指回 `Data/`。
