# 因子采纳通道（🟡 → 生产）：纪律化流程

> M2.2 落地 · 2026-10-11 · 打通「研究参考 → 生产权重」的完整通道。
> 原则（第 8 条纪律）：**先文档 → 再代码 → 再回测 → 人工审批 → 才动生产**；
> 评测通过 ≠ 可入生产，回测裁判才是真裁判。

## 0. 定位

本流程把「候选因子 → 评测 → 回测裁判 → C-3 审批 → 更新 WEIGHTS」写为可执行、
可复核的固定管道。任何因子从研究（🟡）升格为生产（🟢）必须走完本管道，
缺任何一环即退回 🟡。

## 1. 管道（每阶段产出物固定）

```text
候选因子（🟡，有数据基础）
  │
  ▼ ① 评测（R1.1 protocol，已落地）
scripts/factor_screen.py --factor <F-xxx>
  产出：IC/RankIC/ICIR + 分层多空 + 含成本双口径 → evolution/factor-screen-results.md
  门槛（factor-engine.md §4）：|ICIR|≥0.5 且 n≥60 且近窗无衰减 → 通过评测
  │
  ▼ ② 回测裁判（M2.2 probe，已落地）
scripts/factor_backtest_probe.py --factor <features列> --symbol <标的> --direction <正/逆>
  产出：OOS 单标的回测（含换仓成本）→ evolution/experiments/factor-adoption/*-oos.md
  判定：OOS 年化 > B0 买入持有 且 最大回撤不劣化 → PASS（可提案）
  │
  ▼ ③ C-3 提案（既有设施）
evolution/proposals/proposal_<F-xxx>_<date>.md
  模板：依据 / 口径 / 评测证据 / 回测证据 / 风险 / 审批位（## 6. 审批）
  │
  ▼ ④ C-3 人工审批（既有设施）
scripts/evolve_approve.py list | --approve <file> <Y|N|Z>
  Y=采纳（解除动 config 权限，实际改 WEIGHTS 仍须单独显式操作）
  N=否决（留档不采纳）  Z=观察（纳入 VARIANTS 长期观察）
  │
  ▼ ⑤ 更新 WEIGHTS（如 Y）
config.py WEIGHTS 变更 + 变更记录 + 季度 walk-forward 重检（C-5）
```

## 2. 工具与文件对照

| 环节 | 工具 | 产出 |
|---|---|---|
| ① 评测 | `scripts/factor_screen.py`（R1.1） | `evolution/factor-screen-results.md` |
| ② 回测裁判 | `scripts/factor_backtest_probe.py`（M2.2） | `evolution/experiments/factor-adoption/*-oos.{md,json}` |
| ③ 提案 | 手工按模板（C-2 同源） | `evolution/proposals/proposal_*.md` |
| ④ 审批 | `scripts/evolve_approve.py`（C-3） | 提案「## 6. 审批」+ `docs/decision-log.md` |
| ⑤ 落地 | config.py + 变更记录（C-6） | `docs/变更记录/*.md` |

## 3. 纪律红线

- **评测通过不是绿灯**：F-011 反例——IC/ICIR 全达标（RankICIR ~1.3），OOS 回测
  年化 27.96% < B0 49.39% → FAIL，不得入生产（详见 2026-10-11 F-011 提案）。
- **方向先验必须登记**：--direction 由模块 docstring/评测方向标签决定，不得事后改向。
- **无参数先验**：仓位映射（0.2~1.0 线性）、滚动窗口（756）均为文档化先验，非调参；
  任何参数改动视为新因子，重走全管道。
- **无前视**：T 信号 shift(1) → T+1 执行（R1.2 审计器强制）。
- **审批只解除权限**：Y 不直接改 config；改 WEIGHTS 是单独显式操作（C-3 红线）。

## 4. 当前状态

- 首个跑通案例：**F-011 Put-Call**（2026-10-11）——评测通过、回测 FAIL，
  提案 `evolution/proposals/proposal_F-011_2026-10-11.md` 待 C-3 审批（预期 Z 观察：
  因子与未来收益强相关、OOS 回撤改善显著，但年化未跑赢 B0，纳入长期观察更诚实）。
- 候补：H-030/H-031（稳定币背离）、news_sentiment（F-010 样本积累中）。
