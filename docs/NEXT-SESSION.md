# 下次会话先读这个（进度快照）

**更新**：2026-10-16 · **对应提交**：远端 main = `c750f0d`（MT-33：H-069 裁决 A 落地 + §C.3 教训⑧改写/⑨a⑨b）

---

## 一句话现状

- **同步链路已全通** ✓：公司 Windows → 飞书「海外投资助手」机器人 → OpenClaw(Mac) `fg-sync` skill → 贪恐仓库（详见 `docs/dual-end-workflow.md`）
- **gitee 为唯一主线** ✓：读走 `git fetch`（公司代理 `http://10.30.6.49:9090`），写走飞书分片，**不做 merge**（历史无关）✓
- 🔴 **任务表已清空** ✓：`docs/windows-tasks.md` **WT-01~31 全部 ✅** ✓；`docs/mac-tasks.md` **MT-01~33 全部 ✅** ✓ ⇒ **无下发任务** ⚠️（⇒ 需**定新目标**，否则下个会话无活可干）
- 🔴 **任务通道已固化（2026-10-16）**：**凡「需 Mac 执行」的事必须登记进 `docs/mac-tasks.md`** ✓（状态 `待执行` 即触发器 ✓，Mac 完成后回写 ✅）；**note 只是说明附件、不构成任务** ✗
- **规划 v2.0**：**阶段 1 ✅**（A5/A3c/A3b/A3a/D1，2026-10-13 ✓）；**阶段 2 ✅**（敏感性四组 + 变体回测 V-H7/V-ATR/V-VOL/V-CORR/V-MA + B2/B3，2026-10-09~14 ✓）⇒ **下一阶段待定** ⏩（阶段 3 / A4 前置，**需与用户确认** ✗）
- 🔴 **H-065 线已整体归档（2026-10-16）** ✗：H-065（60 日 corr ✗）/ H-068（5 日 corr ✗）/ H-069（当日股债同跌率 ✗）**三个指标全否** ⇒ 「挤压期避险失效」**不再派生新假说** ✗（再换指标即过拟合）
- **Mac 侧待办（等待型）**：① B 类数据积累（H-001 观察点、B-3/B-5 快照、B-8/B-9）；② F-009/F-010 因子样本积累。C-5 季度自动重检已设 launchd（1/4/7/10 月 1 日 08:00）
- ⚠️ **Windows 端环境**：默认 `python` = **3.14 且无 `backtrader`** ✗ ⇒ 跑测试**必须 `py -3.10`** ✓；**无公网** ⇒ 凡"需真实 `Data`"的任务登记 `docs/mac-tasks.md` ✓
- ⚠️ **状态列仅供参考** ✗：本仓库多次出现"已完成但状态仍写待做"✗（WT-15~26 即如此）⇒ **开工前先 grep/跑测试确认代码现状** ✓

---

## 🆕 2026-10-10 ~ 10-16 增量（本轮重点）

- ✅ **双端链路加固**：`--patch` 增量包（**MT-20** ✓）+ **分片丢失根因修复**（**`9c2be0d`** ✓：失败包误写 `done` 判定加固 ✓ + 停用目录级连坐清理 ✓）
- 🔴 **§C.3 预登记自检清单从 5 条 → 9 条** ✓（`docs/dual-end-workflow.md`）—— 由 **H-065 一条假说连踩 5 个坑**反推得出：
  ① 自变量不含结论 / ② 判据不与定义重叠 / ③ 稀有事件禁占比比较 / ④ 措辞与意图逐字对齐 / ⑤ 指标尺度匹配机制尺度 /
  ⑥ 样本低于下限只报数不推断 / ⑦ 非盲登记须显式标注 + 分段稳健 / ⑧ patch 基准 / ⑨a 全样本显著 ≠ 稳健 / ⑨b 子样本下限按**功效**算
- 🔴 **patch 通道失败的真正根因 = 打包基准漂移** ✗（2026-10-19 更正 ✗）：
  **不是**「通道不可用」✗，而是**上一包还没入库就打下一包** ✗ —— `sync_1019e` 基于 `origin/main=16ad892` 打包 ✗，而 `sync_1019d`（含 MT-36 行修复 ✗）随后才落地 ⇒ 1019e 把该修复当「新增」再带一遍 ✗ ⇒ 上下文错位 ⇒ `patch does not apply` ✗。
  ⇒ **规则**：**同一文件在上一包入库前，不得再发新包** ✗（串行，不要并发 ✗）；表格类文档优先**整文件包** ✓；patch 只用于**大文件单发** ✓（`FG_PROXY` 必带 ✓）。
- ✅ **C-3 趋势过滤移除已落地并真数据复核**（**MT-23** ✓）：`TREND_FILTER_FACTOR` 0.5 → 1.0 ✓；`trend` 恒 1.0 ✓；30 天观察窗已启动 ✓
- ✅ **nuwa P0 简报渲染复核**（**MT-24** ✓）；**H-065 数据接入**（**MT-26/27/28**：TLT + DGS10 + **BAA10Y 1986 起** ✓）
- ✅ **抗风险 S-0~S-5**（**MT-11~15** ✓）：`features.csv`/`portfolio_features.csv` 停更修复 + **组合级接入每日链** ✓、freshness 护栏 ✓、回撤预算曲线 ✓、模型目标 vs 实盘偏离行 ✓
- ✅ **归因标尺修复**（**MT-21/22** ✓）：生产口径下趋势过滤 **收益 −5.90pp / 回撤改善 +1.72pp**；OOS **101/120 窗不劣化** ✓

---

## 当前状态基线（2026-10-09，历史留痕）

- ✅ **回测裁判恢复**：`fg_system/backtest/*` 还原（issue #3 关闭），`evolution/baseline.json` 产出（IS 至 2024-09-30 / OOS 自 2024-10-01）
- ✅ **A 类阻塞全解除**：H-005 rejected / H-007 adopted（2026-10-08 验证）
- ✅ **C 系列全落地**（2026-10-08）：C-1 变体设施 / C-2 提案自动化 / C-3 审批闭环 / C-4 周报自动化 / C-5 季度 walk-forward / C-6 执行确认 / C-7 因子库扩展 / C-9 扩池策略侧 / C-10 实盘-回测归因 / C-11 衰减降级；V-H7 三标的 OOS 均不采纳（负结果如实登记，裁决 Y 纳入长期观察）
- ✅ **B 系列**：B-6 Put-Call 免 key 链路（IC 0.044 / IR 0.58）/ B-7 新闻情绪（NewsAPI 免费 key）/ B-4 假说口径修订（H-010~H-021 按真实列重措辞）
- ✅ **Q1-Q4**：alternative.me 市场级 FNG 交叉校验 / TokenUnlocks 受阻登记 / BeckieAnalysis 中文字幕入库 / 方法论书单进 fg-qa
- ✅ **数学模型**：HMM 状态识别 / 档位马尔可夫矩阵 / EVT 阈值校准 / 贝叶斯假说信心（`fg_system/models/`，纯 numpy）
- ✅ **阶段 1️⃣ 敏感性分析四组闭环**（2026-10-09）：circuit（贪婪侧不敏感/恐惧侧极恐线5敏感）、zone（基准[20,40,60,80]稳健）、core（两端敏感、0.45居中合理）、trim（阈值未介入回测路径）；`evolution/sensitivity/` 四张表 + 汇总 README
- ✅ **阶段 2️⃣ 变体回测 V-H7/V-ATR/V-VOL**（2026-10-09）：三变体 OOS 均不采纳（收益损失>回撤收益，SOXL 上 V-VOL 回撤还恶化）⇒ **激进仓位即收益来源，防御降仓不划算**；等价性守卫全通过；提案草稿 evolution/experiments/variant_h007_2026-10-09.md
- ✅ **阶段 2️⃣ V-CORR + V-MA 落地**（2026-10-09）：variants.py 新增 V-CORR（VIX 滚动1年80分位→仓位×0.5）与 V-MA（close<MA50→×0.5）；守卫 12 passed；**UPRO V-CORR 为阶段2首个提案候选**（年化+0.04pp、回撤持平）已按用户批复 **Z（纳入长期观察）** 审批（1134b27）
- ✅ **V-ATR/V-VOL 归档**（2026-10-09 晚）：walk-forward 20/22 窗建议归档 → variants.py 标记 `archived: True`（9c56eeb）；**激进仓位即收益来源，防御降仓 OOS 不划算**
- ✅ **链上金融观察池**（2026-10-09 晚，0277a02）：OBSERVE_SYMBOLS 新增 COIN/HOOD/CRCL（HOOD 补价 1305 行）；ONCHAIN_FINANCE_TAGS 研究标签（CRCL 利率敏感）；假说 H-030 量价-资金背离 / H-031 利率敏感度；微信文章 11 块入 kb（channel=wechat_article）
- ✅ **微信研报提升点**（2026-10-09 晚，3808a1f）：H-033 币股分层 / H-034 稳定币使用效率新假说；ONCHAIN_FINANCE_TAGS 增 valuation_type 分层；7 篇文章入 kb（+19 块，集合 2816）；H-030 编号冲突修复（撞号→H-032）
- ✅ **H-002 判据定案**（2026-10-09）：10-02 起 5 交易日现金全 <0（-879.99×5）⇒ **adopted 确认成立**（B-1 解除）
- ✅ **C-5 walk-forward 全变体重检**（2026-10-09，40 季度窗）：**V-CORR 三标的全维持观察**（27/27/26 窗，与 OOS 提案互相印证）⇒ 待 C-3 人工审批；V-MA 仅 TQQQ 维持；V-H7 延续观察；**V-ATR/V-VOL 建议归档**
- ✅ **知识库**：YouTube 频道字幕 → ChromaDB（yt_trading）+ `scripts/kb_search.py` + kb-search 技能；外部仓库精华沉淀 `docs/kb-insights.md`
- ✅ **H-023** 凯利公式 vs 规则仓位假说（半凯利上限，样本 <60 日不落地）
- ✅ **量化选型决策**：vectorbt + PyPortfolioOpt（不引入 Qlib/LEAN/vn.py）
- ✅ **毛选方法论 skill**（mao-methodology）+ 简报归因主要矛盾标注
- ✅ **守猪待兔修复**：历史通道重建（fetch_shoutu.py），解除信号陈旧
- ✅ **新鲜度/简报/网页刷新系列修复**：freshness 交易日差≥1 天即触发、刷新触发 live 同步、简报减仓双引擎

## 双端同步链路（重点，2026-10-16 更新）

- **打包端**（公司 Windows）：`py -3.10 scripts/pack_many.py <包名> <文件…>` → `dist/feishu/text/<包名>-tNNN.txt`（≤1500 字符/片）
  - `--patch --base-ref origin/main` ⇒ 只发统一 diff（片数大减 ✓）；⚠️ 基准被推进 ⇒ 上下文不匹配失败 ✗
  - ⚠️ patch 打包**不会清理**同名旧分片 ✗（重打前先删 `<包名>-t*.txt` ✓）
- **发送**：`cmd //c start "" "scripts\send_pkg.bat" "<包名>"`（脱离会话 ✓）
  - ⚠️ Git Bash 里必须写 **`cmd //c`** ✗（`/c` 会被当路径 ⇒ bat 报「此时不应有 -n」✗）
  - ⚠️ 脱离窗口**偶发卡死**（日志停在「打开会话」✗）⇒ 降级 `py -3.10 scripts/send_pkg.py <包名> --start N --limit M`（前台分批 ✓，`--limit 2` 最稳 ✓）
  - 发送后**必须** `scripts/verify_pkg.py <包名> <文件…>` 做往返 md5 ✓（patch 包不适用 ⇒ 改为解包核对 diff ✓）
- **接收端**（Mac）：feishu 插件旁路（`FG-SYNC BYPASS` 注入 monitor mjs）→ 落盘 `~/.openclaw/tmp/fg-sync-in/` → `fg_sync_tool.py --quick --brief` 单命令（聚合→解压→白名单→冲突→入库→pytest→回传）
- **白名单**：`ALLOWED_DIRS={fg_system,scripts,tests,evolution,docs}` + 根级文件（含 `.gitignore/.gitattributes`）；`--full-repo` 一次性全库授权（跳过目录白名单但保留 `_denied`：Data/、密钥、.git、node_modules、__pycache__）
- 🔴 **任务登记（2026-10-16 固化）**：需 Mac 执行 ⇒ 写进 `docs/mac-tasks.md` ✓（状态 `待执行` = 触发器 ✓）；Mac 完成后回写 ✅ 并提交 ✓
- **已归档**：855 片 `sync_code_*.md` → `~/.openclaw/tmp/fg-sync-in/archive_synccode_20261009/`（避免重复解析）
- **已知坑**：URL-safe base64 含 `-`/`_` 手动解码必错 ✗；`.done` 幂等标记（内容 hash）✓；ingest 读目录下全部 .md

## 环境备忘

| 项 | 值 |
|---|---|
| 仓库 | Mac `/Users/xingguo/learning_backtrader`；Windows `D:\3-code\learning_backtrader`；**remote `gitee.com/xingbaoyin/learning_backtrader.git`**（读走公司代理 `http://10.30.6.49:9090`）|
| push 网络 | **必须走 ClashX 代理 7890**（直连被 TUN 劫持/超时）；有效推送：`export GH_TOKEN=$(gh auth token)` + `git -c http.proxy=http://127.0.0.1:7890 -c credential.helper= -c credential.helper="!f(){ echo \"username=x-access-token\"; echo \"password=$GH_TOKEN\"; }; f" push origin main`（绕过 osxkeychain 卡死） |
| credential | 系统级 CommandLineTools gitconfig 有 `osxkeychain`（会卡死 push）；repo 级 `!gh auth git-credential`（不带 fill） |
| 模型 | OpenClaw 主模型 `nvidia/deepseek-ai/deepseek-v4.1-flash`；fallback `[zai/glm-4.7-flash, litellm/hermes-agent, ollama/qwen2.5-coder:3b-64k]`（zai 有 429 史）；ollama 11434 |
| 网关 | OpenClaw 18789；重启 gateway 用 `kill -9 <PID>`（`launchctl kickstart` 静默失效）；日志 `~/Library/Logs/openclaw/gateway.log` |
| 飞书 | appId `cli_a93abe057178dbb4`（secret 在 `~/.openclaw/openclaw.json`）；chat_id `oc_a9306b326943821490184d073dae9a65`；API 基 `https://open.feishu.cn/open-apis` |
| 测试 | `.venv/bin/python -m pytest tests/ -q`（**1711 passed** 基线，2026-10-16 ✓）；增量 `--quick` <10s |
| 数据源 | 海外需代理 7890（家里 Mac）；公司电脑用公司代理 |

## 给下次会话的提醒

- **别长回复**——会话容易因上下文超限重启。
- **写「待办」前先 grep 文档 + 跑测试**——曾多次把已完成任务当成待办。
- 🔴 **任务必须登记 `docs/mac-tasks.md`**——note 只是说明附件，**不构成任务** ✗。
- 🔴 **任何假说/因子/变体入库前，先过 §C.3 的 9 条自检**（`docs/dual-end-workflow.md`）。
- 🔴 **patch 发文档易失败** ⇒ 表格类走 `mac-tasks.md` 登记；代码/测试用整文件包。
- **push 卡死先查僵尸 git-credential 进程**——`pkill -f git-credential`，然后用 GH_TOKEN 内联方式推。
- **同步链路排障**：先查 `~/Library/Logs/openclaw/gateway.log`（搜 `FG-bypass handled`）；旁路脚本 `~/.openclaw/tmp/fg-sync-bypass.py`；分片目录 `~/.openclaw/tmp/fg-sync-in/`。
- **待补充（用户 10-09 发飞书）**：公司端补齐内容（B 类数据积累观察点、回测文件已发过飞书——两个 md 文档已还原入库）。
