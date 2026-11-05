# 下次会话先读这个（进度快照）

**更新**：2026-10-29 · **远端**：**gitee** `https://gitee.com/xingbaoyin/learning_backtrader.git` main（`git remote -v` 实测 ✓；此前的「GitHub 唯一主线」已不成立 ✗）· **测试基线**：以 `py -3.10 -m pytest` 全量结果为准 —— 最近复核 **1910 passed / 1 skipped**（2026-10-27），此后增量未全量复核 ⚠️ · 上一提交见 `git log -1`（本文不再钉死哈希 ✗，2026-10-29 修正）

---

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

## 🎯 2026-11-05 **CME 新入口找到**（`cmegroup.cn` → `quikstrike.net`）

### 关键突破：`insid`/`qsid` 不需要浏览器

**旧方案**（已废弃 ✗）：用 headless Chrome 抓 netlog ✗ 从里面捞 `insid`/`qsid` ✗

**新方案**（纯 HTTP ✓）：

```
① GET https://cmegroup-tools.quikstrike.net/User/QuikStrikeTools.aspx
        ?viewitemid=IntegratedFedWatchTool&userId=lwolf
        &jobRole=&company=&companyType=
   ⇒ 返回 HTML 里 **`<form action="...&insid=XXX&qsid=YYY">`**
      `insid`/`qsid` **由服务端自动生成** ✓ **不需要浏览器** ✓

② 从 HTML 提取 `action` + `__VIEWSTATE` + `__VIEWSTATEGENERATOR`
   + `__EVENTVALIDATION`

③ POST 那个 action URL
```

### 怎么发现的

```
cmegroup.cn/fed-watch/ 的 HTML 里嵌了 iframe：
  <iframe src="https://cmegroup-tools.quikstrike.net/User/QuikStrikeTools.aspx
               ?viewitemid=IntegratedFedWatchTool&userId=lwolf&...">
  ⇒ **`userId=lwolf` 是硬编码的** ✓ 不是动态的 ✓
```

### 两个网络前提（重要）

| 前提 | 说明 |
|---|---|
| **必须走公司代理** | `cmegroup.cn` 和 `quikstrike.net` **直连都不通** ✗（`ping` 100% 丢包 ✗）|
| **必须关证书校验** | 公司代理做 **SSL MITM** ✗ 用**弱 CA 密钥** ✗ ⇒ `CERTIFICATE_VERIFY_FAILED: CA certificate key too weak` ✗<br>⇒ `curl` 报 `(43) bad argument` ✗ 是**同一个根因** ✗<br>⇒ `ssl._create_unverified_context()` ✓ |

### 当前卡点

```
GET/POST 都只返回 **3395 字节** ✗ 零个百分比 ✗
  <div style="display:none">Loading View...</div>   ← **JS 异步加载** ✗
  PageMethods=0  WebMethod=0  iframe=0
⇒ 纯 HTTP 拿不到最终数据 ✗ 但**入口是对的** ✓
⇒ 下一步：用 **bsk 打开那个 quikstrike URL** ✓ 让浏览器执行 JS ✓
   （它是**标准 ASP.NET 页面** ✗ 不是反爬 SPA ✗ ⇒ 可能不拦 ✓）
```

---

## 🗄️ 2026-11-05 裁定：**暂时放弃 CME FedWatch**（已从每日链移除）

### 决定性证据（`bsk --diagnose` 实测）

| # | 证据 | 结论 |
|---|---|---|
| ① | `iframes: {count: 0}` | **不是 iframe 问题**（假设被否定）|
| ② | `has_table_tag: false` / `pct_in_html: 0`（489 KB 主文档）| **零个表格、零个百分比** |
| ③ | `click` **4 种 CSS 选择器全失败** + `evaluate` 失败 | 全是 `shared page control or observation changed` |
| ④ | **本机 `example.com` 对照**：`click a` ✓ `evaluate 1+1` ✓ | **bsk 本身没问题**，是 **CME 反自动化** |
| ⑤ | 唯一业务 API `CmeWS/mvc/quotes/v2/contracts-by-number` = **403** | 纯 HTTP 不通，`network` 也拿不到响应体 |

⇒ **CME 明确在反爬** ✗ 反爬是**不可持续对抗**的 ✗
⇒ 每天浪费 **288 秒**（Chrome 跑 3 次，2 次超时 180s）
⇒ **Kalshi 已提供等价数据** ✓（`hike=80.5%` 比 CME 的 10-13 数据新 **23 天**）

### 改了什么

- `scripts/com.xingguo.fg-daily.plist`：**移除** `fetch_fedwatch.py` 那一步
  （命令长度 3070 → 2956，guard 数 23 → 22）
- **不改 `drift_monitor.py`** —— 它的 `fed` crosscheck 行为是
  「任一源缺失 ⇒ 报告明示并跳过」✓ 设计好的 ✓
- **不改 `check_freshness.py`** —— 它**没有引用 `fedwatch.csv`** ✓

### 仍保留的东西

- `scripts/fetch_fedwatch.py`（headless 版）和 `scripts/fetch_fedwatch_bsk.py`
  **代码保留** ✗ 只是不进链 ✓ 将来 CME 若开放数据可复用
- `fg_system/fed.py` 的 **Kalshi 兜底** ✓ 继续生效 ✓

---

## 🆕 2026-11-05 `fed` 因子的两个真 bug（已修）

### bug ①：`wk == wk` 挡不住 `None` ⇒ 整个 try 块跳过

```python
wk = fw.get("wk_hike_pct")        # Kalshi 兜底返回 None ✗
ctx["fw_delta_1w"] = (ctx["fw_hike"] - float(wk)) if wk == wk else None
                                                    ↑ None == None 是 True ✗
⇒ float(None) 抛 TypeError ✗ ⇒ 后面的 fw_date / fw_source 全没赋值 ✗
```

**症状**：简报显示「市场预期（CME FedWatch **None**）：维持 22.5% / 加息25bp 76.0%」

**修法**：`if (wk is not None and wk == wk)` ✓
（`wk == wk` 只能挡 `NaN` ✗ 对 `None` 无效 ✗）

### bug ②：兜底没返回 `date`，也没标注来源

- `fed_brief_text` 用 `ctx["fw_date"]` ✗ 而兜底 dict 没 `date` ✗
- 硬写「CME FedWatch」✗ 但实际可能是 Kalshi ✗ 误导 ✗

**修法**：
- 兜底 dict 加 `"date": _pick("date")` ✓
- 新增 `ctx["fw_source"]` ✓ 简报显示 `CME FedWatch 2026-10-14 · **Kalshi 兜底** ✗`

### 顺带修了一个测试

`tests/test_fedwatch_migration.py` 写死 `"date": "2026-10-13"` ✗
⇒ 新鲜度检查判定过期 ⇒ 走兜底 ⇒ 兜底没 `wk_hike_pct`/`m_hike_pct` ⇒ **4 个测试全挂** ✗
⇒ 改成 `_dt.date.today().isoformat()` ✓

---

## 🗄️ 2026-11-04 数据源：Stooq 已废弃 ✗ + CME 改用 bsk ✓

### Stooq：**实测不可用，代码已删** ✗

```
stooq_raw_head:
<!DOCTYPE html>...<noscript>This site requires JavaScript to verify
your browser.</noscript><script nonce="...">(async()=>{const c="AAAA...
```

⇒ Stooq 加了 **JS 挑战** ✗ 纯 HTTP **永远拿不到 CSV** ✗
⇒ 而 11 个标的**已全部补齐**（`TLT/XBI/ITB/KRE` 各 2514 行 ✓ 到 11-03 ✓）
⇒ 兜底**永远不会被触发** ✗ ⇒ 已删除（`config.STOOQ_API` /
  `fetch.parse_stooq_csv` / `fetch.fetch_symbol_stooq` / `fetch_symbol` 兜底块 /
  `diagnose_symbols` 的 `test_stooq`）

⚠️ **删代码时踩坑**：用「跳过 N 行」的粗糙脚本删 ✗ 误删了 `config.SYMBOLS` /
`UNDERLYING_MAP` / `LEVERAGE_RATIO` ✗ ⇒ 10 个测试失败 ✗
⇒ **已从 git 恢复 + 按「连续注释行往上吃」精确删** ✓
⇒ 教训：**删代码必须按语义定位，不能按固定行数** ✗

---

## 🆕 2026-11-04 CME FedWatch：改用 **bsk**（真实 Chromium）

### 为什么不用 headless

| 方案 | 实测结果 |
|---|---|
| `--dump-dom`（headless ✗）| 287KB ✗ 有 `FedWatch` 字样、有 `ZQ` 合约代码 ✗ **零个百分比数字** ✗ |
| 直接调 `CmeWS/mvc/quotes/v2/contracts-by-number` | **HTTP 403** ✗ |
| **bsk（真实浏览器 ✓）** | **待验证** ✓ |

### 新脚本 `scripts/fetch_fedwatch_bsk.py`

```bash
python scripts/fetch_fedwatch_bsk.py --dump-html /tmp/cme.html   # 先看结构 ✗
python scripts/fetch_fedwatch_bsk.py --write                     # 解析并写盘 ✓
```

**流程**（严格按 bsk lifecycle ✗ 否则报
`shared page control or observation changed` ✗）：
```
bsk session start            → 4 字母 id ✓
bsk navigate <url> --session → 打开 ✓
bsk wait-ms 8000 --session   → **等 JS 渲染** ✓（关键 ✗ 不等就是空表）
bsk get-html --session       → 渲染后 HTML ✓
bsk session stop <id>        → **必须停** ✓（成功/异常都停）
```

**⚠️ 已知限制**：
- 需 Mac 上 **Chrome 常驻 + bsk daemon 在跑** ✗
- 与 **OpenClaw agent** 抢浏览器会失败 ✗（`--retries` 缓解 ✓）
- `parse()` 的**字段映射待确认** ✗ —— 旧正则依赖 `<td class="number">` ✗
  而实测 `has_number_td: False` ✗ ⇒ **必须先 `--dump-html` 看真实结构** ✗

**✅ 好消息：Mac 端发飞书不用 bsk** ✓
`invest_research._send_feishu` 走**官方 API**（`open.feishu.cn` ✗ 纯 `urllib`）✓
⇒ **bsk 抓数据与发飞书不冲突** ✓
（只有 **Windows 侧**的 `feishu_send.py` 用 bsk 网页版 ✗）

**下一步**：
1. Mac 上 `fetch_fedwatch_bsk.py --dump-html /tmp/cme.html` ✓
2. 看 HTML 里概率数据的**真实结构** ✗ 再改 `parse()` ✓
3. 验证通过后接进每日链（替换 `fetch_fedwatch.py` ✗）

---

## 🗄️ 2026-11-04 数据源：加 Stooq 备选（已废弃 ✗ 见上）

**为什么改（问题）**：
- `config.FETCH_SYMBOLS` **39 个** ✗ 而 `prices.csv` 长期只有 **36 个** ✗
- 缺的 11 个全是**主流 ETF**：`DIA / EWY / ITB / KRE / TLT / VGK / XBI / XLE / XLK / XLU / XLV`
- `fetch_symbol` 已有 `assetclass=etf→stocks` 回退 + 3 轮退避重试 ✗ 仍抓不到 ✗
- **根因**：`fetch_symbol` 抓不到时 `return 空表` ✗ ⇒ `update_prices` 对空表**不报错** ✗
  ⇒ 该标的**静默消失** ✗（`TLT` 是 H-065 必需 ✗ `XBI`/`ITB`/`KRE` 是关注列表底层必需 ✗）

**改了什么**：
- `config.STOOQ_API = "https://stooq.com/q/d/l/?s={symbol}.us&i=d"`
- `fetch.parse_stooq_csv()` / `fetch.fetch_symbol_stooq()`
- `fetch_symbol` 在「Nasdaq 空表」时**自动试 Stooq** ✓（不 raise ✗ 双失败才返回空表 ✓）
- Stooq 走 **直连→代理双路径** ✓ —— **不用 `config.PROXY`** ✗（那是**公司代理** `10.30.6.49:9090` ✗ 家里不可达 ✗）
  顺序：`FG_PROXY` → `HTTPS_PROXY` → `HTTP_PROXY` → `config.PROXY`

**为什么不直接把 `stooq.com` 加进 `PROXY_HOSTS`**：
- `PROXY_HOSTS` 是**静态白名单** ✗ 走代理就永远走 ✗
- 而「公司能连代理、家里不能」✗ ⇒ 静态分流**两边都会坏一边** ✗
- 实测（国内/Windows）：`stooq.com` **直连超时** ✗ 需代理 ✓
- ⇒ 只能**运行时先试直连、失败再试代理** ✓

**已知限制**：
- Stooq 一次返回**全历史** ✗ 不支持 `fromdate` ⇒ 本地按 `fromdate` 过滤 ✓（流量略大 ✗）
- 失败返回纯文本 `No data` ✗ ⇒ `parse_stooq_csv` 显式识别 ✓ 返回空表 ✓
- ⚠️ **未在 Mac 验证**（Windows 无代理 ✗ 测不通 ✗）⇒ 下次 Mac 跑 `diagnose_symbols` 时看 `fetch_ok`

**待办**：
- ① Mac 上跑一次 `diagnose_symbols`（`symbols=TLT,XBI,ITB,KRE` ✗）确认 Stooq 可用
- ② 若 Stooq 也不通 ⇒ 换 Yahoo `v8/finance/chart/{sym}`（需代理 ✓）

### 🔴 铁律（2026-11-04 用户裁定）：数据源改动**必须在 Mac 侧验证**

```
Windows 端受限于**公司网络** ✗
  ⇒ 部分外网域名直连不通 ✗（实测 `stooq.com` 超时 ✗）
  ⇒ 代理是**公司代理** `10.30.6.49:9090` ✗ 家里不可达 ✗
⇒ **任何数据源改动，Windows 侧「测通」不代表可用** ✗
⇒ 必须下发到 Mac 跑一次才算验证 ✓
```

**验证方式（按改动类型选）**：

| 改动 | 验证动作 |
|---|---|
| 新增/修改 fetch 脚本 | `run_fetch_step --script=<名> --args=<参数>` |
| 改 `fetch_symbol` / 备选源 | `diagnose_symbols --symbols=<清单> --test_stooq=1` |
| 改整批抓取逻辑 | `fetch_prices`（回报 `prices.csv` 最新日期 ✓）|

**⚠️ `test_stooq=1` 的意义**：
- Nasdaq 能抓到的时候，Stooq 兜底**根本不会被触发** ✗
- ⇒ 不单独测就**永远不知道兜底是否可用** ✗

### 🆕 CME FedWatch 适配（2026-11-04 用户要求「CME 要适配」）

**已加两个诊断开关**（`scripts/fetch_fedwatch.py`）：

```bash
fetch_fedwatch.py --dump-urls      # 从 netlog 列出所有相关 URL ✗ 找新接口
fetch_fedwatch.py --keep-netlog    # 保留 8MB+ netlog 到 /tmp 供离线分析
```

**已确认事实**：`netlog 8.7MB` ✗ 但**零个 `QuikStrike` 请求** ✗
⇒ CME 换了接口 或 加了反爬 ✗

**下一步**（在 Mac 上跑）：
```bash
run_fetch_step --script=fetch_fedwatch.py --args=--dump-urls
```
⇒ 拿到 URL 清单后，看 `CmeWS/mvc/*` 或新域名，再决定怎么改解析 ✓

---

## 🆕 2026-10-27 MT-76：C1 BAA10Y 信用利差因子进评测池（闭环）

- **分工**：① Mac 供数（带 available_date 的 `Data/raw/fred_baa10y_avail.csv`，T+5 自然日显式滞后防 lookahead）→ ② Windows 写因子 `fg_system/factors/credit_spread.py` → ③ Windows 必测 lookahead → ④ Mac 跑 IC/IR/分层单调性 → ⑤ 回写。
- **落地**：②③ 由 Windows sync_1027b 交付（patch 因 docs 基准漂移 git apply 整包拒绝，已人工拆解）；`credit_spread.py`（level/zscore/score，`merge_asof(backward,on=available_date)` 禁 ffill）+ `tests/test_credit_spread.py`（11 passed lookahead）；④ 固化 `scripts/eval_baa10y.py`。
- **④ 评测结果**（样本 2019-09-26→2026-10-26，z 非空 n=1779，756 warmup）：**H10 rank_ICIR=0.548（n1710，近窗0.517 无衰减，pearson 0.566）= 唯一过门槛 horizon**，verdict=通过、best_horizon=10；H5 0.473 / H20 0.459 / H40 0.411 未达 0.5；分层 mono H5/10/20=1.000、H40=0.900，top-bottom 随 horizon 单调。正交性：~putcall −0.076、~breadth −0.089（近零正交）；~vix −0.484、~fg_index −0.450（中等负相关非重复）；~fed +0.604（偏高留意）。
- **口径**：只进评测池、**不进合成权重（走 M2.2）**；未回头调窗口/滞后凑数；待回测裁判/人工审批。已推送 `be29d57`，结论飞书回传协作群。

## 🆕 2026-10-26 方向 A：每日链新鲜度治理（本轮落地）

- **取证结论**：`task_monitor.collect_status()` 当前 all_ok，12 项数据全在容忍窗、9 个 launchd 任务全注册 ⇒ 任务页监控口径本身正确，用户截图里的陈旧是历史停更、现已恢复，**无需改前端/监控逻辑**（任务页 `index.html` 动态遍历 `d.data`，新增项自动渲染）。
- **唯一现存真实停更 = FRED 三序列**：`fred_DFF`（factor_screen 生产用）/`fred_DGS10`（H-065 归因控制量）/`fred_T10Y2Y`（term 观察）此前**既不在每日链也不在监控** ⇒ 静默停更多日无人发现。
- ✅ **修复**：① 手动补跑 `fetch_fred.py --series DFF,T10Y2Y,DGS10`（本地 key 走官方 API，补到最新工作日）；② `task_monitor.py` DATA_CHECKS 增三项（列名 `observation_date`，tol=5 自然日吸收周末/节假日/T+1）；③ `server.py` `_RETRY_MAP` 增三项 fred 页面重试映射；④ 已安装 `com.xingguo.fg-daily.plist` 在 kalshi_fed 后插入 fetch_fred 步骤并已 bootout+bootstrap 重载。
- **研究候选不挂每日**：`BAA10Y`/`BAMLH0A0HYM2`/原油 `DCOILWTICO` 属按需研究（verify_hypotheses / crude_factor_check），非常态生产，不挂每日链、不纳入监控。
- ✅ **plist 回流入库**：仓库 `scripts/` 新增/更新全部贪恐 launchd 副本（fg-daily 覆盖 + evolve-verify/evolve-weekly/fg-monitor/fg-realtime/fg-sync-watcher/kb-update/quarterly-walkforward/shoutu-daily/shoutu-history）；`fg-dashboard` 因含 Basic 密码只入库**脱敏模板**（`CHANGE_ME`，密码不进 git）。
- 相关测试 118 passed（task_monitor + dashboard）；全量回归见提交说明。

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
