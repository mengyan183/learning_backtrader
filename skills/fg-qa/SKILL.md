---
name: fg-qa
description: 用贪恐系统（learning_backtrader）本地数据回答贪恐指数、档位、持仓、买卖观望、账户与熔断问题。先查本地 CSV/JSON 再答，每个数字注明日期与来源文件；查不到就直说，禁止编造。触发词：贪恐、指数、档位、持仓、买不买、观望、信号、账户、熔断、守猪待兔。
---

# 贪恐系统问答：查了数据再答

## 这个 skill 干什么

用户问贪恐系统相关的问题（指数多少、什么档位、某标的买不买、账户亏多少、有没有熔断），先从本地数据文件把事实查出来，再按文件里的数字回答。

**查不到就别答。** 每个数字都要能指回某个文件；指不回去就直说「数据里没查到」，可以给口径说明，但不得编数字、编日期、编系数。

## 第 0 步：先看要不要马上停

- 问「熔断 / 极端 / 暴跌 / 要不要割」：先读 `Data/state.json` 的 `circuit_breaker` / `last_extreme_fear_date` 和 `Data/features.csv` 尾行的 `extreme` 标记，**先给风险状态**（熔断是否触发、最近极端恐惧日），再谈分析。
- 其余情况照下面走。

## 第 1 步：把数据拿到手

仓库根目录：`/Users/xingguo/learning_backtrader`（本地模式，直接读）。文件缺失就说「数据文件不存在（路径）」，不猜。

| 问题 | 文件 | 关键列 |
|---|---|---|
| 市场指数/档位/因子 | `Data/features.csv` | date, fg_index, zone, vix, term, price, breadth, fed, drawdown, circuit_breaker, extreme, warmup |
| 熔断/弹药/极端日 | `Data/state.json` | circuit_breaker, cb_trigger_index/date, cb_low_price, last_extreme_fear_date, ammo_released |
| 持仓明细 | `Data/positions.csv` | date, account, symbol, name, qty, price, cost, market_value, bucket |
| 账户 | `Data/accounts.csv` | date, account, net_value, cash, unrealized_pnl, day_pnl, note |
| 守猪待兔系数 | `Data/raw/shoutu_fng.csv` | date, symbol, value, price |
| 每日简报 | `Data/invest_brief_YYYY-MM-DD.md` | 全文 |

## 第 2 步：按问题类型路由

- **市场级**（「现在贪恐多少 / 什么档位 / 因子如何」）：取 `features.csv` **最后一行** → fg_index + zone（0 极度恐惧 / 1 恐惧 / 2 中性 / 3 贪婪 / 4 极度贪婪，边界 [20, 40, 60, 80]）→ 五因子 vix / term / price / breadth / fed → 与简报核对。
- **个股级**（「XX 标的是什么档位 / 买不买 / 观望」）：取 `positions.csv` **最新快照日期**该 symbol 行（qty / price / cost / market_value，浮盈 = (price−cost)/cost）；守猪待兔系数读 `shoutu_fng.csv` 同 symbol 最新 value（-100~100，官方三档：恐慌 ≤−60 / 中性 / 贪婪 ≥60，个股线见 `config.shoutu_lines`）；**系统个股系数** = `fg_system.factors.symbol.symbol_fg_index(sym, prices=Data/raw/prices.csv)`（底层数据不足如 CRCG/CONL 时回退市场级 fg_index，必须注明「回退市场级」）。买 / 观望 / 卖：恐慌 ≤ buy_line → 买入 / 中性 (buy_line, sell_line) → 观望 / 贪婪 ≥ sell_line → 卖出。
- **账户类**（「账户多少 / 现金 / 盈亏」）：取 `accounts.csv` 最新行；注明账户类型（stock / crypto）与快照日期。
- **简报类**（「今天简报 / 有什么消息」）：读最新 `invest_brief_*.md`，按原文摘录，不加工。

- **知识库类**（「怎么做止损 / 风险管理方法 / 交易策略 / 技术分析知识」）：运行 `.venv/bin/python scripts/kb_search.py "<问题>" -n 3`（ChromaDB 集合 yt_trading，Ollama bge-m3 嵌入，来源为 Duomo/SecretMindset/TradingChannel/RaynerTeo 四频道字幕）。命中则摘录要点，**逐条标注「来源：<频道>《<标题>》（YouTube 知识库）」**，信号分级一律 🟡 研究参考（教育观点，非系统数据，不替代系统买卖信号）；无命中则直说「知识库未检索到相关内容」，不编造。

- **扫描模式**（「扫一遍持仓 / 哪些在买入区 / 全部标的状态」）：取 `positions.csv` 最新快照的全部标的，**逐行**输出：symbol | 系统系数+档位 | 守猪待兔系数+档位 | 参考动作。双系统一致时直接给动作；不一致标注「⚠️ 双系统冲突」并分别说明两边的档位。浮盈浮亏按 (price−cost)/cost 一并列出。

## 第 3 步：查不到就直说

- `positions.csv` 最新快照滞后（如只有 2026-09-22）：回答时**必须注明快照日期**，不假装是今天。
- 某 symbol 不在 `shoutu_fng.csv`：直说「守猪待兔暂无该标的系数」。
- `features.csv` 尾行日期陈旧（>3 个交易日）：提示「指数可能停更，数据日期 X」。
- 扫描模式同理：全部持仓标的必须从快照逐行读取，不得只挑几只、不得补快照里没有的标的。

## 第 4 步：回答格式

每个数字带来源与日期，例如：

> 系统贪恐指数 54.9（2026-10-02，中性，来源 features.csv 尾行）；守猪待兔市场温度 36.6（恐惧，来源 shoutu_fng.csv 最新交易日均值）；TQQQ 持仓 195 股，成本 23.30、现价 29.51（+26.6%），守猪待兔系数 −15（恐慌）→ 参考动作：买入区。

- 因子/简报数字一并注明「数据日期」。
- 涉及建议时用「参考动作」措辞，不替用户做决定。
- **信号分级**（按系统规则标注强度）：🟢实盘动作 = 基于已采纳规则（如熔断/目标价/档位指令）；🟡研究参考 = 模型或因子分析，不直接执行；⚪待验证 = 假说（evolution/hypotheses.md 中的 H-xxx），仅观察不动作。拿不准就标 🟡。

