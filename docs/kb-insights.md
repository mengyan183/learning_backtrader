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
