# 知识库沉淀与系统优化方向（kb-insights）

> 归纳时间：2026-10-06 · 数据：Data/kb/chroma（ChromaDB 集合 yt_trading）
> 本文件是把 YouTube 知识库内容转化为贪恐系统优化方向的**总账**，
> 已落地的优化见「落地状态」列。

## 1. 知识库概况

- 270 个视频 / 9 个交易频道（每频道 30 条）/ 166 条带上传日期（61%，剩余由每日 cron 补拉）
- 知识块 2786 条（ChromaDB），embedding = Ollama bge-m3
- 检索入口：scripts/kb_search.py（支持 --since N / --channel A,B）；异动告警与简报已接入

## 2. 主题分布（标题关键词聚类 + 人工校正）

| 主题 | 视频数 | 主要频道 |
|---|---|---|
| 交易心理 | 60 | Duomo、ChatWithTraders |
| 技术分析 | 53 | TradingChannel、SecretMindset |
| 宏观政策 | 50 | PBoyle、ThePlainBagel |
| 策略方法 | 35 | RaynerTeo、TradingChannel |
| 市场结构 | 23 | BenFelix、QuantPy |
| 投资理念 | 22 | BenFelix、ThePlainBagel |
| 风控仓位 | 11 | RaynerTeo、ChatWithTraders |
| 量化回测 | 11 | QuantPy |

## 3. 频道画像

| 频道 | 定位 | 系统价值 |
|---|---|---|
| Duomo | 交易心理/纪律/执行 | 极端档位行为校验 |
| SecretMindset | 订单流/供需/日内 | 盘中结构信号 |
| TradingChannel | 价格行为/K线教学 | 技术面补充 |
| RaynerTeo | 策略+数学+风控 | 仓位管理量化规则 |
| ChatWithTraders | 大师访谈/风控哲学 | 熔断/回撤规则经验 |
| PBoyle / ThePlainBagel | 宏观/债务/泡沫/央行 | Fed 因子深化 |
| BenFelix | ETF/行为金融/理念 | 杠杆风险、投资边界 |
| QuantPy | 量化/回测/随机建模 | 回测方法论、情景模拟 |

## 4. 优化方向总账（P1-P7）

| # | 方向 | 来源 | 落地内容 | 状态 |
|---|---|---|---|---|
| P1 | 风控仓位 | RaynerTeo《Math Behind》/Peter Brandt | 1%风险规则建议仓位上限（净值×1%/2×ATR20）+ 连亏 kill switch；持仓页 + 简报 | ✅ fg_system/risk.py、report.py、invest_research.py |
| P2 | 极端档位行为检查清单 | Duomo / Market Wizards | 极度恐惧/贪婪档位简报附 FOMO/恐慌割肉检查清单 | ✅ invest_research.py behavior_checklist |
| P3 | 宏观事件日历 | PBoyle/PlainBagel | CPI/非农事件窗口（FRED 官方日程）+ FedWatch 概率变动提示 | ✅ config.MACRO_EVENTS、fed.py |
| P4 | 个股趋势结构 | TradingChannel/价格行为 | 持仓卡 200EMA 方向 + 近20日支撑/阻力带 | ✅ report.py h-trend |
| P5 | 风险标签 | BenFelix 杠杆ETF | 杠杆 ETF 衰减/清算标签 + 加密杠杆标签 | ✅ risk.py risk_tags、report.py |
| P6 | 绩效规范+压力测试 | QuantPy | deflated Sharpe/样本外规范文档 + Monte Carlo 熔断压力脚本 | ✅ docs/performance-eval.md、scripts/mc_pressure_test.py |
| P7 | 系统边界文档 | BenFelix 理念 | 只做多头仓位管理边界 + buy-the-dip 规则 + 信号分级 | ✅ docs/system-boundary.md |

## 5. 已知缺口（后续可做）

- P6 的 deflated Sharpe 自动化脚本需 E3 回测文件恢复后接入（backtest_check.py）
- 宏观"债务/泡沫压力"备选子信号：需要免费数据源评估（远期）
- 知识库自动更新（launchd com.xingguo.kb-update）每日增量补拉日期

## 6. 外部资源库沉淀（2026-10-08，来源 github.com/codeman008/Financial_freedom）

> 该仓库是「最全赚钱投资指南」资源清单（6k stars）：16 本投资经典书 + 16 部财经纪录片 + 23 个美股频道 + Web3 工具集。
> 以下只沉淀**与贪恐系统直接相关**的部分，按可用性分级。

### 6.1 直接可用的数据源（📌 高价值）

| 资源 | 用途 | 与系统关联 | 落地建议 |
|---|---|---|---|
| lookintobitcoin.com | BTC 全模型聚合：Fear & Greed、Rainbow、Stock-to-Flow、MVRV、Hash Rate、Whale Index | **与贪恐系统同源**（守猪待兔 FNG 即其 Fear & Greed 指标） | 可作 shoutu_fng 的交叉校验源（免费 API，无需 key）；Rainbow/MVRV 可做加密持仓的估值带参考 |
| en.macromicro.me | 宏观数据可视化（股/汇/债/商全覆盖，分行业轮动） | Fed 因子、宏观事件日历深化 | 补 FRED 之外的免费宏观源；行业轮动图可作 breadth 因子观察 |
| finviz.com | 美股最佳选股器（screener） | 个股池扩池/板块强弱 | 辅助 P4 个股筛选与 sector breadth |
| seekingalpha.com | 美股讨论/公司跟踪 | 个股研究 | 供简报「公司观点」引用（注意其文章质量分层，学术研究称可预测收益，付费文章不必买） |

### 6.2 知识库频道候选（🟡 可并入 kb_build CHANNELS）

仓库推荐的 23 个美股频道中，与现有 9 频道互补、值得后续抓字幕入库的：

| 频道 | 定位 | 与系统价值 |
|---|---|---|
| Beckie Analysis | 日内/短线 + 技术分析（支撑阻力/指标） | 技术面补充（与 TradingChannel 互补） |
| Jason Lee 美股技术分析 | 量价关系/均线/主力成本区 | P4 趋势结构深化 |
| Victor 美股投资频道 | Gann 系统 + 顺势交易 + 周度预测 | 中期趋势参考（注意 Gann 神秘学成分，仅作参考） |
| Shiye 全球财经 | 新闻信息汇总解读 + 实盘止盈止损目标 | 简报新闻联动源候选 |
| C&K GO! | 宏观洞察 + 独立思维 | 宏观因子观察 |
| 刘翔的投资频道 | 多空双面分析 + 独立思维 | 简报「多空对照」方法论来源 |

> ⚠️ 中文字幕频道抓取需验证字幕可得性；采用前先在 kb_build CHANNELS 加白名单试抓一条。
> ⚠️ 上述频道内容含个股推荐与主观判断，入库后信号分级一律 🟡 研究参考。

### 6.3 方法论沉淀（书单要点，供 fg-qa 知识库引用）

| 书 | 核心要点 | 与系统关联 |
|---|---|---|
| 《聪明的投资者》（格雷厄姆） | 防御型/进取型投资者组合策略；安全边际 | CORE_CAP/现金缓冲纪律的经典依据 |
| 《投资最重要的事》（霍华德·马克斯） | 第二层思维、价格 vs 价值、逆向、等待机会 | 贪恐逆向逻辑的理论背书（极端恐惧=机会） |
| 《穷查理宝典》（芒格） | 多元思维模型、能力圈、避免愚蠢 | 系统「宁可中止不可乱覆盖」纪律来源 |
| 《乌合之众》（勒庞） | 群体心理、情绪传染 | 贪恐指数的心理学根基（恐惧/贪婪即群体情绪） |
| 《资产配置的艺术》（达斯特） | 股票/债券/现金/黄金/地产多资产组合 | 35% 永久现金缓冲、多市场核心仓的理论来源 |
| 《怎样选择成长股》（费雪） | 成长股 15 要点、长期持有 | 个股池选股标准参考 |
| 《股市长线法宝》（西格尔） | 股票长期回报统计、历史回测 | 回测基准、长期持仓纪律 |

### 6.4 工具类（加密持仓相关，📌 已有 OKX 链路）

| 工具 | 用途 | 备注 |
|---|---|---|
| CoinGecko / CoinMarketCap | 行情 + 排名 + 数据 | 行情兜底源 |
| DefiLlama / Token Terminal | DeFi 数据、加密财务指标 | 远期：加密标的 P/S 估值观察 |
| TokenUnlocks | 代币解锁事件日历 | **可接入宏观事件日历**（解锁 = 潜在抛压事件） |
| StakingRewards | 质押数据 | 远期观察 |

## 7. 从仓库沉淀出的可落地方向（待排期）

| # | 方向 | 来源 | 落地内容 | 状态 |
|---|---|---|---|---|
| Q1 | lookintobitcoin 交叉校验 | 6.1 | alternative.me 市场级 FNG（lookintobitcoin 同源，官方 API 需订阅）→ `scripts/fetch_fng_altme.py` → `Data/raw/fng_altme.csv`，接入 `shoutu_daily.sh` 可选块（不改 RC） | ✅ 2026-10-08 |
| Q2 | TokenUnlocks 解锁日历 | 6.4 | 加密持仓的解锁抛压事件入 MACRO_EVENTS | ⛔ 受阻（2026-10-08）：官方 API 需 key（代理可达但 401）；Messari 无鉴权端点不可达；当前唯一加密持仓 BTC-USDT 无代币解锁概念 → 降级为手动登记观察位，持仓扩到有 unlock 的代币时再启用 |
| Q3 | 频道扩容 | 6.2 | 先试抓 Beckie Analysis 一条字幕验证可得性，通过后入 CHANNELS | 待排期 |
| Q4 | 书单要点入 fg-qa | 6.3 | fg-qa「方法论」路由增加书单引用（标注来源：Financial_freedom 书单） | 待排期 |
