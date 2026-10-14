# 2026-10-14 Kalshi KXFED：fed 因子第二数据源接入

- 状态：✅ 完成
- 类型：P1 功能落地（数据源增强 · fed 因子交叉验证）
- 前置：`scripts/fetch_fedwatch.py`（CME FedWatch，fed 因子第一源）

## 背景

用户提出评估 Polymarket / Kalshi 预测市场免费数据接入。调研 + 最小可行性验证结论：
- 两平台市场数据均**免费、免 key**（Kalshi `/series`、`/markets` 公开；Polymarket Gamma/Data/CLOB 读公开）；
- **国内直连不可达**（HTTP 000），必须走本机代理 127.0.0.1:7890（macOS 系统代理）；
- Kalshi `KXFED` 系列按 FOMC 会议分事件、按目标利率档位拆二元合约（YES = 上限 ≥ strike%），
  可直接映射 ease/hold/hike 三概率，口径与 CME FedWatch 对齐。

实测交叉验证（2026-10-14，会议 2026-10-28）：

| 口径 | CME FedWatch（现有） | Kalshi KXFED（本次） | 差异 |
|---|---|---|---|
| 加息概率 | 22.7%（fed 因子 = 23.0） | 21.0% | -1.7pp |
| 按兵不动 | 77.3% | 78.5% | +1.2pp |
| 降息 | 0.0% | 0.5% | +0.5pp |

## 做了什么

1. **新增 `scripts/fetch_kalshi_fed.py`**：
   - REST 翻页拉取 `GET /markets?series_ticker=KXFED&status=open`（cursor 分页，urllib 走代理 7890）；
   - 取 close_time 最早事件为"下一次会议"；当前上限 c = 使 P(≥s) ≥ 0.90 的最大档位；
   - 概率 = yes 买/卖中间价；`ease = 1 - P(≥c)`、`hike = P(≥c+0.25)`、`hold = P(≥c) - P(≥c+0.25)`；
   - 输出 `Data/raw/kalshi_fed.csv`（`date,meeting,ease_pct,hold_pct,hike_pct,src`，同一天幂等，失败仅告警不覆盖旧数据）；
   - CLI：`--debug` 明细 / `--dry-run`。
2. **新增 `tests/test_fetch_kalshi_fed.py`**（6 条，不联网）：正常解析、空数据、无高置信档、单档不足、同日幂等、跨日保留。
3. **接线每日任务**：`com.xingguo.fg-daily.plist`（05:30 全链路）在 `fetch_fedwatch.py` 后追加 `fetch_kalshi_fed.py`，已 `launchctl unload/load` 重载并验证。

## 验证

- 脚本真实运行 exit=0，CSV 已写入（2026-10-14 行）；
- 增量 pytest：6 passed；
- plist 语法 `plutil -lint` OK，launchctl 注册正常。

## 后续（未做）

- Polymarket 宏观事件合约（gamma/data API 走同一代理）可作第三源，待用户按需立项；
- Kalshi 数据暂只作 fed 因子交叉验证参考，**未改变 fed 因子计算口径**（CME 仍为主源）；
- 如需纳入 E4 因子引擎（如"双源分歧"信号），走假说登记流程另行评估。
