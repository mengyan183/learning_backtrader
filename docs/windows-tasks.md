# Windows 端待开发任务清单（Windows Tasks）

> 用途：给 Windows 端（公司电脑）一份**具体的、可立即开工**的开发任务清单（不是类别）。
> 来源：blocked-registry.md / hypotheses.md 审计 / roadmap 增强项，由 Mac 维护、随 fg-sync 同步。
> 机制：Mac 端 `scripts/push_todo.py` 收到「同步待办」时读取本清单**待做（状态非 ✅）** 行并回传；
> Windows 端完成一项 → 打包回传 fg-sync → Mac 入库后把状态改为 ✅ 并提交。
> 更新纪律：新增/解除任务必须同步本表；每行五要素齐全（编号/任务/说明/验收/状态）。
> 创建：2026-10-10。配套：docs/dual-end-workflow.md（分工）、docs/windows-agent-prompt.md（开场）。

状态标记：待做 / 进行中 / ✅ 完成（进行中任务 Windows 端完成收尾后改 ✅）

---

## 待做任务（Windows 可立即开工）

| 编号 | 任务 | 说明与来源 | 验收标准 | 状态 |
|---|---|---|---|---|
| WT-07 | verify_hypotheses.py 覆盖全部 open 假说 | 当前仅支持 H-005/H-007/H-024/H-025/H-027/H-029/H-032；扩展支持**其余修订后 open 假说**：H-006/H-008/H-009（B-3 修订口径）、H-011/H-013（B-5）、H-014~H-022（B-4 修订，含 H-010/H-012 的极值依赖/切换点判据）、H-026（GDXU 占比）、H-030（TVL 背离，数据源未接入时输出等待）、H-031（fed×CRCL，样本已 338/240）。每个假说按其 hypotheses.md「检验方法」列实现验证函数（数据均走 config 路径）。来源：evolution/hypotheses.md 全部 open 行 | `--help` 列出新增假说全集；dry-run 无数据时报"数据缺失（路径）"退出 2 而非崩溃；有数据时输出判据判定（adopted/falsified/insufficient） | ✅ sync_1010e 入库（b5e9ec4）：verify_hypotheses.py +469 行覆盖全部 open 假说（H-006/008/009/011/013/014~022/026/030/031）；--dry-run/--out 支持；Mac 复核 --help + 92 passed | 
| WT-08 | 核心脚本测试补齐 | 以下脚本无测试：`calibrate_extreme.py`（WT-03 产物）、`evolve_approve.py`（WT-02 产物）、`evolve_h001.py`、`evolve_decay.py`、`evolve_weekly.py`、`execution_confirm.py`、`factor_screen_extend.py`、`evolve_propose.py`——至少为其中 **6 个**补 `tests/test_*.py`（mock 数据/命令路径，不依赖真实 Data/）。来源：scripts/ 测试覆盖盘点（2026-10-10） | 6 个测试文件存在且增量 pytest 全绿；测试用 fixture/mock 不读真实 Data | ✅ sync_1010e 入库（b5e9ec4）：补齐 8 个测试（calibrate_extreme/evolve_approve/evolve_decay/evolve_h001/evolve_weekly/execution_confirm/factor_screen_extend/validate_stablecoin_data）+ test_verify_hypotheses 扩展；Mac 复核 92 passed（2.65s） |
| WT-09 | 新因子候选开发（F-010+） | `scripts/factor_screen_extend.py` 扩展 ≥2 个候选因子（走 IC/IR 检验框架）：候选①新闻情绪（news_sentiment.csv 的 score 列，B-7 已落地数据）、候选②Put-Call 情绪（putcall_total 列，B-6 已落地数据）、候选③波动率结构（VIX 期限结构 term 的滚动变化率）。每个候选实现 factor 函数 + 注册表登记（factors.md 同步补 F-010~F-012 行）。IC/IR 实际检验在 Mac 跑（需 Data）。来源：roadmap E4 因子库深化 | factor_screen_extend.py 新增 ≥2 个 factor 函数 + 注册；--list 输出含新因子；factors.md 登记行已同步 | ✅ sync_1010e 入库（b5e9ec4）：factor_screen_extend.py +181 行，F-010 新闻情绪/F-011 Put-Call/F-012 波动率结构均已注册（draft）；Mac 复核 --list 输出 3 新因子；IC/IR 实检待 Mac 数据 |
| WT-11 | evolve_propose.py 测试补齐 + 全量回归 | WT-08 已补 8 个脚本测试，**唯一漏网**：`scripts/evolve_propose.py`（C-2 变更提案产物）仍无测试。补 `tests/test_evolve_propose.py`（mock 命令路径/提案文件，不依赖真实 Data/）；补齐后跑**全量 pytest 回归**（~900 用例）确认 0 fail。来源：WT-08 覆盖盘点补漏 | 测试文件存在且增量 pytest 绿；全量回归 0 fail 输出回传 | 待做 |

## 默认动作（不占编号）

- 全量 pytest 回归（~900 用例）：每次开发收尾必跑，Mac 只跑增量 --quick。
- 本清单为空时：以 docs/NEXT-SESSION.md / docs/blocked-registry.md 为准自查，或等 Mac 下发新任务。

---

## 已完成（留痕）

| 编号 | 任务 | 完成依据 | 完成日期 |
|---|---|---|---|
| WT-01 | H-024/H-025/H-027/H-029/H-032 口径修订 | sync_1010b 入库（b63081c）：5 条已按真实列重措辞（core_position/zone/fg_index/trend_blocked_us/trend_blocked_crypto），状态 open（修订口径）；本地复核 5/5 确认 | 2026-10-10 |
| WT-02 | C-3 增强：提案飞书推送 | sync_1010b 入库（b63081c）：evolve_approve.py 支持 --push / --push --dry-run（写分片 → feishu_send.py --pkg）；本地验证 --help 与注释 | 2026-10-10 |
| WT-03 | B-8 极端规则校准脚本预写 | sync_1010b 入库（b63081c）：scripts/calibrate_extreme.py（熔断标称 85 实测 75.96~87.30 / 极恐标称 10），本地实测可运行 | 2026-10-10 |
| WT-04 | 新假说验证脚本骨架（H-030/H-031/H-033） | sync_1010d 入库（e8959ca）：scripts/evolve_verify_new.py 统一骨架（非一假说一脚本）；本地 dry-run 实测 H-030 0/240 等待 / H-031 338/240 / H-033 309/240 待检验，`[dry-run] 未写回`；tests/test_evolve_verify_new.py 通过 | 2026-10-10 |
| WT-05 | verify_hypotheses.py 扩展（修订口径批量验证） | sync_1010d 入库（e8959ca）：scripts/verify_hypotheses.py 支持 H-005/H-007 + 修订口径 H-024/025/027/029/032（--dry-run/--out）；本地 --help 实测；tests/test_verify_hypotheses.py 通过 | 2026-10-10 |
| WT-06 | B-10 稳定币数据源 fetch 脚本 | sync_1010d 入库（e8959ca）：scripts/fetch_stablecoin_usage.py（--api/--require-key/--retries → Data/raw/stablecoin_usage.csv）；本地 --help 实测；tests/test_fetch_stablecoin_usage.py 通过；**三测试合计 35 passed** | 2026-10-10 |
