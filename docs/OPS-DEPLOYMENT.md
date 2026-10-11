# 贪恐系统（learning_backtrader）运维部署手册

> 版本：2026-10-11 · 适用机器：Mac（主运行机）+ Windows（公司开发机，经飞书同步）
> 仓库根：`/Users/xingguo/learning_backtrader` · 主线：GitHub `mengyan183/learning_backtrader` branch `main`

---

## 1. 系统概览

```
┌────────────── 数据层 ──────────────┐
│ prices/indices（行情）  fedwatch（利率概率）
│ shoutu_fng（守猪待兔）  putcall（P/C）
│ sentiment/stablecoin/FRED（情绪子信号/宏观）
└──────────────┬───────────────────┘
               ▼
┌────────────── 因子与合成 ──────────┐
│ 六因子 vix/term/price/breadth/fed/putcall
│ → 0-100 贪恐指数 fg_index + 五档 zone
│ → 仓位指令（buy/hold/sell + 熔断）
└──────────────┬───────────────────┘
               ▼
┌────────── 服务与产物 ──────────────┐
│ dashboard(8000)  futu_realtime(行情订阅)
│ 每日简报 invest_brief_*.md → 飞书
│ 漂移监控/数据质量闸门 → 飞书告警
└──────────────┬───────────────────┘
               ▼
┌────────── 调度与同步 ──────────────┐
│ launchd 6 任务（每日/季度/周）
│ 飞书 fg-sync 分片同步（Windows→Mac）
└────────────────────────────────────┘
```

## 2. 运行环境

| 项 | 值 |
|---|---|
| 操作系统 | macOS（Apple Silicon 本机验证） |
| Python | 仓库 venv `.venv/bin/python`（Python 3.10，勿用系统 python3 跑生产脚本） |
| 依赖 | `pip install -r requirements.txt`（如无该文件则按 import 缺失逐个补） |
| 模型服务 | Hermes（NIM 深度归因/投研裁判，`hermes dashboard`）+ Ollama（kb 嵌入 bge-m3、本地小模型） |
| 端口 | 8000（dashboard）；Ollama 11434；frpc/Lolia 隧道（飞书回调链路） |

## 3. 常驻服务与启动方式

| 服务 | 命令 | 说明 |
|---|---|---|
| 看盘 dashboard | `.venv/bin/python scripts/serve_dashboard.py --host 0.0.0.0 --port 8000` | 本机 http://127.0.0.1:8000；手机同 Wi-Fi 可访问 |
| 实时行情 | `.venv/bin/python -u scripts/futu_realtime.py` | 富途订阅，盘中预览数据源 |
| Hermes | `/usr/local/bin/hermes dashboard` | NIM/Gateway，投研流水线模型通道 |
| Ollama | `ollama serve` | 知识库嵌入/本地模型 |

**launchd 托管（全部已注册，`~/Library/LaunchAgents/`）**：

| plist | 频率 | 动作 | 日志 |
|---|---|---|---|
| `com.xingguo.fg-dashboard` | RunAtLoad | dashboard 8000 | 无（前台看） |
| `com.xingguo.fg-realtime` | RunAtLoad | futu_realtime 行情订阅 | 无（前台看） |
| `com.xingguo.fg-daily` | 每日 05:30 | 全量数据同步+简报+监控（见 §5） | `/tmp/fg_daily.log` |
| `com.fg.shoutu-daily` | 每日 06:30 | 守猪待兔历史通道补拉 | `/tmp/shoutu_daily.log` |
| `com.fg.quarterly-walkforward` | 1/4/7/10 月 1 日 08:00 | 季度 walk-forward 重标定 | `/tmp/quarterly_walkforward.log` |
| `com.xingguo.fg-kb-update` | 每周日 03:00 | 知识库字幕抓取更新（ChromaDB） | `/tmp/kb_update.log` |

**launchd 管理命令**：

```bash
launchctl list | grep fg          # 查看全部 fg 任务与 PID
launchctl unload ~/Library/LaunchAgents/com.xingguo.fg-dashboard.plist   # 停
launchctl load   ~/Library/LaunchAgents/com.xingguo.fg-dashboard.plist   # 起
```

## 4. 核心数据文件（Data/）

| 文件 | 内容 | 更新 |
|---|---|---|
| `Data/features.csv` | 每日因子分/指数/档位/熔断标记 | 每日 05:30 pipeline |
| `Data/state.json` | 熔断/弹药/极端日状态 | 每日 pipeline |
| `Data/positions.csv` / `accounts.csv` | 持仓/账户快照 | 每日同步持仓 |
| `Data/raw/prices.csv`、`indices_*.csv` | 行情/指数历史 | 每日 update_prices/indices |
| `Data/raw/fedwatch.csv` | CME 利率概率 | 每日 fetch_fedwatch |
| `Data/raw/shoutu_fng.csv` | 守猪待兔市场温度 | 每日 shoutu_daily |
| `Data/raw/putcall.csv` | CBOE P/C ratio | 每日 fetch_sentiment |
| `Data/raw/stablecoin_usage.csv` | 稳定币使用效率 | 每日 fetch_stablecoin_usage --incremental |
| `Data/raw/fred_DFF.csv` / `fred_T10Y2Y.csv` | FRED 官方宏观（1954 至今） | 手动/增量 fetch_fred.py |
| `Data/human30.json` | Human 3.0 打卡记录 | 打卡时写 |
| `Data/invest_brief_YYYY-MM-DD.md` | 每日投研简报 | 每日 05:30 |

## 5. 每日链路（05:30 自动，等价于手动执行）

```bash
cd /Users/xingguo/learning_backtrader
FG_SYNC_MODE=live .venv/bin/python scripts/fetch_fedwatch.py     # 1 利率概率
.venv/bin/python -c "from fg_system.data import fetch; fetch.update_prices(); fetch.update_indices()"  # 2 行情
.venv/bin/python scripts/fetch_shoutu_api.py                     # 3 守猪待兔
.venv/bin/python -c "from fg_system import pipeline; pipeline.run(write=True)"  # 4 因子+指数+档位
.venv/bin/python scripts/check_freshness.py                      # 5 数据新鲜度闸门
FG_SYNC_MODE=live .venv/bin/python scripts/sync_positions.py     # 6 持仓同步
.venv/bin/python scripts/evolve_h001.py                          # 7 H-001 观察点
.venv/bin/python scripts/evolve_review.py                        # 8 假说复评
FEISHU_OPEN_ID=ou_xxx .venv/bin/python scripts/invest_research.py # 9 投研简报（推飞书）
.venv/bin/python scripts/drift_monitor.py --push-alert           # 10 漂移/质量告警
.venv/bin/python scripts/fetch_sentiment.py                      # 11 情绪子信号
.venv/bin/python scripts/fetch_stablecoin_usage.py --incremental # 12 稳定币
```

**手动触发**（排查/补跑）：直接按上表逐条执行，或 `bash -lc 'cd /Users/xingguo/learning_backtrader; ...'`。

## 6. 测试与发布（硬纪律）

```bash
cd /Users/xingguo/learning_backtrader
.venv/bin/python -m pytest tests/test_<改动项>.py -q   # 增量测试（<10s）
.venv/bin/python -m pytest -q                          # 全量回归（基线 1201 passed，约 3 分钟）
.venv/bin/python scripts/lookahead_audit.py             # 未来函数审计（PASS 才可提交）
git add <改动文件> && git commit -m "<类型>(<范围>): <描述>" && git push origin main
```

- **红线**：新改脚本不得含 `shift(-`（前视泄露）；RESEARCH_WHITELIST 变更需同步登记
- **生产改动**走第 8 条流程：先文档 → 改码 → OOS 回测裁判（`factor_backtest_probe.py` / `portfolio_backtest.py`）→ C-3 人工审批 → 才动 `config.py`
- **F 系列候选因子**：只注册评测池，不进合成权重，除非 M2.2 回测裁判 + 用户审批 Y

## 7. Windows ↔ Mac 同步链路（fg-sync）

```
Windows 打包（make_feishu_bundle.py 分片 ≤8KB）
  → 飞书「海外投资助手」机器人
  → Mac OpenClaw fg-sync skill（旁路落盘 ~/.openclaw/tmp/fg-sync-in/）
  → fg_sync_tool.py --quick --brief（聚合→解压→白名单→冲突→入库→pytest→回传）
  → git add/commit/push
```

- **白名单**：`fg_system, scripts, tests, evolution, docs` + 根级文件；`--full-repo` 跳过目录白名单但仍拒绝 `Data/`、密钥、`.git`、`node_modules`
- **手动还原**：`python3 scripts/restore_from_base64.py <消息文件>`（URL-safe base64 含 `-`/`_`，禁止手动解码）
- **已处理分片**：成功后自动清理；失败保留原文便于排查，修复后重跑同一命令

## 8. 常见故障排查

| 症状 | 排查路径 |
|---|---|
| 页面指数显示 NAN / tab 不可点 | dashboard 后端异常 → `ps aux \| grep serve_dashboard`；重启：`launchctl unload/load com.xingguo.fg-dashboard`；浏览器硬刷新 |
| 数据日期陈旧（features 尾行 >3 交易日） | 看 `/tmp/fg_daily.log` 尾 100 行定位失败步骤；手动重跑该步骤（§5） |
| 飞书简报/告警没发 | 检查 `FEISHU_OPEN_ID` 配置、`invest_research.py` 日志、飞书机器人是否在线；限流（429）自动退避重试 |
| 飞书同步无响应/超时 | openclaw 模型通道（Hermes/NIM）是否正常（`hermes dashboard`）；消息是否含完整 `###FG:` 分片标记 |
| 模型报 unavailable/HTTP 500 | Hermes 后端模型被改名/下线或限流 → 检查 openclaw 模型 fallback 链配置；等待几分钟重试 |
| 端口 8000 被占 | `lsof -i :8000` 找占用进程；kill 后重启 dashboard |
| 同步报「xz 损坏 / 非 xz」 | 打包端 `make_feishu_bundle.py` 产物校验失败 → 公司端重新打包发送，勿手动改 base64 |
| 同步报白名单拒绝 | 文件不在白名单 → 确认是否该入库；需全量同步用 `--full-repo` |
| 同步报冲突（未提交修改） | Mac 本地有未提交改动 → 先处理本地改动再重跑（skill 不自动覆盖） |
| 知识库检索空 | `kb_update.sh` 是否按时跑；`chromadb` 集合 yt_trading 是否存在；Ollama 是否在跑 |

## 9. 备份与恢复要点

- 仓库一切以 GitHub main 为准：Mac 本地 `git pull` 即可恢复代码
- 不可再生数据在 `Data/raw/`（prices/indices/shoutu 历史）——重装前备份整个 `Data/` 目录
- 模型配置：`~/.openclaw/openclaw.json`（飞书 appId/secret、模型通道）——勿提交进仓库
- launchd plist 全部在 `~/Library/LaunchAgents/`，重装后需重新 `launchctl load`

## 10. 相关文档

- `README.md`：快速上手
- `docs/roadmap.md`：迭代规划与状态
- `docs/decision-log.md`：全部决策记录
- `docs/2026-10-11-贪恐系统发展迭代规划.md`：规划 v1.0 全文
- `docs/factor-adoption-pipeline.md`：因子采纳通道（M2.2）
- `docs/human30.md`：Human 3.0 系统
- `docs/fg-sync-accelerate.md`：同步链路加速与坑
