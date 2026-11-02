#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选因子的**数据积累进度** ✓（2026-11-02）。

🔴 为什么需要：F-010 / F-013 / F-019 三条都卡在「样本不够」✗
   而「够没够」靠人记日期很容易忘 ✗
   ⇒ 跑一次就能看到「还差几天、大约哪天能测」✓

用法：
  .venv/bin/python scripts/factor_data_gap.py
"""
import sys
from pathlib import Path

import pandas as pd

# ⚠️ Windows 控制台默认 GBK ✗ —— 输出 `✓`/`✗`/`−` 会 `UnicodeEncodeError` ✗
# ⇒ 强制 UTF-8 + replace ✓（Mac 上无影响 ✓）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parent.parent

#: (因子编号, 说明, 数据文件, 日期列, 需要多少行, 为什么)
NEEDS = [
    ("F-010", "新闻情绪（mkt_score）", "news_sentiment.csv", "date", 60,
     "评测门槛 n≥60"),
    ("F-013", "稳定币使用效率（usage_30d）", "stablecoin_usage.csv", "date", 756,
     "756 日滚动分位窗"),
    # ⚠️ 描述里不能用 `−`（U+2212）✗ —— Windows 控制台 GBK 编码不了 ✗
    ("F-019", "稳定币广度（mcap 分位 - usage 分位）", "stablecoin_usage.csv",
     "date", 730, "2 年样本（评测可信度下限）"),
]


def main(argv=None):
    print("# 候选因子数据积累进度（%s）\n"
          % pd.Timestamp.today().date())
    print("| 编号 | 因子 | 现有行数 | 需要 | 还差 | 预计可测 | 状态 |")
    print("|---|---|---|---|---|---|---|")
    for fid, desc, fname, col, need, why in NEEDS:
        p = REPO / "Data" / "raw" / fname
        if not p.exists():
            print("| %s | %s | **缺文件** | %d | — | — | ✗ 无数据 |"
                  % (fid, desc, need))
            continue
        d = pd.read_csv(p, parse_dates=[col])
        n = len(d)
        gap = need - n
        if gap <= 0:
            eta, status = "—", "**可测 ✓**"
        else:
            last = d[col].max()
            eta = str((last + pd.Timedelta(days=gap)).date())
            status = "积累中（%s）" % why
        print("| %s | %s | %d | %d | %s | %s | %s |"
              % (fid, desc, n, need,
                 "**0 ✓**" if gap <= 0 else "%d 天" % gap, eta, status))
    print("\n注：预计日期按「数据尾行 + 缺口天数」算，**假设每天 +1 行** ✓")
    print("    若采集断了，实际日期会后移 ✗ —— 用 `drift_monitor` 可查断流 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
