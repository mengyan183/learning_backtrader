# learning_backtrader

个人开发的美股贪婪恐惧指数交易系统（含加密子系统、守猪待兔情绪对照、AI 进化闭环）。

> 状态标签：`生产运行中`（Dashboard / 每日自动链 / 飞书推送均在线）· 开发环境：Mac + 公司电脑双端（GitHub private 同步）

---

## 一、系统是什么

- **核心**：市场级贪婪恐惧指数 `fg_index`（0-100，五档：极度恐惧/恐惧/中性/贪婪/极度贪婪），驱动目标仓位 `target_position`（0-100%），规则带：`ZONE_EDGES=[20,40,60,80]`
- **信号**：波动率 VIX / 期限利差 term / 价格动量 price / 市场广度 breadth（四因子 → 756 日滚动百分位合成）
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

## 三、AI 进化闭环（六阶段）

① LLM 假说体检 → ② 基准回测（backtest runner + baseline）→ ③ LLM 体检（已自动化）→ ④ 假说验证（已自动化）→ ⑤ 变体验证（OOS 不劣化）→ ⑥ 门控采纳（人工审批后才动 `config.py`）

- **每日自动链**（05:30，launchd `com.xingguo.fg-daily`）：同步持仓 → 假说重检 `evolve_h001.py` → 复评 `evolve_review.py` → 投研简报 `invest_research.py` → 漂移监控 `drift_monitor.py --push-alert` → 情绪子信号 `fetch_sentiment.py`
- **假说登记**：`docs/hypotheses.md`（H-001~H-009，自动重检每交易日更新观察点）
- **⛔ 当前阻塞**：回测裁判 `fg_system/backtest/*`（20 文件）待公司电脑补传（issue #3）——解锁 baseline 与 H-005/H-007

## 四、扩展规划 E1~E5（已交付部分）

| 编号 | 名称 | 状态 | 说明 |
|---|---|---|---|
| **E1** | 多智能体投研流水线 | ✅ 已上线 | `scripts/invest_research.py`：GLM 情绪 → NIM 归因 → 本地裁判 → 飞书推送 |
| **E2** | 概念漂移监控 | ✅ 已上线 | `scripts/drift_monitor.py`：滚动 IC / ICIR 衰减检测（逆向指标语义），异常才推飞书 |
| **E3** | 执行确认流 | ⏳ 等回测 | 目标仓位飞书确认 → 审批 → 富途执行 |
| **E4** | AI 因子引擎 | ✅ 地基完成 | `fg_system/factors/eval.py`：滚动 IC / ICIR / 多前瞻衰减 |
| **E5** | Copilot 持仓问答 | ✅ 已接通 | `scripts/portfolio_qa.py` + OpenClaw 技能 `portfolio-qa`（飞书/网页直接问"持仓/风险"） |

**AI 工具分工**（本机部署）：
- **OpenClaw**（网关 18789，网页 + 飞书）：默认 GLM 云端（`litellm/hermes-agent`），本地 3b 可选；E5 问答走这里
- **Hermes**（API 8642）：主用 GLM，备用 NVIDIA NIM
- **Harness**（DeepSeek dsh，3080）：投研归因
- **Ollama**（11434）：本地模型（qwen2.5-coder 3b/1.5b、internlm2:1.8b 等）

## 五、近期交付记录（2026-10-02）

- E1/E5 扩展完成并实测（飞书推送 + 技能执行成功）
- 全部 5 项不依赖回测任务完成：就绪度对齐检查单 / IC-IR 框架 / 漂移监控 / 情绪子信号（VIX 全历史 + OKX 资金费率）/ 观察池扩池（NVDL/TSLL/FNGU/FAS/TNA/SQQQ 入库）
- 系统指数与 SPY 未来 20 日收益稳定负相关（IC -0.36）——逆向指标特性已固化为监控语义

## 六、测试

```bash
.venv/bin/python -m pytest tests/ -q          # 完整回归（616 passed / 25 skipped 基线）
```

详细规划与变更记录见 `docs/roadmap.md`。
