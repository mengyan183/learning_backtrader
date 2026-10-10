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

> 当前无待做项（2026-10-10 已清空）。Windows 端默认动作：全量 pytest 回归；或等 Mac 下发新任务。

（空）

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
