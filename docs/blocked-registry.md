# 未落地 / 受阻塞实现登记表（Blocked Registry）

> 用途：贪恐系统所有"尚未落地"或"落地受阻"的实现统一登记，供公司电脑续开发时一眼看清缺口与解锁条件。
> 更新纪律：每轮在 roadmap.md / hypotheses.md 出现状态变化时同步本表；新增阻塞项必须登记，解除后移到"已解除"区并注明依据。
> 创建：2026-10-06（数学模型落地轮次）。来源：docs/roadmap.md、evolution/hypotheses.md、docs/变更记录/。

状态标记：🔴 外部依赖阻塞 / 🟡 数据积累中 / ⚪ 等回测恢复 / ✅ 已解除

---

## A 类：外部依赖阻塞（唯一硬前置 = 回测文件，issue #3）— 已全部解除

| 编号 | 事项 | 阻塞原因 | 解锁条件 | 状态 |
|---|---|---|---|---|
| A-1 | 补传回测文件 | issue #3 的 20 个文件未恢复 | 用户从旧机器/备份补传，相关测试全绿 | ✅（2026-10-08，issue #3 已关闭；19 文件补传 + pytest 838 passed / 0 failed / 0 skipped） |
| A-2 | 恢复回测基准 | `evolve_baseline.py` 依赖 A-1 | baseline.json 产出 | ✅（2026-10-08，scripts/evolve_baseline.py 已实现并产出 evolution/baseline.json：全区间/逐年/IS-OOS 80-20/分市场归因） |
| A-3 | 解锁 H-005 / H-007 验证 | portfolio_features.csv 未恢复 | A-1 恢复后分箱/分组统计 | ✅（2026-10-08，portfolio_features.csv 已重建，scripts/verify_hypotheses.py 验证：H-005 rejected / H-007 adopted，详见 evolution/hypothesis_results.md） |
| A-4 | 对齐进化就绪度 | 待回测文件补传 | A-1 恢复 | ✅（2026-10-08，evolution-plan.md 第 7 节修订记录：代码就绪度与六阶段流程闸门互补无冲突） |

## B 类：数据积累型阻塞（时间 / 订阅 / API key 依赖）

| 编号 | 事项 | 阻塞原因 | 解锁条件 | 状态 |
|---|---|---|---|---|
| B-1 | H-002 现金<0 持续性 | ~~需连续 5 个交易日快照~~ → **2026-10-09 判据复核定案** | 5 个交易日快照已满（10-02/10-03/10-07/10-08/10-09，现金全 -879.99，5/5 <0 >2）⇒ **adopted 定案**（详见 hypotheses.md H-002） | ✅ 完成 |
| B-2 | H-001 深度浮亏系统性拖累 | 需 20 个观察点 | 观察点满 20（约 2026-10 末） | 🟡 |
| B-3 | H-006 / H-008 / H-009 | 账户/持仓每日快照需 ≥40-60 交易日 | 快照积累满（约 3 个月） | 🟡 |
| B-4 | H-010~H-022 中引用虚构列者（H-010/H-012/H-014~H-021） | **登记口径缺陷**：引用的 position_multiplier/threshold/「第 5/6 列布尔位」在真实 features/portfolio_features 列中不存在（2026-10-08 审计确认） | **2026-10-08 修订完成**：九条假说已按真实列重新措辞（zone/core_position/fg_index/trend_blocked_us/trend_blocked_crypto），证据区间改为真实数据（zone 真实切换点 09-24）；状态 open 待按修订口径验证 | ✅ 完成 |
| B-5 | H-011 / H-013 | 样本不足（持仓快照少、切换点观察短） | 观察点积累 | 🟡 |
| B-6 | E1 Put-Call 期权情绪 | ~~CBOE 需订阅端点~~ → **免 key 解锁**：CBOE 官方批量 CSV（2006-11→2019-10，cdn 直连）+ Daily 页面逐日（2020-01 起，?dt=YYYY-MM-DD） | ✅ **2026-10-08**：双层链路落地——Data/raw/putcall.csv 3943 条（2006-11-01→2026-10-07）；fetch_sentiment.py 并入 putcall_total/equity/vix 列；putcall_factor_check.py 检验（E4）：total IC 0.044 / 滚动 IR 0.58 / 恐慌端次日 +0.14%>贪婪端 +0.01%（1449 样本）；每日链已接入增量 | ✅ 完成 |
| B-7 | 新闻/社媒情绪（Market Mood） | 需 API key | **2026-10-08 解锁落地**：NewsAPI 免费档 key 已申请（100 请求/天，key 存 Data/newsapi_key 已 gitignore）；fetch_news.py 拉大盘/加密/持仓标的新闻，确定性词表打分 → news_sentiment.csv（mkt/crypto 正负计数+score，🟡 研究参考，候选 E1 情绪子信号，未经回测裁判不进合成权重） | ✅ 完成 |
| B-8 | 极端规则校准（85 熔断 / 10 极恐） | 需积累实盘快照做参数校准 | 快照积累 + OOS 变体验证（红线：OOS 禁直接调参） | 🟡 |
| B-9 | H-033 币股「经营现金流 vs Crypto Beta」分层验证 | 观察池币股（CRCL/HOOD/COIN）样本不足（CRCL 上市 <18 个月） | 样本积累后按收益-BTC 相关性分组比较（2026-10-09 登记，🟡 研究参考） | 🟡 |
| B-10 | H-034 稳定币「使用效率」指标验证 | 稳定币链上交易量数据源未接入 | 接入数据源后构造使用效率 = 链上月交易量/USDC 流通量，检验对币股后续收益领先性（2026-10-09 登记，🟡 研究参考） | 🟡 |
| B-11 | H-035 / H-040 / H-041 口径缺陷 + 未登记阻塞 | **登记口径缺陷**（WT-12 差异 3，2026-10-10）：三条 open 假说引用已判不存在的列——H-035/H-041 用 `position_multiplier`（2026-10-08 B-4 审计确认不存在）、H-040 用「AXTX 浮亏」列（results 明示 features/portfolio_features 无此列）；`verify_hypotheses.py --help` 已把三者列入「挂起（数据缺失/样本不足）」，但 blocked-registry 无登记 | **口径修订**：H-035/H-041 的 position_multiplier 按 B-4/WT-01 口径映射真实列（zone/core_position），H-040 明确 AXTX 浮亏数据来源（Data/positions.csv 持仓快照）或标 pending-revise；修订完成前不得按字面跑 | ✅ **2026-10-10 修订完成**（commit 8b3e2a1）：H-035/H-041 position_multiplier → core_position（真实列）、布尔位/恐惧贪婪数值 → extreme/fg_index（H-037 同源一并修订）；H-040 数据源改为 Data/positions.csv（cost 88.499 vs price 26.47 → 浮亏 **-70.1%**，纠正原登记 -25.1% 的现价当成本错误）。假说状态 open，待按修订口径验证 |

## C 类：回测恢复后解锁（第二层 + 远期）— 依赖已解除，可实施

> 2026-10-08：A-2（baseline.json）已产出，C 系列依赖解除，状态由 ⚪ 转为可实施（待按优先级逐个推进）。
>
> 2026-10-08（晚）：C-9 / C-1 / C-7 已落地（842 passed 全绿）。C-1 变体实验给出**负结果**（V-H7 三标的 OOS 均不采纳，如实登记）。

| 编号 | 事项 | 依赖 | 状态 |
|---|---|---|---|
| C-1 | 变体实验设施 `evolve_variant.py`（adopted 假说→VARIANTS 草稿+等价性守卫） | A-2 ✅ | ✅ **2026-10-08 完成**：variants.py（B0+V-H7 纯计算）+ evolve_variant.py（等价性守卫/B0 相对差 <5e-5/OOS 对比/提案草稿）+ test_variant_guard.py 4 passed；**V-H7 OOS 三标的均不采纳**（TQQQ 38.6→27.0 / SOXL 95.1→65.1 / UPRO 26.0→18.3；回撤除 SOXL 外有改善）→ 提案草稿 evolution/experiments/variant_h007_2026-10-08.md；**裁决（用户）2026-10-08：Y 纳入 VARIANTS 长期观察（不入生产），不升级提案；季度 walk-forward（C-5）重检** |
| C-2 | 变更提案自动化（OOS 不劣化→自动生成提案） | A-2 ✅ | ✅ **2026-10-08 完成**：evolve_propose.py（复用 C-1 变体+守卫；确定性判定：OOS 年化>B0 且回撤<=B0 ⇒ 提案/否则不采纳；第 8 条模板：依据/口径/回测证据/判定/风险/审批位）→ evolution/proposals/（V-H7 三标的自动生成"不采纳"记录，守卫通过） |
| C-3 | 人工审批闭环（提案推飞书→签字→动 config.py） | C-2 | ✅ **2026-10-08 完成**：evolve_approve.py（list 扫描未审批提案 / --status Y\|N\|Z 回写审批位 / --log 写决策日志）→ V-H7 三份提案已全部审批（Z 观察，与用户裁决一致） | ✅ 完成（增强项：飞书推送对接可后续做） |
| C-4 | 阶段 6 复盘/周报自动化 | C 系列 | ✅ **2026-10-08 完成**：evolve_weekly.py（假说变更/提案/审批/因子/数据缺口/风险快照）→ evolution/weekly/weekly-2026-W41.md；--push 接 feishu_send | ✅ 完成 |
| C-5 | E2 告警后季度 walk-forward 重标定流程 | A-2 ✅ | ✅ **2026-10-08 完成**：evolve_walkforward.py（季度滚动窗 B0 vs 变体，三档判定：不劣化/等价/劣化；≥60% 窗维持观察）→ evolution/walkforward-report.md；**V-H7 首轮重检：三标的 34~35/40 窗不劣化/等价 ⇒ 维持观察**（修正等价口径后结论反转，与裁决一致） | ✅ 完成（2026-10-09 已补跑全变体重检：V-CORR 27/27/26 维持 / V-MA 仅 TQQQ / V-ATR、V-VOL 建议归档；launchd 季度调度已设 1/4/7/10 月 1 日 08:00） |
| C-6 | E3 执行确认流（目标仓位确认→人工审批→一键执行） | A-2 ✅ | ✅ **2026-10-08 完成**：execution_confirm.py（持仓快照+守猪待兔系数+个性化买卖线 → 确认清单 execution/confirm-*.md；--finalize 输出可执行指令文本，系统不自动下单） | 可实施 |
| C-7 | E4 因子库扩展（LLM 因子草稿→数据裁判检验→入库） | A-2 ✅ | ✅ **2026-10-08 完成**：新增 F-007 守猪待兔温度 / F-008 极恐标记（zone==0，事件研究：20 日 +1.3pp / 40 日 +2.8pp 超额，5/10 日弱）/ F-009 资金费率；F-007/F-009 样本不足登记积累中；scripts/factor_screen_extend.py |
| C-8 | E5 Copilot 扩展（归因/假说状态/漂移监控问答） | 已由 D-3 覆盖 | ✅（2026-10-06 前完成） |
| C-9 | 个股指数扩池-策略侧（OBSERVE_SYMBOLS 数据已就绪，白名单未动） | A-2 ✅ | ✅ **2026-10-08 完成**：SIGNAL_UNDERLYING_MAP 增 NVDL/TSLL/FAS/TNA/FNGU/SQQQ 映射（FNGU/SQQQ→QQQ 近似底层已声明）；signal_wide 只补 SHOUTU_SYMBOLS 底层；observe_screen.py → Data/observe_screen_2026-10-08.md（NVDL 64.4 贪婪/FAS 21.8 恐惧/TNA 32.3 恐惧/SQQQ 反向标注）；71 passed |
| C-10 | 实盘-回测归因校验（预测 vs 实际每日归因） | A-2 ✅ | ✅ **2026-10-08 完成**：attribution_check.py（zone→次日收益回测归因 + 持仓快照实盘归因）→ evolution/attribution-report.md；**发现：恐惧档次日收益均值显著高于贪婪档（TQQQ +0.46% vs +0.09%，SOXL +0.93% vs +0.05%，UPRO +0.31% vs +0.06%），与 F-008 事件研究同向** | ✅ 完成 |
| C-11 | E2 假说绩效衰减自动降级（弱假说归档） | C-1 | ✅ **2026-10-08 完成**：evolve_decay.py（确定性判据：近窗衰减 ≥2/4 horizon → decayed；样本不足 → accumulating；假说监控表）→ evolution/decay-report.md；首轮扫描：F-007/F-009 accumulating、F-001/F-003~F-006 近窗衰减 1/4 维持、假说 adopted 走 C-5 季度重检；hypotheses.md 状态机已扩展 |

## D 类：可先做（不依赖回测，本表跟踪推进）

| 编号 | 事项 | 现状 | 状态 |
|---|---|---|---|
| D-1 | 数学建模落地（HMM/马尔可夫/EVT/贝叶斯更新） | **2026-10-06 已完成**（fg_system/models/ + scripts/model_report.py，见 2026-10-06-数学模型落地.md） | ✅ |
| D-2 | E4 因子流程文档化 | **2026-10-06 完成**：factors.md 登记表(F-001~F-006) + 首批候选因子 IC/IR 初检（scripts/factor_screen.py → evolution/factor-screen-results.md，NVDL/FAS/TNA/FNGU 达标、SQQQ 反向语义核验通过、TSLL 弱） | ✅ |
| D-3 | E5 问答扩展（归因/假说状态/漂移监控） | fg-qa skill 已支持多问题类型 | ✅（2026-10-06 前） |

## 已解除区（留痕）

| 原编号 | 事项 | 解除依据 | 解除日期 |
|---|---|---|---|
| A-1 | 补传回测文件 | issue #3 关闭：19 文件补传（ce44ae1）+ pytest 838 passed / 0 failed / 0 skipped（831f450） | 2026-10-08 |
| A-2 | 恢复回测基准 | evolution/baseline.json 产出（scripts/evolve_baseline.py，全区间/逐年/IS-OOS/归因） | 2026-10-08 |
| A-3 | 解锁 H-005 / H-007 验证 | portfolio_features.csv 重建 + verify_hypotheses.py 验证（H-005 rejected / H-007 adopted） | 2026-10-08 |
| A-4 | 对齐进化就绪度 | evolution-plan.md 第 7 节修订记录 | 2026-10-08 |
| — | 看板数据停更（代理按域名分流+新鲜度护栏） | e418abe/a314be1，2026-10-06 | 2026-10-06 |
| — | 不依赖回测的扩展项清零 | roadmap 基线，2026-10-02 | 2026-10-02 |

---

> 维护提示：A 类已全部解除；B 类剩数据积累（时间）与订阅依赖；C 类依赖已解除可逐个实施。所有"解锁"动作都必须走既有纪律（数据裁判、人工审批、OOS 禁直接调参）。H-010~H-021 引用虚构列，禁止在修订前按"第 N 列"做统计。
