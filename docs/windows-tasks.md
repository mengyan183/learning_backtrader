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
| WT-12 | 项目双维审查（代码 + 规划） | Windows 端 `git pull` 最新后执行：**①代码审查**——审 `fg_system/` + `scripts/` 核心脚本：结构缺陷、测试盲区、安全隐患、纪律红线冲突（OOS 禁调参/LLM 不裁决/Data 不入库），findings 按 严重/一般/建议 分级并附 文件+行号；**②规划审查**——对照 `docs/roadmap.md`/`windows-tasks.md`/`blocked-registry.md`/`NEXT-SESSION.md` 实际进度，找状态与事实不符、优先级倒挂、遗漏阻塞项（≥3 条）。产出 `docs/review/代码审查-YYYY-MM-DD.md` + `docs/review/规划审查-YYYY-MM-DD.md`。结论为建议/待确认，不代 Mac 裁决（数据/实检仍 Mac 跑） | 两份审查文档存在并回传；每项 finding 含 文件+行号+严重级+建议；规划审查 ≥3 条差异；无数据依赖项（Data/ 不在审查范围） | ✅ sync_1010h 入库（a239c8e）：代码审查 16 条（S-1~S-2 / G-1~G-7 / R-1~R-7）+ 规划审查 5 条差异（≥3 达标），均含 文件+行号+证据。Mac 裁决处理：S-1(import sys)/S-2(HERMES_KEY 去默认值)/G-2(4 处 /tmp→tempfile)/G-3(open_id 环境变量+plist 注入)/G-6(utcnow→tz-aware)+R-1(补 sys_python 测试)已修复并验证（test_freshness 5 passed）；规划差异 1 已解决（WT-07~10 ✅）、差异 2（H-005→falsified/H-007→adopted）、差异 3（B-11 登记）、差异 4/5（NEXT-SESSION 更新 + F-010~12 IC/IR 登记 Mac 待办）已落地；G-1/G-4/G-5/R-2~R-7 与 G-7/R-4 待确认项登记 NEXT-SESSION<br>⚠️ **更正（2026-10-12，Windows 端实测）**：本条所记「S-2(HERMES_KEY 去默认值)已修复」**与事实不符** —— `scripts/evolve_review.py:40` 的硬编码默认值**仍在**（`os.environ.get("API_SERVER_KEY", "32b64f3f…")`，64 位 hex）。经用户 2026-10-12 裁决**决定不修**（风险已知悉并接受），但**记录必须更正**，以免后人据此以为已修。 |
| WT-13 | 代码审查剩余项修复（9 项） | `git pull` 最新后执行 WT-12 审查的**一般/建议**级剩余项（均无 Data 依赖，Mac 已确认可 Windows 做）：**G-1** dashboard 不展示 freshness_warning（`report.render_html` 顶部渲染告警条 + 守卫测试）；**G-4** 多处异常静默吞噬（`except Exception: pass` 类，改为写日志/上报，审计 `fg_system/`+`scripts/`）；**G-5** OKX/NVIDIA key 经 curl argv 传输（`sync_positions.py`/`evolve_review.py` 改 env 注入或 `--config` 文件，禁止 argv 明传）；**R-2** evolve_approve 提示漂移（提示语与提案实际状态对齐）；**R-3** walkforward 循环内重复 apply_variant（去重/跳过已应用）；**R-5** legacy.py 死代码清理（删除或标注 deprecated + 测试）；**R-6** NewsAPI query key 硬编码（`fetch_news.py` 改 env 读取）；**R-7** check_freshness.py 退出码恒 0（无新鲜告警时退出 1）。R-4（stablecoin_key gitignore）**Mac 已修**，跳过。来源：docs/review/代码审查-2026-10-10.md §1-§6 | 每项改动附 文件+行号；增量 pytest 全绿；新增/修改守卫测试覆盖 G-1/R-3/R-7；打包回传（make_feishu_bundle.py） | ✅ sync_1010k 入库（55c0e4c，18 文件）：G-1(告警条+test_report_warning)/G-4(freshness/legacy 异常降级)/G-5(sync_positions/evolve_review key→env+test_sync_positions_creds)/R-2(evolve_approve)/R-3(walkforward 去重+test)/R-5(legacy deprecated+test)/R-6(fetch_news key→env+test)/R-7(check_freshness 退出码+test) 全落地。Mac 复核：**全量 1074 passed**；tempfile/env 修复与 Mac 侧无冲突（freshness.py 仍 gettempdir） |
| WT-14 | 趋势打折口径核对（团队评审 S-4 副产品） | `without_trend`（`fg_system/backtest/attribution.py`）的前提是「`target_position` **已按 `TREND_FILTER_FACTOR` 打折**，故在 `trend_blocked` 处除以它即可还原」；但 Windows 端实测：全仓 `trend_factor_series` **只在 `pipeline.py:253/258` 用于造 trend 列**，**没有任何地方把它乘进 `target_position`**（`pipeline.py:86` 的 `core = core_position(idx_val)` 未乘系数）⇒ 生产调用方 `cli.py:338` 拿到的 `run_equity_v2()` 输出里**看不到趋势打折**。需确认：归因的「带趋势 vs 不带趋势」对比是否因此失去意义（若 `without_trend` 把从未打折的值又除一次，反而会**放大**仓位）。来源：团队评审 2026-10-12 §3 副产品（S-4 本体为误报，已撤回；此为其暴露出的独立问题） | 给出结论二选一：① **口径本就一致**（说明 `target_position` 在何处被打折）② **需修**（给出改点与影响面）⇒ 据此再开修复任务 | ✅ **裁决 B（口径不一致）**——Mac 2026-10-12 实证：`run_equity_v2()`=v1 `run()`+趋势列，v1 `target_position = legacy.core_position + ammo`（`legacy.py:99` **无 trend 乘法**）；真实数据 blocked 行 target/core 比值中位 1.198（0.864~2.093，含弹药），绝非 0.5 ⇒ **从未打折**；`without_trend` 在 blocked 行 ÷0.5 → 仓位翻倍（实测 0.5→1.0）⇒ 归因表与 verdict() 失真。**影响面**：`cli attribution` 的美股对照路径系统性放大 → 夸大趋势过滤贡献 → 影响「是否回退核心仓上限」判定。**建议改点**：`without_trend` 对 v1 数据（target 未打折）应**原样返回**（关闭趋势过滤的对照=无变化），blocked 行不做 ÷0.5；同时更新 4 个 test_attribution 语义。✅ **用户已确认实施**（2026-10-12）⇒ 由 WT-22 执行 |

| WT-15 | fg_system/models/ 补测试 | `fg_system/models/` 整包 4 文件零测试（hmm/markov/evt/bayes_update，均有生产用途）。补 `tests/test_models_*.py`：纯函数输入输出断言（模型可复现性、边界输入），mock 或构造小样本，**不依赖真实 Data/**。来源：团队评审 2026-10-12 §4 测试盲区 | 4 个测试文件存在；增量 pytest 全绿；每文件 ≥2 条有效断言 | 待做 |
| WT-16 | config 增加 validate() + 非法参数用例 | `fg_system/config.py` 目前**无任何参数校验**（权重/边界/系数可被改坏而静默运行）。新增 `validate()`：WEIGHTS 归一化≈1、ZONE_EDGES 递增且 0-100、饱和度 0-1、CORE_CAP/COMMISSION 正值等；非法时 `raise ValueError`（带字段名）。补 `tests/test_config_validate.py`（合法通过 + ≥5 类非法拒绝）。来源：团队评审 2026-10-12 §4 | validate() 存在；非法参数用例 ≥5 类全被拒且报错含字段名；合法配置通过；增量 pytest 绿 | 待做 |
| WT-17 | sensitivity_scan.py 补测试 | `scripts/sensitivity_scan.py`（251 行）零测试，是最接近触碰 OOS 红线（禁止调参）的入口。补 `tests/test_sensitivity_scan.py`：--help/参数解析、无数据路径退出 2、mock 扫描输出格式。来源：团队评审 2026-10-12 §4 | 测试文件存在；增量 pytest 绿；无数据路径实测退出 2 | 待做 |
| WT-18 | OOS 起点双轨统一 | 两套 OOS 起点并存：`config.py:217` `OOS_START=2023-01-01` vs 各回测脚本硬编码 2024-10-0x。统一为**单一常量**（统一读 config.OOS_START），加一致性测试断言无脚本再硬编码 2024-10 起点。来源：团队评审 2026-10-12 §3① | 统一后 grep 无 2024-10-0 硬编码残留；一致性测试存在且绿 | 待做 |
| WT-19 | pipeline.py 空/单元素窗口防御 | `fg_system/pipeline.py:967` 附近对 `us_features.index` 做 `index[-1]` / `tail[max(0,...)]` 切片，**空/单元素窗口会 IndexError 崩溃**（而非可解释失败）。加防御：窗口 <2 时明确报「数据窗口不足（路径/行数）」退出 2。补测试（空窗口/单元素/正常三态）。来源：团队评审 2026-10-12 §2 | 三态测试通过；空窗不再 traceback | 待做 |
| WT-20 | restore_from_base64.py 解压穿越校验 | `scripts/restore_from_base64.py:229` `tar.extractall(args.into)` **无路径穿越校验**（恶意 tar 可写任意路径）。改安全解压：遍历成员拒绝绝对路径/`..`/symlink 逃逸（复用 `fg_sync_ingest._safe_extract` 模式或独立实现）。补测试（正常包通过 + 恶意成员被拒）。来源：团队评审 2026-10-12 §2（安全） | 恶意成员被拒且报错；正常还原回归通过 | 待做 |
| WT-21 | risk.py HRP 递归二分校正 | `fg_system/risk.py:183-187` HRP：`fcluster(Z, len(idxs)-1, "maxclust")` 的簇标签与**实际聚类树最后合并点**可能错位（数值不可信）。改为从 `Z[len(idxs)-2]` 直接取二分索引（i,j），左右子树用 `fcluster` 在**该节点**上拆分（或 scipy `cut_tree` 取 2 簇），确保 left/right 与树结构一致。补测试：构造已知相关矩阵，断言二分结果与暴力分组一致。来源：团队评审 2026-10-12 §2 | 修复后与暴力分组一致；增量 pytest 绿 | 待做 |
| WT-22 | 实施 WT-14 修复（待用户确认后） | **前置**：用户确认 WT-14 裁决 B 的修复方案后执行。`without_trend` 对 v1 数据返回原样（blocked 行不做 ÷0.5），同步更新 `tests/test_attribution.py` 4 个用例语义（对照路径=原样）；重新跑 attribution 输出并回传，供 Mac 复核 verdict() 变化。来源：WT-14 裁决 B | 修复后 blocked 行不被放大；test_attribution 4 用例更新且绿；attribution 报告回传 | 待做（**前置已解除**：用户 2026-10-12 确认实施） |

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
