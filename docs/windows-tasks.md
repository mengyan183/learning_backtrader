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
| WT-04 | 新假说验证脚本骨架（H-030/H-031/H-033） | 仿 `scripts/evolve_h001.py` 模式：为 H-030（量价-资金背离）/ H-031（利率敏感度）/ H-033（币股收益-BTC 分层）各写验证脚本（或一个 `evolve_verify_new.py` 统一骨架）：数据路径用 config 常量（不硬编码绝对路径）、样本不足时输出"等待样本积累（n/阈值）"并退出 0、状态机 open→verifying→adopted/falsified 注释齐全。来源：evolution/hypotheses.md H-030/H-031/H-033（2026-10-09 登记） | 脚本文件存在、`--help` 可运行、dry-run 输出"等待样本积累"退出 0；不依赖 Mac 本地运行数据（不 read_csv 绝对路径） | 待做 |
| WT-05 | verify_hypotheses.py 扩展（修订口径批量验证） | 现有 `scripts/verify_hypotheses.py` 只支持 H-005/H-007 式分箱；扩展为支持修订后 15 条假说的新口径（zone / fg_index / trend_blocked_us / trend_blocked_crypto，数据源 features.csv + portfolio_features.csv，均走 config 路径）：按 H-024/025/027/029/032 的修订版验证方法（触发率≥50% 判据）实现通用验证函数 + 结果写 evolution/hypothesis_results.md 追加段。来源：B-4/WT-01 修订后待验证假说 | 代码扩展完成、`--help` 列出支持假说、dry-run 在无数据时明确报"数据缺失（路径）"而非崩溃；实际验证运行由 Mac 执行 | 待做 |
| WT-06 | B-10 稳定币数据源 fetch 脚本 | 为 H-034「使用效率 = 链上月交易量/USDC 流通量」开发数据接入脚本 `scripts/fetch_stablecoin_usage.py`：数据源方案先行（候选：DefiLlama 稳定币 API / Artemis / CoinGecko 稳定币市场数据，脚本内注释写明端点与字段）；输出 Data/raw/stablecoin_usage.csv（date, symbol, monthly_volume, circulation, usage_efficiency）；脚本参数化 URL/key（key 走环境变量或 Data 内 gitignore 文件）。注意：公司电脑可能无公网，脚本写好即可，**实际拉取验证在 Mac 执行**。来源：blocked-registry B-10（H-034） | 脚本存在、--help 可运行、无 key/无网络时明确报错并退出 2（可解释失败）；CSV 输出列结构符合登记 | 待做 |

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
