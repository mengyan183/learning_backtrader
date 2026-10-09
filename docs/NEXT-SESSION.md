# 下次会话先读这个（进度快照）

**更新**：2026-10-09 · **对应提交**：远端 main = `9bbd85f`（阶段1敏感性闭环 + V-VOL）

---

## 一句话现状

- **同步链路已全通** ✓：公司 Windows → 飞书「海外投资助手」机器人 → OpenClaw(Mac) `fg-sync` skill → 贪恐仓库，**855 片大包（117 文件）已全量入库并推送**；白名单误伤修复、push 卡死根治（详见 `docs/fg-sync-accelerate.md`）
- **GitHub 已统一为唯一主线** ✓：两条线合并完成（以远程为底 + 本地新增重放），issue #3 已关闭，A 类阻塞全解除，C 系列全落地
- **下一步**：等公司端补发内容（B 类数据积累中）；可随时接 C-5 季度节奏自动重检（已设 launchd）；README/进度文档已更新至 2026-10-09

---

## 当前状态基线（2026-10-09）

- ✅ **回测裁判恢复**：`fg_system/backtest/*` 还原（issue #3 关闭），`evolution/baseline.json` 产出（IS 至 2024-09-30 / OOS 自 2024-10-01）
- ✅ **A 类阻塞全解除**：H-005 rejected / H-007 adopted（2026-10-08 验证）
- ✅ **C 系列全落地**（2026-10-08）：C-1 变体设施 / C-2 提案自动化 / C-3 审批闭环 / C-4 周报自动化 / C-5 季度 walk-forward / C-6 执行确认 / C-7 因子库扩展 / C-9 扩池策略侧 / C-10 实盘-回测归因 / C-11 衰减降级；V-H7 三标的 OOS 均不采纳（负结果如实登记，裁决 Y 纳入长期观察）
- ✅ **B 系列**：B-6 Put-Call 免 key 链路（IC 0.044 / IR 0.58）/ B-7 新闻情绪（NewsAPI 免费 key）/ B-4 假说口径修订（H-010~H-021 按真实列重措辞）
- ✅ **Q1-Q4**：alternative.me 市场级 FNG 交叉校验 / TokenUnlocks 受阻登记 / BeckieAnalysis 中文字幕入库 / 方法论书单进 fg-qa
- ✅ **数学模型**：HMM 状态识别 / 档位马尔可夫矩阵 / EVT 阈值校准 / 贝叶斯假说信心（`fg_system/models/`，纯 numpy）
- ✅ **阶段 1️⃣ 敏感性分析四组闭环**（2026-10-09）：circuit（贪婪侧不敏感/恐惧侧极恐线5敏感）、zone（基准[20,40,60,80]稳健）、core（两端敏感、0.45居中合理）、trim（阈值未介入回测路径）；`evolution/sensitivity/` 四张表 + 汇总 README
- ✅ **阶段 2️⃣ 变体回测 V-H7/V-ATR/V-VOL**（2026-10-09）：三变体 OOS 均不采纳（收益损失>回撤收益，SOXL 上 V-VOL 回撤还恶化）⇒ **激进仓位即收益来源，防御降仓不划算**；等价性守卫全通过；提案草稿 evolution/experiments/variant_h007_2026-10-09.md
- ✅ **知识库**：YouTube 频道字幕 → ChromaDB（yt_trading）+ `scripts/kb_search.py` + kb-search 技能；外部仓库精华沉淀 `docs/kb-insights.md`
- ✅ **H-023** 凯利公式 vs 规则仓位假说（半凯利上限，样本 <60 日不落地）
- ✅ **量化选型决策**：vectorbt + PyPortfolioOpt（不引入 Qlib/LEAN/vn.py）
- ✅ **毛选方法论 skill**（mao-methodology）+ 简报归因主要矛盾标注
- ✅ **守猪待兔修复**：历史通道重建（fetch_shoutu.py），解除信号陈旧
- ✅ **新鲜度/简报/网页刷新系列修复**：freshness 交易日差≥1 天即触发、刷新触发 live 同步、简报减仓双引擎

## 双端同步链路（重点）

- **打包端**（公司 Windows）：`scripts/make_feishu_bundle.py` → `###FG:包名:序号/总数###…###FG:end###`（≤8KB/条）
- **接收端**（Mac）：feishu 插件旁路（`FG-SYNC BYPASS` 注入 monitor mjs）→ 落盘 `~/.openclaw/tmp/fg-sync-in/` → `fg_sync_tool.py --quick --brief` 单命令（聚合→解压→白名单→冲突→入库→pytest→回传）
- **白名单**：`ALLOWED_DIRS={fg_system,scripts,tests,evolution,docs}` + 根级文件（含 `.gitignore/.gitattributes`）；`--full-repo` 一次性全库授权（跳过目录白名单但保留 `_denied`：Data/、密钥、.git、node_modules、__pycache__）
- **已归档**：855 片 `sync_code_*.md` → `~/.openclaw/tmp/fg-sync-in/archive_synccode_20261009/`（避免重复解析）
- **已知坑**：URL-safe base64 含 `-`/`_` 手动解码必错；`.done` 幂等标记（内容 hash）；ingest 读目录下全部 .md

## 环境备忘

| 项 | 值 |
|---|---|
| 仓库 | `/Users/xingguo/learning_backtrader`；remote `github.com/mengyan183/learning_backtrader.git` |
| push 网络 | **必须走 ClashX 代理 7890**（直连被 TUN 劫持/超时）；有效推送：`export GH_TOKEN=$(gh auth token)` + `git -c http.proxy=http://127.0.0.1:7890 -c credential.helper= -c credential.helper="!f(){ echo \"username=x-access-token\"; echo \"password=$GH_TOKEN\"; }; f" push origin main`（绕过 osxkeychain 卡死） |
| credential | 系统级 CommandLineTools gitconfig 有 `osxkeychain`（会卡死 push）；repo 级 `!gh auth git-credential`（不带 fill） |
| 模型 | OpenClaw 主模型 `nvidia/deepseek-ai/deepseek-v4.1-flash`；fallback `[zai/glm-4.7-flash, litellm/hermes-agent, ollama/qwen2.5-coder:3b-64k]`（zai 有 429 史）；ollama 11434 |
| 网关 | OpenClaw 18789；重启 gateway 用 `kill -9 <PID>`（`launchctl kickstart` 静默失效）；日志 `~/Library/Logs/openclaw/gateway.log` |
| 飞书 | appId `cli_a93abe057178dbb4`（secret 在 `~/.openclaw/openclaw.json`）；chat_id `oc_a9306b326943821490184d073dae9a65`；API 基 `https://open.feishu.cn/open-apis` |
| 测试 | `.venv/bin/python -m pytest tests/ -q`（850+ passed 基线）；增量 `--quick` <10s |
| 数据源 | 海外需代理 7890（家里 Mac）；公司电脑用公司代理 |

## 给下次会话的提醒

- **别长回复**——会话容易因上下文超限重启。
- **写「待办」前先 grep 文档**——曾多次把已完成任务当成待办。
- **引用 issue/清单前先核对**——issue #3 清单 19 个（不是 20）。
- **push 卡死先查僵尸 git-credential 进程**——`pkill -f git-credential`，然后用 GH_TOKEN 内联方式推。
- **同步链路排障**：先查 `~/Library/Logs/openclaw/gateway.log`（搜 `FG-bypass handled`）；旁路脚本 `~/.openclaw/tmp/fg-sync-bypass.py`；分片目录 `~/.openclaw/tmp/fg-sync-in/`。
- **待补充（用户 10-09 发飞书）**：公司端补齐内容（B 类数据积累观察点、回测文件已发过飞书——两个 md 文档已还原入库）。
