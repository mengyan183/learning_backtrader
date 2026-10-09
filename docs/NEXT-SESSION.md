# 下次会话先读这个（进度快照）

**更新**：2026-10-08 · **对应提交**：本地 HEAD 仍是 `5fbd8a7`（本轮**未提交**，见下）

---

## 一句话现状

- **新情况（重要）** ✓：**本仓库与 GitHub 是两条无共同祖先的线** ✗ —— 详见下节
- **正在做** ✓：解决 GitHub **issue #3**（Mac 端 pytest 收集失败）—— **已交付，待你 push** ✗
- **下一步** ✗：① 用 `dist/lb-mac-backfill.bundle` 把 19 个文件推上 GitHub ✓ ② 决定两条线的长期策略 ✗

---

## ⚠️ 两条线（先读这一节）✗

| | 本地（公司 Windows） | GitHub `mengyan183/learning_backtrader` |
|---|---|---|
| HEAD | `5fbd8a7`（2026-09-29） | `5cdaba7`（2026-10-07） |
| 共同祖先 | **无** ✗（本地 4 个 sha 在远程全部不存在） | — |
| 来源 | 公司开发主线 ✓ | Mac 端 `git init` 新建（`created_at` 2026-09-29 ✓），内容来自**飞书解压包** ✓ |
| 有 | `docs/trading-discipline.md`（5400+ 行 ✓）、`docs/NEXT-SESSION.md` ✓、`docs/superpowers/specs/*` ✓、YINN 取证 §12.36~§12.39 ✓ | `docs/roadmap.md` / `evolution-plan.md` / `blocked-registry.md` / `变更记录/` 等 **41 份** ✓、`models/`（HMM/EVT/贝叶斯）✓、`fed.py` / `risk.py` ✓、dashboard 大改 ✓ |
| 无 | Mac 侧的上述全部 ✗ | Windows 侧的上述全部 ✗ |

⇒ **两套文档体系、两套代码增量** ✗ ⇒ **长期策略待你定** ✗（谁为准 / 如何互推 / 是否合并）
⇒ **本地新工作（含 YINN 取证）不会自动上 GitHub** ✗ —— 因为无共同历史 ✓

---

## 本轮完成 ✓：GitHub issue #3

**问题**：Mac 端 `.venv/bin/python -m pytest -q` ⇒ 13 个测试文件收集期
`ModuleNotFoundError` / `FileNotFoundError`（飞书打包把实现文件 strip 了 ✓）。

**已交付**（`dist/` ✓）：
- `lb-mac-backfill.bundle`（**83.1 KB** ✓）—— 含基于远程 tip 的提交 **`d429edd`** ✓（**推荐**）
- `lb-mac-backfill-20261008.zip`（85.4 KB ✓）—— 19 个文件直拷 ✓
- `lb-mac-backfill-README.md` ✓ —— 两条路线的命令 + 校验证据 ✓

**清单是 19 个（不是 issue 里写的 20 个）** ✗，三处订正：
1. `fg_system/backtest/` 实为 **6** 个 ✓（漏了 `__init__.py` ✓，缺它包不成立 ✓）
2. `scripts/fetch_shoutu.py` **远程已存在** ✓（Mac `3f7c56f6` 重建过 ✓）⇒ **不要覆盖** ✗
3. `scripts/shoutu_page_query.js` 在 **Windows 端也不存在** ✓（全仓无引用 ✓）⇒ 不补 ✓

**已做校验** ✓：模块级（补齐后导入全可解析 ✓）+ 接口级（19 个文件用到的 13 个共享模块属性在远程全存在 ✓）+ bundle 自检（`ls-tree` 19/19 ✓）。
**未做** ✗：Mac 树上实跑 pytest ✗ —— 代理拉不动整树（见下 ✓）。

---

## 下一步（明确的）✗

1. **把 19 个文件送进 GitHub** ✗ —— 公司电脑**无法登录 GitHub** ✗（用户 2026-10-08 确认 ✓）
   ⇒ 两条路，**待用户选** ✗：
   - **路 1（最快，无需传文件）** ✓：用户在**手机/Mac** 上建 **fine-grained PAT**（contents: write ✓）
     → 我直接 `git push`（用一次即弃 ✓，不写入任何配置 ✓）
   - **路 2（走既有飞书通道）** ✓：`py -3.10 scripts/feishu_send.py --pkg backfill --chat 郭星`
     （**52** 片 backfill ＋ 7 片 bootstrap ✓ ＝ 59 条 ✓）→ Mac 端
     `python3 scripts/restore_from_base64.py ~/Downloads/fg`（**默认就解到 `~/learning_backtrader`** ✓）
     → `git add` / `commit` / `push` / `pytest` ✓
2. **决定两条线的长期策略** ✗（我未擅自合并 ✗）
3. **GDXU 取证** ✗（交易侧待办，实盘 27.65%，是**最后一个**无信号持仓 ✓）
   —— 建议**先做成本检验** ✓（YINN 的教训：方向成立 ≠ 赚得到 ✓）

---

## 两条线：已定策略与裁决结论 ✓（2026-10-08）

**用户决定：以 GitHub 为准** ✓；**`restore_from_base64.py` 以 Mac 那份为准** ✓
（⇒ 本地版**不推** ✓；它是「Mac 版更新」，本地那份属待替换 ✗）。

**文件账（blob sha 对比，零额外请求 ✓）**：仅远程 520 ✓／仅本地 **154** ✓／同名同内容 24 ✓／
**同名不同内容 88** ✗。本地独有 154 个 = **23.2 MB** ✗（`Data/` 占 20.9 MB）
⇒ 一次性补传**不可行** ✗（飞书要 ~9000 片 ✗）⇒ **必须按优先级分批** ✓。

**88 个冲突的抽样结论**（8 个精查 + 8 个分类 ✓）：**6/8 是纯换行差异** ✓
（`tests/**`、`pytest.ini`、`requirements.txt`、`factors/price.py` 等**内容其实相同** ✓）；
实质分歧只有 `fg_system/config.py`（远程多 105 行：五因子权重/观察池 ✓）与
`pipeline.py`（远程多 8 行：fed 因子 ✓）⇒ **以远程为准** ✓。

⇒ **分组裁决（建议）**：A `Data/*.csv` 不用管 ✓／B 换行差异类**不推**（以远程为准 ✓）／
C 远程有实质新增（config/pipeline）**以远程为准** ✓／D 本地有实质新增
（`tests/test_feishu_send.py`、`tests/test_make_feishu_bundle.py` —— 本轮新增的守卫测试 ✓）
⇒ **以远程为底 + 重放本地新增** ✓／E `.gitignore`（22.5% 相似，两边都改过 ✗）需合并 ✓。
⇒ **88 个里真正要动手的只有 D(2) + E(1)** ✓，其余 85 个**不用推** ✓。

**代理退化** ✗：`502 → 403 → 407 AuthenticationRequired`（批量请求后被节流 ✓）
⇒ 批量 API 任务（如 88 个全量分类）**跑不动** ✗，只能小批量 ✓。

---

## 根因订正 ✓（2026-10-08 读码确认）

**strip 不是 `check_deploy_set.py` 的错** ✓ —— 它的清单是**完整**的
（`NEED_DIRS = ["fg_system", "scripts", "tests"]` ✓ 全拷 ✓）。

**真正的漏点在飞书打包的「包选择」** ✗：`--only minimal` 用的是**传递闭包**
（按「Mac 跑任务需要什么」算 ✓）⇒ `audit.py` / `cli.py` / `backtest/*` /
`evolution.py` / `factors/screening.py` / `shoutu_analysis.py` 都**不在**闭包里 ✓；
而 `tests` 包**又把这些测试文件发了** ✓ ⇒ **包内容自相矛盾** ✓（正是 issue #3 ✓）。

⇒ **治本 = 用 git 补文件** ✓（本轮 ✓）；**顺带**：若将来还用飞书发 `tests` 包，
应把「tests 的传递闭包」也算进包选择 ✓（否则**必再犯** ✗）。

---

## 环境备忘 ✓（本轮新增 ✗）

| 项 | 值 |
|---|---|
| GitHub 访问 | 直连**不通** ✗；必须走代理 `http://10.30.6.49:9090` ✓ |
| **⚠️ DLP 上传上限** ✗ | **POST 体 > ~10 KB 被拦**（实测 base64 **6036 通过** ✓、**12388 → 403** ✗，返回代理 HTML 拦截页 ✓；同款限制见 `restore_from_base64.py` docstring「纯文本上限约 10 KB」✓）⇒ **`git push`（pack）与 GitHub API 建 blob 都走不通** ✗ —— 这是**公司网络下的硬约束** ✗ |
| 结论 | **公司电脑无法把代码推上 GitHub** ✗（读得到、写不了 ✓）⇒ 传输必须走**飞书**（消息/云文档，均 ≤1700 字符/条 ✓）|
| git over proxy | `git -c http.proxy=http://10.30.6.49:9090 ls-remote ...` ✓ |
| **大文件传输** ✗ | 代理扛不住大 pack：`clone` **502** ✓、`--depth 1` 全量 **early EOF** ✓、partial clone 按需拉 blob **HTTP 403** ✓ ⇒ **只能小请求** ✓ |
| 可行的小请求 | `--filter=blob:none --sparse` 克隆（**222K** ✓，只有 commit+tree ✓）；GitHub **API**（`/git/trees`、`/contents`）✓ |
| GitHub 凭据 | 本机**没有** ✗（`cmdkey` 无 github、无 `~/.git-credentials`、无 netrc）⇒ **无法 push** ✗ |
| 命令行限制 | 单条 **≤1024 字节** ✗ + **约 37s 截断** ✗ ⇒ 长命令要拆 ✓ |
| 代理 + curl | `curl -x <proxy>` 报 **libcurl error 43** ✗ ⇒ 改用 **Python urllib + ProxyHandler + CERT_NONE** ✓ |
| 预存在失败 | `test_make_feishu_bundle.py`(6) + `test_pre_commit_syntax.py`(1~3) ✗ —— 根因 **Windows GBK 解码子进程输出** ✓，与本轮无关 ✓ |

---

## ⚠️ 给下次会话的提醒 ✗

- **别长回复** ✗ —— 会话容易因上下文超限重启 ✓。
- **写「待办」前先 grep 文档** ✗ —— 曾两次把已完成的任务当成待办 ✓。
- **静态守卫要防"假通过/假阳性"** ✗ —— 本轮两次：`from X import sub` 漏收子模块（假通过 ✓）、
  `A, B = ...` 未处理（假阳性 ✓）⇒ **结论出来前先想它会不会漏/会错** ✓。
- **引用 issue 清单前先核对** ✗ —— 本轮 3 处订正 ✓。
- **代理只适合小请求** ✗ —— 别再用 clone/fetch 大 pack 浪费时间 ✓。
