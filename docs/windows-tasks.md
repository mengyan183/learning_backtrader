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
| WT-01 | H-024/H-025/H-027/H-029/H-032 口径修订 | 2026-10-10 口径审计挂起 pending-revise：这 5 条引用虚构列/位置引用（position_multiplier、「第 4/5/6/7 列」）→ 按真实列重措辞（与 B-4 同处置：zone/core_position/fg_index/trend_blocked_us/trend_blocked_crypto，证据区间用真实数据）。来源：evolution/hypotheses.md（状态列 open（pending-revise）） | 5 条假说措辞改完、状态改为 open（修订口径）、提交 hypotheses.md；说明修订依据 | 待做 |
| WT-02 | C-3 增强：提案飞书推送 | evolve_approve.py 目前只有 --list/--status/--log，缺「新提案自动推飞书」；补 feishu_send 对接（复用 scripts/feishu_send.py 或内置发送）。来源：blocked-registry C-3 备注「飞书推送对接可后续做」 | evolve_approve.py 支持 --push：未审批提案推飞书，已在库中测试通过（增量 pytest 绿） | 待做 |
| WT-03 | B-8 极端规则校准脚本预写 | 85 熔断 / 10 极恐线参数校准：写 scripts/calibrate_extreme.py（实盘快照积累后跑，输出证据表；红线：OOS 禁直接调参，脚本只测量不改 config.py）。来源：blocked-registry B-8 | 脚本产出校准证据表（快照不足时输出"样本不足"并退出 0），不动 config | 待做 |

## 默认动作（不占编号）

- 全量 pytest 回归（~900 用例）：每次开发收尾必跑，Mac 只跑增量 --quick。
- 本清单为空时：以 docs/NEXT-SESSION.md / docs/blocked-registry.md 为准自查，或等 Mac 下发新任务。

---

## 已完成（留痕）

| 编号 | 任务 | 完成依据 | 完成日期 |
|---|---|---|---|
| （空） | | | |
