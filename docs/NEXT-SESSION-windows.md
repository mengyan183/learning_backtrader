# Windows 侧交接单（2026-10-27 收尾 · 第二轮）

> 新会话开场：**先读本文件**，再按「下次开工顺序」执行。

## 当前状态

| 项 | 状态 |
|---|---|
| Windows 待办（P0 + P1 + P2⑦） | **全部完成** ✓（本地已验证） |
| impeccable 审查 + 修 P0/P1/P2 | 第一轮 22/40 → 修复；第二轮 27/40 → **5 项全修完** ✓（见「第二轮」两节） |
| 本地 HEAD | `d63c9fc`（**领先 `origin/main` 2 个提交**：`5195f95` 看板改造 + `d63c9fc` 纪律门禁）—— Windows 不能 push，等 Mac 侧取 |
| 工作区改动 | `index.html` / `style.css` / `report.py` / `test_report.py` / `test_report_exposure.py` / 本文，**未提交** |
| 全量测试 | **1950 passed / 1 flake / 2 skipped**（1953 用例，185.9s）✓ —— 原先 9 个 Windows 编码失败已全修（见下）；剩下 1 个 `test_fg_sync_ingest::test_catch_up_push_pushes_backlog` 是**全量下偶发**，单跑与整文件跑均通过 ✓ |
| 本次改动覆盖 | dashboard 子集 **112 passed** + 纪律门禁 **5 passed** = 117 ✓ |
| `sync_1027h`（MT-83） | ✅ **Mac 已落地**：8 片收齐，Mac 已推送 `8525460` 到 gitee（4 文件，增量 pytest 通过） |
| Mac 侧 | 🔴 当前**已关机** ⇒ 本轮**不打包、不投递、不推送**（用户 2026-10-27 明确要求） |
| 基线一致性 | ✅ 本地 HEAD == `origin/main` == `8525460`（0 ahead / 0 behind），本轮改动干净叠在其上 |

## 本轮做了什么（全部在 Windows 本地完成）

### P0
- ① 删掉 `body` 的两层径向光晕 ✓（`style.css` 里 `radial-gradient` 两行移除，底色回到 `var(--bg)`）
- ② 正文类 11px ⇒ 12px ✓：`.stat-label` `.temp-ticks` `.h-line2` `.h-cost` `.h-trend` `.h-risk`
  `.f-name` `.sent-t` `.sent-d` `.cmp-note` `.w-note` + 模板内联 11px（2 处）
  - 药丸标签（`.tag` / `.zone` / `.f-zone`）与指示点（`.rt-dot`）**故意不动** —— 不是正文

### P1
- ③ 「更多」面板项选中态 ✓：`.sheet-item.on`（蓝底+蓝字+右侧圆点），
  `showByName()` 同步 `aria-current="page"`；点主 tab 会自动清掉
- ④ 粘性表头 ✓：`table.card th{position:sticky;top:0}`；
  🔴 必须同时做两件事才能生效：`div.scroll` 改为 `overflow:auto;max-height:70vh`（造纵向滚动上下文），
  并**去掉** `table.card` 上的 `overflow:hidden`（它会自己变成滚动容器，把 sticky 吃成无效）
- ⑤ 骨架屏 + 失败重试 ✓：`.sk`（扫光骨架）/ `.fail`（红条 + 重试按钮）；
  覆盖 `/api/tasks`、`/api/watchlist_3x`、`/api/symbol_fg` 三条链路
- ⑥ 横滑边缘渐隐 ✓：`div.scroll.can-l/.can-r` 的 `mask-image`，由 `syncFade()` 按
  `scrollLeft/scrollWidth` 开关（滚动、resize、切 tab、渲染完成都会重算）

### P2
- ⑦ 内联 `style=` 抽成 class ✓：模板里 87 处 → 只剩 **2 处**（来源色 / 状态色，值来自数据，必须内联）
  新增通用件：`.form-row .inp .inp-num .inp-text .btn .btn-sm .btn-xs .btn-link`
  `.msg .msg-top .hint .note .note-inline .note-date .muted .lbl-sm .q-title`
  `.mb4 .mb8 .row-gap .src-ok .src-bad .src-none .td-note .td-num-sm .fs12`
  `.c-stale .c-ok .c-bad .c-sub` `table.t-compact`
  - `report.py` 的 16 处**保留**：其中 13 处是 `width:%` / `background:%s` / `color:%s` 动态值，抽不了
- ⑧ `prefers-reduced-motion` 全局覆盖 ✓（`transition/animation` 统一降到 .01ms + `scroll-behavior:auto`），
  面板项平滑滚动也改为 `REDUCE ? "auto" : "smooth"`

### 顺带
- `style.css?v=20261027a` ⇒ `20261027b` ✓（硬约束 6）

## 验证记录（本地 127.0.0.1:8899）

| 检查 | 结果 |
|---|---|
| `pytest tests/dashboard -q` | **110 passed** ✓ |
| `impeccable detect --json index.html style.css` | **0 条**（比上一轮少，已无 26 条 low-contrast 误报） |
| 市场页 改前/改后截图 | 仅底色光晕消失 + 字号变大，无静默错位 ✓ |
| 粘性表头（合成 30×10 表，390px 视口） | `scrollTop=300` 后表头仍在顶部 ✓ |
| 边缘渐隐 | 溢出时右侧 `can-r` + mask 生效，不溢出时不加 class（无假提示）✓ |
| 面板选中态 | 「关注列表」蓝底蓝字蓝点 ✓ |
| 失败态 | 关注清单缺失 ⇒ 红条 + 重试按钮 ✓ |

截图存档：**无** —— 2026-10-27 的验证截图（含改前基线）按用户要求全部删除 ✓，
`docs/` 下只保留 `docs/media/card_*.png`（`scripts/make_explain_cards.py` 的产物，已入库 ✓）。
需要复现时重拍：
```
py -3.10 scripts/serve_dashboard.py --host 127.0.0.1 --port 8899
bsk session start → bsk navigate --session <id> http://127.0.0.1:8899
bsk screenshot --session <id> --out <path>.png
bsk session stop --all
```
🔴 **关注列表的粘性表头/边缘渐隐至今没有真实数据证据** —— 本机缺 `watchlist_3x.csv`，
用合成 30×10 表拍的图（`col0…` 假表头）**不能作为证据** ✗，已删。
该两项目前只有**测量数据**（`position:sticky` 生效、`can-r` 与 mask 生效），等 Mac 真实数据复验。

## 第二轮（16:00–16:25）：impeccable 审查 + 按结论修复

审查方式：双路独立评估（A 设计评审 / B 检测器 + 浏览器证据）。
得分 **22/40**（Acceptable），失分集中在「出事时它怎么说话」（控制/一致/恢复/帮助）。

### 已落地

| 项 | 落点 |
|---|---|
| **P0-1 过期数据进 hero** | `report.py`：`MAX_SIGNAL_LAG_DAYS=3` + `_signal_lag_days()`；超容差 ⇒ `56.6` 转灰（`.hero-num.stale`）+ 琥珀 chip「数据停更 15 天 · 非当前」 |
| **P0-1b 动作也门禁** | 过期时「今日动作」降级为「基于过期数据（10-12）· …」，字号 14px 灰字（原设计漏了这层，等于用旧数据喊买 ✗） |
| **P0-2 错误条改人话** | `#__errbar` 由 `position:fixed` 改为**正常流横幅**（不再压 h1）+ `×` 关闭 + 文案改「接口连续 N 次未连通 · 数字可能不是最新的」 |
| **P1-3 任务页严重度** | 分「需要处理 / 正常 / 任务注册」三组，异常组按 `滞后÷容差` 降序；摘要改「N 项需要处理（越靠前越急）」 |
| **P1-4 今日动作** | `_holdings_block(..., acts=[])` 出参复用已有逐标的结论 ⇒ hero 内 15px 一行（**不新增任何交易规则**） |
| **P2 色契约** | `.f-zone` 四条是**死代码**（实测 `.f-card` 5 个 / `.f-zone` 0 个）⇒ 删除；写清「纯 `#f85149` 只留给需要你动手」 |
| **P2 绿涨红跌** | 用户拍板改美股惯例：`--up/--down`（值/名矛盾且被熔断、覆盖共用）⇒ 换成 `--gain/--loss`；`.h-pnl.up` 绿、`.h-pnl.down` 红、`.stat-value.bad` 红、`.tag-in` 绿；文案改「按美股惯例着色（绿涨红跌）」 |
| 深色控件 | `input`/`button`/`radio` 全部跟调色板（元素选择器 0,0,1，`.inp*`/`.btn*` 类自动压过） |
| 检测器真阳性 | placeholder `#5d6b82` 3.4:1（深色化时引入）⇒ 改 `--fg-muted` ≈7:1，复跑 0 条 |

### 新增护栏

- `test_hero_admits_stale_signal`：信号日超容差必须挂 `stale-flag` + `hero-num stale`，新鲜信号不得误报
- `test_sticky_header_and_style_floor`：sticky 三要素 + body 无光晕 + reduced-motion + **注释里不得出现「星号+斜杠」**

### 🔴 本轮两个新坑（写进硬约束）

1. **CSS 注释里出现「星号+斜杠」会提前闭合注释**，把紧跟的第一条规则整条吞掉 ✗。
   实测两次：`input` 规则被吞 → 输入框一直白底，`cssRules` 里查不到，**误判成浏览器丢 `:where()`** ✗。
   已加护栏 `test_sticky_header_and_style_floor` 的 `"*/" in ln[:-2]` 断言。
2. **同一端口起了两个服务进程**（`netstat` 两个 LISTENING）⇒ 旧进程应答、改代码不生效 ✗。
   改完 Python 后：`netstat -ano | grep :8899 | grep LISTENING` 拿 PID 全部 `taskkill`，再单进程启动。

### 第二轮审查（27/40）后的 5 项修复（已完成 ✓）

| 审查结论 | 修复 | 证据 |
|---|---|---|
| **P0** 一卡一结论 | `act == 买入` 时 `cost_adv` 降级为**风险陈述**：`风险提示：浮亏 -57.1%（与买入信号不同轴，先看下方仓位上限）`，不再输出「建议分批减仓/止盈」祈使句 | 持仓截图 AXTX / CRCG / GDXU |
| **P0** 超配提权 | `_deviation_line` 从 12px `.sub` 灰字 ⇒ `.expo` 数字条（首屏可见）；hero 用 `expo` 出参**镜像同一组数字**（不重复计算） | 页面实测（截图已清理） |
| **P1** 同卡两个浮盈数字 | 实时轮询**不再改写 `.h-pnl`**（快照浮盈），另加 `.rt-pct`「实时 +33.6%」显式标注 | BTC 卡：`+36.7%` 快照 + `实时 +33.6%` |
| **P1** 过期只降级容器、没降级词 | `（当前系统）`⇒`（系统指数）`；`今日动作`⇒`10-12 当日动作`；`现价 X`⇒`现价 X（09-22）`；持仓页加 `持仓快照 09-22 · 35 天前（非当前）` chip | 三张截图 |
| **P1** 两处实测布局缺陷 | ① `table.t-compact th` 补 sticky（实测 211→**189 粘住**，原来 211→149 滚走）；② `.f-card{min-width:0}` + `.f-chart/.echart/.echart-main{overflow:hidden}` 修旋转溢出 | 实测 445/390 ⇒ **390/390** |

⚠️ **一条误报要记住**：B 报的「390px 首次加载溢出 55px」不成立 —— 先 `emulate` 再 `navigate` 后测量是 390/390。
真实缺陷只在**先加载后改宽**（手机旋转 / 窗口拖窄）时出现，因为 echarts 画布保留旧像素宽 ✗。
⇒ 量响应式必须**先设视口再重载**，否则会测出假 bug。

### Windows 编码失败修复（2026-10-28，9 个 → 0）

根因不是「测试写错」，而是**生产代码在 Windows 上默认 GBK**：

| 位置 | 问题 | 修法 |
|---|---|---|
| `scripts/evolve_review.py` 的 `open(HYP).read()`（2 处）、`open(HYP, "a")`（2 处） | 没写 `encoding` ⇒ Windows 用 GBK 读写 UTF-8 的 `hypotheses.md` ⇒ `UnicodeDecodeError` | 全部加 `encoding="utf-8"` |
| `tests/test_evolve_review_dedup.py` 的 `open(p, "w")` | 造夹具时按 GBK 写，被测代码按 UTF-8 读 | 加 `encoding="utf-8"` |
| `scripts/mac_bootstrap.sh` 内嵌 Python | 打印 `✅` 撞 GBK 控制台 ⇒ `UnicodeEncodeError`（**这是真发给用户的脚本** ✗） | heredoc 开头加 `sys.stdout/stderr.reconfigure(encoding="utf-8", errors="replace")` |
| `scripts/make_feishu_bundle.py` | 同上 | 同上（照抄 `analyze_shoutu_variants.py` 的既有惯例 ✓） |

🔴 **教训**：Mac 上默认 UTF-8，所以这类 bug **只在 Windows 暴露** ✗ ——
凡是 `open()` 读写仓库里的 `.md`/`.json`/`.csv`，**必须显式 `encoding="utf-8"`** ✓。

### 未做（有意）

- 「重试全部异常」按钮：`/api/tasks/retry` 一次只接一个 target，一键重试会**并发拉起 15+ 个脚本** ✗ ⇒ 只做分组排序，保留逐行重试
- `.inp` 仍硬编码旧调色板 `#0d1117`（critique 次要观察，未在范围内）

## 下次开工顺序

1. ✅ 已完成：`sync_1027h`（MT-83）已落地（Mac 推送 `8525460`），
   `index.html` 有 `id="moreSheet"` ✓、无 `var showAll` ✓、`style.css?v=20261027a` ✓
2. **Mac 恢复后，按这个顺序同步本轮改动**（🔴 顺序不能反，反了就出 `sync_1027b` 那种 patch 冲突）：
   1. `git fetch origin` → `git pull --ff-only origin main`（把 Mac 期间推的提交先吃掉）
   2. 确认 `git rev-list --count HEAD..origin/main` **= 0**，且 `git status` 无冲突残留
   3. 本轮改动先本地提交（`index.html` / `style.css` / `test_report.py`）
   4. 再打包投递；`pack_many` 报「有删除行」**逐条核对**；每命令 1~2 片
   5. 发完必查 `feishu_send.py --sent-status <包>`
3. Mac 侧复验同一份清单（骨架/失败态在 Mac 有真实数据，能看到正常表格 + 粘性表头）
4. 可选：暗色输入框/按钮 —— 现在 `input` 与 `button` 仍是浏览器默认白底（**本轮未动**，
   不在清单内，属静默变化），要改另开一条

## 待决策

- 🟡 `input` / `button` 在深色页里仍是白底（`h30` 快速打卡、各查询按钮）。本轮**故意没碰**：
  不在清单内，改了就成「静默变化」。要不要下一轮一起做？

## 硬约束（踩过的坑，别重犯）

1. 🔴 **每次同步/打包前，先 `git fetch && git pull --ff-only origin main`** —— 两个已发生的代价：
   ① 曾落后 **542 个提交**，打包把 Mac 的改动删掉了 ✗；
   ② 曾因 Windows 侧基线旧 ⇒ `sync_1027b.diff` 在 Mac 上**应用失败**（`docs/mac-tasks.md` 冲突）✗，
   还得让豆包人工处理入库冲突 ✗。
   ⇒ **拉完先确认** `git rev-list --count HEAD..origin/main` **为 0** 再打包 ✓
2. 🔴 **`pack_many` 报「有删除行」必须逐条核对** —— 曾 3 次当噪音忽略，其中一次真删了别人的代码
3. 🔴 **发包要分批**（每命令约 1~2 片），**发完必查** `feishu_send.py --sent-status <包>`
4. 🔴 **发前先 `bsk session stop --all`** —— 会话泄漏会让 `bsk observe` 挂死
5. 🔴 **注释里不写字面 HTML 标签** —— `<script>` 曾撞坏「script 配对」断言
6. 🔴 **改样式必须 bump `style.css?v=`** —— 否则普通刷新命中旧 CSS，等于白改
7. 🔴 **不能改 tab 文本** —— `show()` 用 `tabs[idx].textContent` 匹配 `data-name`
8. 🔴 **「更多」面板项的 `class` 必须保持 `class="sheet-item"`** ——
   `test_tab_alignment.py` 的 `ITEM_RE` 是精确匹配，静态 class 一改测试就红；选中态只能 JS 加
9. 🟡 `docs/mac-tasks.md` 表格**每行必须 5 格**，正文里裸 `|` 要写 `\|`
10. 🟡 本机 `rm -f a b c` **只会删掉第一个文件** ✗（safe-delete 包装器会中止后续 ✗）
    ⇒ 批量删必须逐个删，或用删除工具 ✓（2026-10-27 实测：23 张截图分 3 次才删对）
11. 🔴 **Windows 侧无法 push 到远程 git**（公司安全策略 ✗）—— 出向只能靠飞书分片 ✓，
    入向（`git fetch` / `git pull`）正常 ✓。真实拓扑是单向的：
    `Windows --飞书分片--> Mac --gitee--> Windows`。
    ⇒ ① 飞书打包/还原那一段**不是冗余，不能删** ✗（只能降出错率：打包前先 fetch+pull ✓）；
    ② Mac 是**唯一能 push 的端** ⇒ Mac 侧 agent 若自动 commit/push，坏代码会直接进 gitee，
    Windows 下次 pull 就中招 ✗ ⇒ 「禁 auto-commit」门禁优先级更高 ✓。
12. 🔴 **Mac 侧必须自己装纪律门禁钩子** —— `scripts/pre-commit-syntax.sh` 在
    `.gitignore` 的「本机专用」清单里（未跟踪 ✗），挂载点不会同步过去 ✗；
    而 `scripts/pre-commit-discipline.sh` 是**跟踪**的 ✓，会随同步到达 ✓。
    Mac 仓库根目录跑这一条（幂等，可重复执行 ✓）：
    ```sh
    H=.git/hooks/pre-commit; mkdir -p .git/hooks; [ -f "$H" ] || printf '#!/usr/bin/env bash\n' > "$H"; grep -q 'bash scripts/pre-commit-discipline.sh' "$H" || printf '\nbash scripts/pre-commit-discipline.sh || exit 1\n' >> "$H"; chmod +x "$H"; tail -3 "$H"
    ```
    验证：`bash scripts/pre-commit-discipline.sh fg_system/config.py` ⇒ 退出码 **1**（拒绝）✓

## 已装工具

| 工具 | 位置 | 用法 |
|---|---|---|
| impeccable skill | `~/.codebuddy/skills/impeccable/` | `use_skill impeccable`；改 UI 前读 `reference/craft-floor.md` |
| impeccable 引擎 | `~/.impeccable/bin/impeccable.exe` | 0.1.17+engine |
| impeccable agents | `~/.codebuddy/agents/impeccable-*.md` | 4 个 |

## 已知误报

- 上一轮 `impeccable detect` 对 `index.html` 报的 **26 条 low-contrast** 本轮已不再出现（0 条）。
  若后续又出现，仍是它把 `body` 渐变底当白色所致 ⇒ **不要"修"**。
