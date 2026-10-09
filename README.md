# learning_backtrader

个人开发的美股贪婪恐惧指数交易系统（含加密子系统、守猪待兔情绪对照、AI 进化闭环）。

> 状态标签：`生产运行中`（Dashboard / 每日自动链 / 飞书推送均在线）· 开发环境：Mac + 公司电脑双端（GitHub private 同步，855 片大包链路已打通）

---

## 一、系统是什么

- **核心**：市场级贪婪恐惧指数 `fg_index`（0-100，五档：极度恐惧/恐惧/中性/贪婪/极度贪婪），驱动目标仓位 `target_position`（0-100%），规则带：`ZONE_EDGES=[20,40,60,80]`
- **信号**：波动率 VIX / 期限利差 term / 价格动量 price / 市场广度 breadth / Fed 政策（五因子 → 756 日滚动百分位合成）
- **白名单**（生产）：`SYMBOLS=["TQQQ","SOXL","UPRO"]`（3×杠杆 ETF，底层 QQQ/SOXX/SPY）
- **加密子系统**：三层递减上限（BTC 现货杠杆 + 高 Beta + 经营 Beta），`CRYPTO_SYMBOLS`
- **守猪待兔对照**：官方情绪 API（-100~100，官方三档：恐慌≤-60 / 中性 / 贪婪≥60，见 `docs/shoutu-zones.md`），与系统指数并排展示
- **纪律红线**：LLM 永不判决（回测 + pytest 唯一裁判）、OOS 禁调参、等价性守卫、第 8 条人工审批

## 二、快速上手

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python fg_system/pipeline.py --live    # 每日数据同步 + 指数更新（或由 launchd 05:30 自动）
.venv/bin/python scripts/serve_dashboard.py       # 本地看盘 http://127.0.0.1:8000（手机同 Wi-Fi 可访问）
```

- **数据**：`Data/raw/prices.csv`（26+6 观察池标的日线）、`Data/features.csv`（指数历史）、`Data/positions.csv`（持仓快照）
- **海外数据源**（Nasdaq/NIM/OKX）需代理：家里 Mac 用 `http://127.0.0.1:7890`，公司电脑用公司代理（`fg_system/data/fetch.py` 读 `config.PROXY`）
- **运维**：`docs/dashboard-ops.md`（服务重启/日志）、`docs/evolution-plan.md`（进化六阶段）、`docs/roadmap.md`（三层规划 + E1~E5 扩展）

## 三、AI 进化闭环（六阶段，已全自动）

① LLM 假说体检 → ② 基准回测（backtest runner + baseline）→ ③ LLM 体检（已自动化）→ ④ 假说验证（已自动化）→ ⑤ 变体验证（OOS 不劣化）→ ⑥ 门控采纳（人工审批后才动 `config.py`）

- **每日自动链**（05:30，launchd `com.xingguo.fg-daily`）：同步持仓 → 假说重检 `evolve_h001.py` → 复评 `evolve_review.py` → 投研简报 `invest_research.py` → 漂移监控 `drift_monitor.py --push-alert` → 情绪子信号 `fetch_sentiment.py`
- **季度自动重检**（launchd `com.fg.quarterly-walkforward`，1/4/7/10 月 1 日）：walk-forward 重标定
- **假说登记**：`docs/hypotheses.md`（H-001~H-023，自动重检每交易日更新观察点）
- **C 系列落地（2026-10-08 起）**：C-1 变体设施 / C-2 提案自动化 / C-3 审批闭环 / C-4 周报自动化 / C-5 季度 walk-forward / C-6 执行确认 / C-7 因子库扩展 / C-9 扩池策略侧 / C-10 实盘-回测归因 / C-11 绩效衰减降级
- **回测裁判已恢复**：`fg_system/backtest/*` 还原（issue #3 关闭），基准 `baseline.json` 已产出，H-005/H-007 已验证（rejected / adopted），V-H7 纳入长期观察

## 四、扩展能力（已交付）

| 模块 | 状态 | 说明 |
|---|---|---|
| **知识库** | ✅ 已上线 | YouTube 四频道字幕 → ChromaDB（yt_trading 集合）+ `scripts/kb_search.py` + kb-search 技能；外部仓库精华沉淀 `docs/kb-insights.md` |
| **数学模型包** | ✅ 已落地 | HMM 状态识别 / 档位马尔可夫矩阵 / EVT 阈值校准 / 贝叶斯假说信心（`fg_system/models/`，纯 numpy） |
| **毛选方法论** | ✅ 已沉淀 | `skills/mao-methodology/`：调查先行 / 矛盾分析 / 分阶段 / 聚焦（简报归因用矛盾分析法标注主要矛盾） |
| **量化选型** | ✅ 已决策 | vectorbt + PyPortfolioOpt（规则敏感性→经典量化→walk-forward→因子库化），明确不引入 Qlib/LEAN/vn.py（见 `docs/roadmap.md`） |
| **多因子情绪源** | ✅ 已接入 | 期权 Put-Call（B-6，免 key）+ 新闻/社媒情绪（B-7，NewsAPI）+ 资金费率（OKX）+ VIX 全历史（CBOE） |
| **双端同步链路** | ✅ 已打通 | 公司电脑打包 → 飞书分片（`###FG:`）→ OpenClaw 旁路还原 → Mac 仓库入库 + pytest + 回传；855 片大包已验证（117 文件） |

**AI 工具分工**（本机部署）：
- **OpenClaw**（网关，网页 + 飞书）：主模型 nvidia/deepseek-v4.1-flash（直连快），fallback zai/glm / litellm/hermes / ollama；E5 问答 + fg-sync 同步链路
- **Hermes**（API 8642）：主用 GLM，备用 NVIDIA NIM
- **Harness**（DeepSeek dsh，3080）：投研归因
- **Ollama**（11434）：本地模型（qwen2.5-coder 3b/1.5b 等）+ bge-m3 嵌入

## 五、近期交付记录（2026-10-09）

- **同步链路全程打通**：公司端 855 片大包（117 文件，含 mobile/ 工程与学习教程）经飞书旁路完整入库并推送，修复第 1/2 片截断（飞书 API 原文替换）、白名单误伤（`.gitignore`/`.gitattributes` 放行而 `.git` 目录仍拒）、git credential 僵尸进程（gh token 直推绕过 keychain）
- **C 系列全落地**：变体设施 / 提案自动化 / 审批闭环 / 周报 / 季度 walk-forward / 执行确认 / 归因校验 / 衰减降级（V-H7 三标的 OOS 均不采纳，负结果如实登记）
- **B 系列**：B-6 Put-Call 免 key 链路（IC 0.044 / IR 0.58）、B-7 新闻情绪（NewsAPI 免费 key）、B-4 假说口径修订（H-010~H-021）
- **Q1-Q4**：alternative.me 市场级 FNG 交叉校验 / TokenUnlocks 受阻登记 / BeckieAnalysis 中文字幕入库 / 方法论书单进 fg-qa
- **假说**：H-023 凯利公式 vs 规则仓位（半凯利上限，样本 <60 日不落地）
- 系统指数与 SPY 未来 20 日收益稳定负相关（IC -0.36）——逆向指标特性已固化为监控语义

## 六、测试

```bash
.venv/bin/python -m pytest tests/ -q          # 完整回归（850+ passed 基线，2026-10-09）
.venv/bin/python -m pytest tests/ -q --co     # 收集用例数
```

详细规划与变更记录见 `docs/roadmap.md`、`docs/blocked-registry.md`（未落地/受阻塞实现登记）、`docs/变更记录/`（全量 commit 索引）。
