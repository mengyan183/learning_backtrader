# -*- coding: utf-8 -*-
"""诊断：`accounts.csv` 的尾部 + **最新日期下的行序**（只读 4 列）。

为什么单独写这个脚本，而不是把 `Data/accounts.csv` 加进 `READ_ALLOW`：
  `read_tail` 会把整行原样吐出来（含 `securities_mv` / `cash` 等），
  而这个脚本**只输出** `date / account / net_value / day_pnl` 四列 ✓
  ⇒ 暴露面比放开白名单更窄 ✓

动机（2026-11-20 实测）✗：
  简报的连亏保护显示 `当日亏损 -1072.79 (-18.3%)`，而同一份简报里
  股票净值从 6202.5 掉到 5876.4 ⇒ 净值差只有 **-326.1** ✗
  两者差 746 ⇒ 怀疑 `acc_latest["day_pnl"].dropna().iloc[-1]`
  **取到了错误的行**（跨账户或跨日期）✗
  ⇒ 本脚本把「最新日期下 iloc 顺序」直接打出来 ✓

用法：
    python scripts/accounts_tail.py          # 默认尾部 8 行
    python scripts/accounts_tail.py -n 20
"""
import argparse
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLS = ("date", "account", "net_value", "day_pnl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=8, help="尾部行数（默认 8）")
    args = ap.parse_args()

    path = os.path.join(ROOT, "Data", "accounts.csv")
    if not os.path.exists(path):
        print("accounts.csv 不存在：%s" % path)
        return 1
    d = pd.read_csv(path)
    keep = [c for c in COLS if c in d.columns]
    print("文件 %s" % path)
    print("总行数 %d · 全部列 %s" % (len(d), list(d.columns)))
    print("\n--- 尾部 %d 行（只列 %s）---" % (args.n, keep))
    print(d.tail(args.n)[keep].to_string(index=False))

    last = d["date"].max()
    sub = d[d["date"] == last].reset_index(drop=True)
    print("\n--- 最新日期 %s 的行序（决定 .iloc[-1] 取到谁）---" % last)
    for i, r in sub.iterrows():
        print("  iloc[%d]  account=%-8s net_value=%-10s day_pnl=%s"
              % (i, r.get("account"), r.get("net_value"), r.get("day_pnl")))
    if len(sub):
        tail_row = sub.iloc[-1]
        print("\n⇒ `.iloc[-1]` 取到：account=%s  day_pnl=%s"
              % (tail_row.get("account"), tail_row.get("day_pnl")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
