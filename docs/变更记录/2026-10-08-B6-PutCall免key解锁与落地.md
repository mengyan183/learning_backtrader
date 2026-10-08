# 2026-10-08 B-6 Put-Call 免 key 解锁与落地

## 背景
B-6（E1 期权 Put-Call 情绪）原阻塞于 CBOE DataShop 付费订阅端点（系统暂用 VIX 代理）。
用户 2026-10-08 明确「要探」免 key 数据源（与不付费偏好一致）。

## 数据源探查结论（三选一，均已实测）
1. **CBOE 官方批量 CSV（最终采用，做 2006-11 → 2019-10 基底）**
   - `https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/{totalpc,indexpc,equitypc,etppc,vixpc,spxpc}.csv`
   - 国内直连、免 key、秒级下载；字段 `DATE, CALL(S), PUT(S), TOTAL, P/C Ratio`
   - 覆盖 2006-11-01 → 2019-10-04（3253 行）；2019-09 起 equity 改走页面，批量 CSV 停更
2. **CBOE Daily Market Statistics 页面（最终采用，做 2020-01 起近期）**
   - `https://www.cboe.com/us/options/market_statistics/daily/?dt=YYYY-MM-DD`
   - 免 key、国内直连；Next.js RSC payload 内嵌 `optionsData` JSON（括号配对提取）
   - optionsData 存在边界：2020-01-02 起有，2019-01-02 无；2024/2025 节假日返回无 optionsData（正常）
   - 单请求 4~9s（页面约 425KB），失败自动重试 2 次；并发 8 线程触发限流（大量 timeout），2 线程稳定
3. 已排除：`?format=json` / `/api/...` / `totalpc2024.csv`（403/404）、Cboe All Access API（需注册 key）、OANDA/oanor（实时 15 分钟延迟、无全史）、Yahoo 期权链自算（unofficial 可能失效）

## 落地内容
- `scripts/fetch_putcall.py`：逐日抓取（--since/--until/--out/--workers/失败重试 2 次）→ `Data/raw/putcall_daily_*.csv`
- `scripts/build_putcall.py`：官方 CSV 基底 + 逐日增量 → `Data/raw/putcall.csv`（3943 条，2006-11-01 → 2026-10-07）
- `scripts/fetch_sentiment.py`：并入 `putcall_total / putcall_equity / putcall_vix` 列（sentiment.csv 8 列）
- `scripts/putcall_factor_check.py`：E4 因子检验（total_ratio → SPY 次日收益，IC=Spearman，滚动 60 日 IR，五分位事件研究）→ `evolution/putcall-report.md`
- `scripts/shoutu_daily.sh`：每日链新增 putcall 增量块（--backfill 1，不改主 RC，可选）
- 修复：fetch_day 失败重试、pandas 版本不支持 `Rolling.corr(method=spearman)` → 显式循环 scipy spearmanr

## 检验结果（evolution/putcall-report.md，1449 样本 2016-09-26 → 2026-10-05）
- total_ratio 与次日收益 IC = 0.044（弱正）
- equity_ratio IC = 0.017
- 滚动 60 日 IC → IR = 0.58
- 事件研究（total_ratio 五分位 → 次日 SPY 收益均值）：
  | 分位 | 次日收益 |
  |---|---|
  | Q0 贪婪 | +0.01% |
  | Q2 | -0.00% |
  | Q4 恐慌 | +0.14% |
- 恐慌端次日收益 > 贪婪端 → 与 C-10 归因发现方向一致（恐惧→次日反弹）
- 信号分级：🟡 研究参考（单因子检验，未经回测裁判，**不进入合成权重**）

## 遗留
- 2020-01-01 前近期缺口：2019-10-07 → 2019-12-31（约 60 交易日，页面无 optionsData，未回溯）
- 2006-2019 基底仅 total/index/equity/etp 档（spx/vix 的 P/C 列在部分文件因编码/列名差异未并入——build 脚本 FILE_MAP 已含，按实际列名容错）
- 是否进入合成权重：待回测裁判（第二层回测恢复后走变体+审批）

---

## 追加（同日收尾）：抓取端点升级为 CBOE JSON + 全链路复验

- **升级**：`scripts/fetch_putcall.py` 数据源从「Daily 页面逐日抓取（?dt=YYYY-MM-DD，单请求 4~9s）」改为 **CBOE 按日 JSON 端点** `cdn.cboe.com/data/us/options/market_statistics/daily/{date}_daily_options`（单请求 <1s、响应稳定、六档比率 + 全市场成交量齐全），输出契约不变（putcall_daily_*.csv 7 比率列 + 成交量）。
- **复验（2026-10-08 实测）**：抓取 2026-10-01→10-07 共 5 交易日；`build_putcall.py` 重建 putcall.csv（2006-11-01→2026-10-07，七列全量，近期行六档无缺列）；`fetch_sentiment.py` 并入 → sentiment.csv 8 列，最新 2026-10-07 putcall_total=0.87 / putcall_equity=0.63 / putcall_vix=0.39。
- **数据可靠性**：历史基底来自 CBOE 官方批量 CSV（已入库 Data/raw/putcall/），近期来自官方 JSON——全部官方源、可追溯。
