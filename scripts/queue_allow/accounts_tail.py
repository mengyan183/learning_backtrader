# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/accounts_tail.py` ✓。

为什么放行（2026-11-20）：简报的连亏保护显示 `-1072.79 (-18.3%)`，
而同一份简报里股票净值差只有 `-326.1` ⇒ 怀疑
`acc_latest["day_pnl"].dropna().iloc[-1]` 取错了行 ✗
需要远程确认「最新日期下的行序」才能定论 ✓

⚠️ 只读 `Data/accounts.csv`，且**只输出 4 列**
（`date / account / net_value / day_pnl`）✗ —— 不吐 `securities_mv`
/ `cash` 等明细 ⇒ 比放开 `READ_ALLOW` 更窄 ✓
"""
