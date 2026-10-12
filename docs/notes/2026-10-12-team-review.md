# Windows 端回传 · 2026-10-12（四）团队评审交付

## 交付物

`docs/review/团队评审-2026-10-12.md`（**请 Mac 优先看 §1 与 §3**）

## 方式（可复现）

- **对象**：Gitee 主线 `origin/main = 2361124`（含 Mac 侧 FRED/F-015/L3.5/R1.x/M2.x/L3.x 全部工作）
- **快照**：`git worktree add --no-checkout` + 非 cone 稀疏检出（`fg_system/ scripts/ docs/ tests/ evolution/ skills/`）⇒ **246 个 .py** 落地
- **评审**：**4 个独立 Agent 并行**，各守一域、只读、互不通信（分离工作者与检查者）
- **主 Agent 抽查复核 4 条，4/4 命中**（未发现 Agent 编造）

## 最重要的 4 条（均已由我实测复核）

1. **`scripts/evolve_review.py:40` 硬编码 Hermes 会话密钥仍在** ✗
   —— 而 `docs/windows-tasks.md` 的 WT-12 行记「S-2(HERMES_KEY 去默认值)已修复」⇒ **假记录**。
   泄露面真实：`make_feishu_bundle.py` 的 keep 含 `scripts/**`，随飞书包外发。**建议删除默认值 + 轮换密钥 + 修正该行记录。**
2. **`fg_system/human30.py:78-79` 静默降级 ⇒ 不可逆数据丢失**：`except Exception: return {"records": []}` 把"文件损坏"当"首次无记录"，随后 `_save` 整文件覆盖 ⇒ 打卡记录永久丢失且无告警。
3. **`scripts/evolve_weekly.py:149` 周报推送静默失效**：`feishu_send.py` 无位置参数 ⇒ 传 `out_path` 直接 `SystemExit(2)`，而 `check=False` 吞掉 ⇒ 永不成功也不报错。`evolve_approve.py:19-23` 已记过同一坑，本文件未同步修。
4. **`fg_system/backtest/attribution.py:26-27` shift 错位**：`target_position` 已 shift(1) 而 `trend_blocked` 未 shift ⇒ 归因错位一天 ⇒ 影响「趋势过滤是否有用」的判定 ⇒ **影响真实仓位**。

## 红线结论摘要（详见报告 §3）

- ① OOS 禁调参：**轻度违规**（`evolve_propose`/`variant`/`walkforward` 用 OOS 做采纳裁决，且被测试固化；**OOS 起点存在两套口径**）
- ② LLM 不裁决：**合规**（执行最干净）
- ③ Data 不入库：**部分违规**（`fetch_market_data.py` 对原始 CSV 整表原地重写）
- ④ 密钥禁提交：**违规**（同 S-1 + `invest_research.py:31` open_id + `fg-sync-bypass.py:138` chat_id）

## 测试盲区摘要（详见报告 §4）

`fg_system/models/` **整包零测试**（hmm/markov/evt/bayes_update，却有生产用途）｜`factors/putcall.py`·`factors/fed.py`（六因子之二）无独立单测｜`scripts/sensitivity_scan.py`（最接近触碰红线①的调参入口）零测试｜`config` **无任何非法参数用例**且无 `validate()`｜`test_runner.py` 无异常路径｜**红线守卫疑似缺失**（待确认 `test_secret_paths_are_gitignored` 是否已随 `sync_1010k` 入库）

## ⚠️ 评审局限（如实声明）

`AGENTS.md` 与 `.gitignore` 在快照中**不可读** ⇒ 红线④「密钥是否被 gitignore 覆盖」**无法判定**。原因见报告 §7：**公司 Skyhigh SWG 拦截 `.gitignore` 这个 blob**（`git worktree add` 3 次重试均卡在同一对象，确定性失败），绕过办法是 `--no-checkout` + `sparse-checkout set --no-cone` + **`MSYS_NO_PATHCONV=1`**。

**连带纠正**：此前用 `git show origin/main:.gitignore` 得到的**空输出**，应重新解读为「被 SWG 拦截」而非「Mac 侧没有该规则」——我上一轮据此得出的判断需要修正。
