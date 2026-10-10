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
| WT-10 | 稳定币数据质量校验脚本 | 为 B-10/WT-06 产物写 `scripts/validate_stablecoin_data.py`：校验 Data/raw/stablecoin_usage.csv（若不存在则明确报"数据未拉取"退出 2）：缺失率（>5% 告警）、异常值（流通量/交易量 ≤0 或环比跳变 >10× 标记）、格式（date 可解析、列齐全）、输出校验报告。来源：blocked-registry B-10（H-034 数据质量前置） | 脚本存在、--help 可运行；无数据时退出 2 并提示先跑 fetch_stablecoin_usage.py；有数据时输出缺失率/异常清单 | ✅ sync_1010e 入库（b5e9ec4）：scripts/validate_stablecoin_data.py（--in 参数）；sync_1010f 追加 tests/test_validate_stablecoin_data.py；Mac 复核 --help + 92 passed + 无数据路径实测退出 2 并提示先跑 fetch（2026-10-10） |
| WT-11 | evolve_propose.py 测试补齐 + 全量回归 | WT-08 已补 8 个脚本测试，**唯一漏网**：`scripts/evolve_propose.py`（C-2 变更提案产物）仍无测试。补 `tests/test_evolve_propose.py`（mock 命令路径/提案文件，不依赖真实 Data/）；补齐后跑**全量 pytest 回归**（~900 用例）确认 0 fail。来源：WT-08 覆盖盘点补漏 | 测试文件存在且增量 pytest 绿；全量回归 0 fail 输出回传 | ✅ sync_1010g 入库（6441c4e）：test_evolve_propose.py（+102）+ verify_hypotheses 再扩展（+159）；Mac 复核 test_evolve_propose + test_verify_hypotheses 49 passed |
| WT-12 | 项目双维审查（代码 + 规划） | Windows 端 `git pull` 最新后执行：**①代码审查**——审 `fg_system/` + `scripts/` 核心脚本：结构缺陷、测试盲区、安全隐患、纪律红线冲突（OOS 禁调参/LLM 不裁决/Data 不入库），findings 按 严重/一般/建议 分级并附 文件+行号；**②规划审查**——对照 `docs/roadmap.md`/`windows-tasks.md`/`blocked-registry.md`/`NEXT-SESSION.md` 实际进度，找状态与事实不符、优先级倒挂、遗漏阻塞项（≥3 条）。产出 `docs/review/代码审查-YYYY-MM-DD.md` + `docs/review/规划审查-YYYY-MM-DD.md`。结论为建议/待确认，不代 Mac 裁决（数据/实检仍 Mac 跑） | 两份审查文档存在并回传；每项 finding 含 文件+行号+严重级+建议；规划审查 ≥3 条差异；无数据依赖项（Data/ 不在审查范围） | ✅ sync_1010h 入库（a239c8e）：代码审查 16 条（S-1~S-2 / G-1~G-7 / R-1~R-7）+ 规划审查 5 条差异（≥3 达标），均含 文件+行号+证据。Mac 裁决处理：S-1(import sys)/S-2(HERMES_KEY 去默认值)/G-2(4 处 /tmp→tempfile)/G-3(open_id 环境变量+plist 注入)/G-6(utcnow→tz-aware)+R-1(补 sys_python 测试)已修复并验证（test_freshness 5 passed）；规划差异 1 已解决（WT-07~10 ✅）、差异 2（H-005→falsified/H-007→adopted）、差异 3（B-11 登记）、差异 4/5（NEXT-SESSION 更新 + F-010~12 IC/IR 登记 Mac 待办）已落地；G-1/G-4/G-5/R-2~R-7 与 G-7/R-4 待确认项登记 NEXT-SESSION |

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
