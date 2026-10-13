# 未来函数审计报告（R1.2 · freqtrade lookahead 思想）

- 生成：2026-10-13 11:20 · scripts/lookahead_audit.py
- 口径：代码层扫描 `shift(-n)`/`shift(0)`（默认违规、白名单豁免）；数据层 features 尾行不得超前原料 raw（pipeline shift(1) 设计，同日/滞后正常）
- 结论：**PASS（违规 0）**

## 一、代码层

| 类别 | 文件:行 | 代码 |
|---|---|---|
| 🟡 白名单 | `fg_system/factors/eval.py:22` | `out[f"fwd_{h}"] = close.shift(-h) / close - 1.0` |
| 🟡 白名单 | `fg_system/factors/screening.py:25` | `return close.shift(-horizon) / close - 1.0` |
| 🟡 白名单 | `scripts/attribution_check.py:56` | `df["ret_next"] = df["close"].shift(-1) / df["close"] - 1` |
| 🟡 白名单 | `scripts/factor_screen_extend.py:206` | `fut = spy.shift(-h) / spy - 1.0` |
| 🟡 白名单 | `scripts/norm_compare.py:135` | `fwd = df["ret"].shift(-1)` |
| 🟡 白名单 | `scripts/putcall_factor_check.py:30` | `spy["next_ret"] = spy["ret"].shift(-1)  # 当日收盘 → 次日收盘` |
| 🟡 白名单 | `scripts/verify_hypotheses.py:486` | `- 「后续 H 日收益」= close.shift(-H)/close - 1（事件日起 H 个交易日后）。` |
| 🟡 白名单 | `scripts/verify_hypotheses.py:545` | `fwd = close.shift(-h) / close - 1.0            # H 日前瞻收益` |
| 🟡 白名单 | `scripts/verify_hypotheses.py:581` | `"4/8/16 日收益（close.shift(-H)/close-1）vs 全样本基线，各 horizon "` |

## 二、数据层

- features 尾行：2026-10-12
- raw/vix.csv 尾行：2026-10-12
- raw/sentiment.csv 尾行：2026-10-12
- raw/prices.csv 尾行：2026-10-12

- features 超前原料：**否 ✓**

---
> 由 scripts/lookahead_audit.py 生成 · 只读审计，不修改任何代码/数据；
> 新增评测脚本须登记 RESEARCH_WHITELIST（默认违规、白名单豁免）。