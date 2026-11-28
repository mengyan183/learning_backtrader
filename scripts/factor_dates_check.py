#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""六因子**源文件日期 vs features 主数据日**（2026-11-28）。

【要回答的问题】
  简报显示：
    VIX 6.2(T-1)〔11-26〕 · TERM 1.1(T-1) · PRICE 6.6 · BREADTH 42.6 ·
    FED 23.0 · PUT-CALL 18.2 极度恐惧〔11-25〕
  而 features 数据日是 **11-27** ✗
  ⇒ VIX/TERM 落后 1 天、PUT-CALL 落后 2 天 ✗
  问题：是「源数据没到」还是「抓取没跑」？

【本脚本打印】
  ① 每个源文件的**最后日期** + 距今几个交易日
  ② features.csv 最后 6 行里，各因子列的**是否 NaN**（NaN ⇒ 回退；有值 ⇒ forward fill）
  ③ 若某源落后，打印它的最后 3 条原始记录（看是不是真的停更）
"""
from __future__ import annotations

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "Data")
sys.path.insert(0, ROOT)
from fg_system import trading_days as td          # noqa: E402

SOURCES = [
    ("vix", "raw/vix_history.csv", "date"),
    ("term", "raw/vix3m.csv", "date"),
    ("putcall", "raw/putcall_daily_latest.csv", "date"),
    ("breadth", "raw/prices.csv", "date"),
    ("fed", "raw/fedwatch.csv", "date"),
    ("price", "raw/prices.csv", "date"),
]
FEAT_COLS = ("vix", "term", "price", "breadth", "fed", "putcall")


def main():
    fp = os.path.join(DATA, "features.csv")
    feat = pd.read_csv(fp)
    main_date = str(feat["date"].max())[:10]
    print("=== features.csv 主数据日：%s（共 %d 行）===" % (main_date, len(feat)))

    print("\n=== ① 源文件最后日期 ===")
    for name, rel, col in SOURCES:
        p = os.path.join(DATA, rel)
        if not os.path.exists(p):
            print("  %-9s ❌ 文件不存在（%s）" % (name, rel))
            continue
        try:
            d = pd.read_csv(p, usecols=[col])
            last = str(pd.to_datetime(d[col], errors="coerce").max())[:10]
        except Exception as e:                  # noqa: BLE001
            print("  %-9s ❌ 读失败 %s" % (name, type(e).__name__))
            continue
        lag = td.session_lag(last, main_date)
        mark = "✅" if lag == 0 else ("⚠️ T-%d" % lag)
        print("  %-9s 最后 %s  %s  （%s）" % (name, last, mark, rel))

    print("\n=== ② features 最后 6 行各因子列是否 NaN ===")
    tail = feat.tail(6)
    print("  %-12s %s" % ("date", " ".join("%-8s" % c for c in FEAT_COLS)))
    for _, r in tail.iterrows():
        cells = []
        for c in FEAT_COLS:
            v = r.get(c)
            cells.append("%-8s" % ("NaN" if pd.isna(v) else "%.1f" % float(v)))
        print("  %-12s %s" % (str(r["date"])[:10], " ".join(cells)))
    print("  ⇒ NaN = 当天缺失（简报会回退并标 T-n）；有值 = forward fill（旧值）")

    print("\n=== ③ 落后源的原始尾部 3 条 ===")
    for name, rel, col in SOURCES:
        p = os.path.join(DATA, rel)
        if not os.path.exists(p):
            continue
        try:
            d = pd.read_csv(p)
            d[col] = pd.to_datetime(d[col], errors="coerce")
            last = str(d[col].max())[:10]
            if td.session_lag(last, main_date) == 0:
                continue
            print("  --- %s（最后 %s）---" % (name, last))
            print(d.tail(3).to_string(index=False)[:400])
        except Exception:                       # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
