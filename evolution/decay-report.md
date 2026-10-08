# 因子/假说绩效衰减降级报告（C-11，2026-10-08）

> 由 scripts/evolve_decay.py 生成 · 确定性判据（无 LLM 判决）；
> 判据：近窗衰减 horizon >= 2/4 → decayed；样本不足 → accumulating；否则维持。

## 因子（factors.md F 行）

| 编号 | 原状态 | 判定 | 说明 |
|---|---|---|---|
| F-001 | draft | **draft** | 近窗衰减 1/4 horizon（5），维持观察 |
| F-002 | draft | **draft** | 无近窗衰减标记，维持 |
| F-003 | draft | **draft** | 近窗衰减 1/4 horizon（5/10），维持观察 |
| F-004 | draft | **draft** | 近窗衰减 1/4 horizon（40），维持观察 |
| F-005 | draft | **draft** | 近窗衰减 1/4 horizon（20），维持观察 |
| F-006 | draft | **draft** | 近窗衰减 1/4 horizon（20），维持观察 |
| F-007 | draft | **accumulating** | 样本不足，数据积累中 |
| F-008 | draft | **draft** | 无近窗衰减标记，维持 |
| F-009 | draft | **accumulating** | 样本不足，数据积累中 |

## 假说（hypotheses.md H 行，状态监控）

| 编号 | 状态 | 监控判定 |
|---|---|---|
| H-001 | verifying | 数据积累监控中（观察点/快照不足，随数据自然推进） |
| H-002 | adopted | 回测/实证型假说：衰减判定走 C-5 季度 walk-forward 重检（本脚本仅登记监控） |
| H-003 | adopted | 回测/实证型假说：衰减判定走 C-5 季度 walk-forward 重检（本脚本仅登记监控） |
| H-004 | adopted | 回测/实证型假说：衰减判定走 C-5 季度 walk-forward 重检（本脚本仅登记监控） |
| H-005 | rejected | 终态，无需监控 |
| H-006 | verifying | 数据积累监控中（观察点/快照不足，随数据自然推进） |
| H-007 | adopted | 回测/实证型假说：衰减判定走 C-5 季度 walk-forward 重检（本脚本仅登记监控） |
| H-008 | verifying | 数据积累监控中（观察点/快照不足，随数据自然推进） |
| H-009 | verifying | 数据积累监控中（观察点/快照不足，随数据自然推进） |
| H-010 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-011 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-012 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-013 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-014 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-015 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-016 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-017 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-018 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-019 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-020 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-021 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
| H-022 | open | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |
