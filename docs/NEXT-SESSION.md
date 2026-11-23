# 下次会话先读这个（进度快照）

**更新**：2026-11-20 · **远端**：**gitee** `https://gitee.com/xingbaoyin/learning_backtrader.git` main（`git remote -v` 实测 ✓；此前的「GitHub 唯一主线」已不成立 ✗）· **测试基线**：以 Mac 上 `py -3.10 -m pytest` 全量为准 —— 上次完整复核 **1910 passed / 1 skipped**（2026-10-27）；**Windows 侧 2026-11-20 复核：29 failed 全为缺 `flask`（dashboard）/ `backtrader`（回测），非代码回归** ⚠️ · 上一提交见 `git log -1`（本文不再钉死哈希 ✗，2026-10-29 修正）

---

## 📌 2026-11-20 **本日汇总：贪恐系统评审后的 9 项规则变更 + 4 个 bug 修复**

> 权威明细在 `docs/rules-2026-11-20.md`（12.42~12.56），本节只回答「现在是什么状态」。

### 当前状态

- **权重锁定 40.5%（vol 主导）**：`vix .270 / price .225 / term .135 / breadth .135 / fed .135 / putcall .100`
- **系统定位已改写**为「**波动率主导的逆向情绪指数**」（README / `fg_system/index.py` /
  `docs/factor-weights-decision.md` 三处已改）⇒ **40.5% 是先验选择**，不是"本质"
  （2026-11-20 三轮评审降级，见 12.57：518 日样本、年化 SE≈21pp，三档统计上不可区分；
  有硬证据的只是"波动率主导"方向 —— fed 缺失重归一下 `vix+term=46.8%`）
- 测试：`tests/test_run_task_queue.py` **68 passed**；全量 29 failed 全为**缺依赖**
  （`flask` → dashboard 测试；`backtrader` → 回测测试），非代码回归 ✓

### 已生效

| 条 | 内容 |
|---|---|
| 12.42 | 弹药池**回撤修复重装**（回撤 ≤5% 且距上次 ≥90 天 ⇒ 清空已释放批次） |
| 12.43 | **压力测试接进简报**（`_stress_section`：-20% / -35% / 归零 三情景） |
| 12.44 | **绝对水平指数** `fg_index_abs`（固定阈值口径，与滚动分位并列展示） |
| 12.45 | 简报弹药状态**改读 `state.json`**（原来靠回撤推断，说成「弹药还在」✗） |
| 12.46 | 连亏保护**分母改期初净值**（-18.3% → -15.4%）+ 标注减仓滑点 |
| 12.48 | ICIR 按**重叠倍数折算**（`window/horizon` ⇒ ×1/√3） |
| 12.49 | **防抖结论进简报**（可操作 / 不可操作 + 原因） |
| 12.50 | **存量仓过渡期结束**（`2027-11-09` → `2026-11-19`）⇒ 1% 规则全量生效 |
| 12.51 | 漂移阈值改**相对基线**（0.30 / 0.45，与 ICIR 口径解耦） |

### 已验证但**不采纳**（重要，别再重做一遍）

- vol 权重 **30%**：同窗口 A/B **−5.41pp / Sharpe −0.21** ⇒ 已回退（12.47→12.52）
- vol 权重 **35%**：**−3.32pp / −0.12** ⇒ 不采纳（12.53→12.54）
- `term` 换 `credit_spread` / `erp`：候选 ρ(vix) **更强**（0.47 vs 0.43）、IC 更弱
  （−0.18 / +0.09 vs −0.32）⇒ 不换（12.55→12.56）
- **结论**：这个结构**没有可替换的薄弱环节**；降权 = 降收益，换因子 = 换集中方向

### 顺带修掉的 bug

- `%` 未转义 ⇒ `_stress_section` 崩溃，整份简报 rc=1（`-50%` 里的 `%` 被当格式符）
- `sys.path` 缺仓库根 ⇒ 「有效敞口」长期静默降级（`No module named 'fg_system'`）
- 连亏保护取错账户行 ⇒ 分子实际是 crypto 的 `day_pnl`
- pandas 3.0 `merge_asof` 精度不匹配（`[s]` vs `[us]`）⇒ `erp.py` / `credit_spread.py`
  **根本跑不起来**（从未被调用过，所以一直没暴露）

### 待观察（次日）

- **09:00** 守猪待兔定时器是否**自动**触发（2026-11-20 是我 `restart_queue` 手动拉起的）
- **05:30** 简报是否显示新段落：弹药状态 / 绝对水平 / 压力测试

### 队列侧

- 主文件 `run_task_queue.py` 已瘦身至 **328 行**（起点 6460），77 个 action 全在
  `scripts/queue_actions/` 8 个包里；守卫 `test_main_file_has_no_actions` 锁住「主文件不许再长 action」
- 新增动作 `discard_dirty`（用 `git stash` 收走指定文件的脏改动，可 `pop` 找回）
- 打包器新增两道硬失败：**规则代码必须带 `docs/` 变更**、**包名 MMDD 必须是当天**

### 评审整改（12.57~12.60）+ 两个 A/B 脚本

- **12.57**（已生效）：把「40.5% 是本质」降级为「先验选择」（518 日样本、SE≈21pp）；
  同时更正 `config.py` 的预算口径（`31.5%` 是 70/30 旧口径 ⇒ 实际 **36%**，
  大盘最大暴露 **49.33%**，余量 3.5~8.9pp）
- **12.58**（代码已回退，等 MT-88）：`putcall` 有 **1066 交易日空洞**
  （2019-10-07~2023-12-29），`ffill` 后 43% 是常数；改 `ffill(limit=5)` 会让
  因子全样本只剩 **12 个有效日** ⇒ 必须先补数据
- **12.59**（代码已改，待裁定）：冷却改「交易日」。本机执行层模拟：操作 225→215、
  换手 −84.2pp、近似年化 +0.90pp、回撤 +1.02pp、额外挡住 **151** 个日期
- **12.60**：补 QQQ/SPY 买入持有对照（OOS：策略 17.22% vs SPY 17.02% vs QQQ 24.41%）
- **脚本**：`scripts/putcall_ffill_compare.py` / `scripts/cooldown_compare.py`
  （均已在 `scripts/queue_allow/`，Mac 可用 `run_script` 直接跑）
- 🔴 **投递事故（2026-11-20）**：`sync_1120t`（新脚本）先于 `sync_1120v`
  （`portfolio.py`）到达 ⇒ Mac 增量 pytest 失败（`portfolio.cooldown_gap` 还不存在）；
  且 `sync_1120v` 因 `NEXT-SESSION.md` 与已入库内容**完全相同** ⇒ 纪律门禁判
  「改了规则代码但 docs 无变更」✗
  ⇒ **两条硬教训**：① 新文件包**不得依赖**尚未入库的代码，依赖项必须先进；
  ② 规则代码包的 docs 必须是**内容真有差异**的文件（不能拿已同步过的文档凑数）

## 🗄️ 历史条目在哪

2026-11-09 及更早的逐条记录（CME FedWatch 三版方案、Stooq 废弃、拆股事故、
MT-76 等）已移到 **`docs/session-log-archive.md`** ✓

本文件只保留四块：**当前状态**（一句话现状）+ **最近一条汇总**（2026-11-20）+
**环境备忘 / 双端链路** + **给下次会话的提醒**。


## 一句话现状

- **同步链路已全通** ✓：公司 Windows → 飞书「海外投资助手」机器人 → OpenClaw(Mac) `fg-sync` skill → 贪恐仓库（详见 `docs/dual-end-workflow.md`）
- **gitee 为唯一主线** ✓（2026-10-29 修正：此前写 GitHub ✗）：读走 `git fetch`（公司代理 `http://10.30.6.49:9090`），写走飞书分片，**不做 merge**（历史无关）✓
- **任务表 MT-01~77 全部 ✅** ✓；MT-76（C1 BAA10Y 信用利差因子进评测池，只评测不进权重）已全链闭环 ✓（见下「2026-10-27 MT-76」）⇒ **当前无下发任务** ⚠️（⇒ 下一新目标待用户/Windows 拍板：候选 C2 ERP 估值锚 PE 源待补，或 C1 走 M2.2 回测裁判/人工审批）
- 🔴 **任务通道已固化（2026-10-16）**：**凡「需 Mac 执行」的事必须登记进 `docs/mac-tasks.md`** ✓（状态 `待执行` 即触发器 ✓，Mac 完成后回写 ✅）；**note 只是说明附件、不构成任务** ✗
- 🔴 **H-065 线已整体归档（2026-10-16）** ✗：H-065/H-068/H-069 三指标全否 ⇒ 「挤压期避险失效」不再派生新假说 ✗（再换指标即过拟合）
- **Mac 侧待办（等待型）**：① B 类数据积累（H-001 观察点、B-3/B-5 快照、B-8/B-9）；② F-009/F-010 因子样本积累；③ H-006/008/009 样本未达标（仅 ~20 日，需 60/40/T+10），硬编码 verifying 已标 pending，不硬判；C-5 季度自动重检已设 launchd（1/4/7/10 月 1 日 08:00）
- ⚠️ **Windows 端环境**：默认 `python` = **3.14 且无 `backtrader`** ✗ ⇒ 跑测试**必须 `py -3.10`** ✓；**无公网** ⇒ 凡"需真实 `Data`"的任务登记 `docs/mac-tasks.md` ✓
- ⚠️ **状态列仅供参考** ✗：开工前先 grep/跑测试确认代码现状，勿把已完成当待办 ✓

---

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
| 仓库 | Mac `/Users/xingguo/learning_backtrader`；Windows `D:\3-code\learning_backtrader`；**remote GitHub `https://github.com/mengyan183/learning_backtrader.git` main**（读走公司代理 `http://10.30.6.49:9090`）|
| push 网络 | 走代理 `10.30.6.49:9090`；HTTP/2 报错用 `git -c http.version=HTTP/1.1 push origin main`；**推完 unset http/https_proxy**（飞书 API 直连必须先 unset 全部代理 http_proxy/https_proxy/HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/all_proxy）|
| credential | 系统级 CommandLineTools gitconfig 有 `osxkeychain`（会卡死 push）；repo 级 `!gh auth git-credential`（不带 fill） |
| 模型 | OpenClaw 主模型 `nvidia/deepseek-ai/deepseek-v4.1-flash`；fallback `[zai/glm-4.7-flash, litellm/hermes-agent, ollama/qwen2.5-coder:3b-64k]`（zai 有 429 史）；ollama 11434 |
| 网关 | OpenClaw 18789；重启 gateway 用 `kill -9 <PID>`（`launchctl kickstart` 静默失效）；日志 `~/Library/Logs/openclaw/gateway.log` |
| 飞书 | appId `cli_a93abe057178dbb4`（secret 在 `~/.openclaw/openclaw.json`）；chat_id `oc_a9306b326943821490184d073dae9a65`；API 基 `https://open.feishu.cn/open-apis` |
| 测试 | `.venv/bin/python -m pytest tests/ -q`（**1910 passed / 1 skipped / 0 failed** 基线，2026-10-26 ✓）；增量 `--quick` <10s |
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
