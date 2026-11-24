#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`prices.csv` vs `shoutu_history.csv` 的价格交叉校验 ✓（2026-11-24 用户要求）。

【为什么】
  两个源都记了同 6 个标的（CONL / GDXU / SOXL / TQQQ / UPRO / YINN）的日价格：
    · `Data/raw/prices.csv`        ← `fetch.update_prices()`（Nasdaq）
    · `Data/raw/shoutu_history.csv` ← 守猪待兔历史（第三方 API）
  ⇒ 若其中一个源出错，**所有下游分析都会被污染** ✗
  ⇒ 用同一 (date, symbol) 的价格对比，找出偏差 ✓

【做什么】
  ① 按 (date, symbol) 内连接，算相对偏差 `|close/price - 1|`
  ② 报：匹配对数、平均/中位/最大偏差、偏差 >1% 的样本（列出前 10 条）
  ③ 报两个源各自的日期覆盖差异（谁缺哪天）

⚠️ 守猪待兔的 `price` 可能是**盘中价**而非收盘价 ⇒ 小幅偏差属正常 ✓
   判据：**中位偏差 < 0.5%** 视为一致；**> 2%** 说明有一方错了 ✗

用法（Mac，经队列）：
    python scripts/price_crosscheck.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES = os.path.join(REPO, "Data", "raw", "prices.csv")
SHOUTU = os.path.join(REPO, "Data", "raw", "shoutu_history.csv")

SYMS = ["CONL", "GDXU", "SOXL", "TQQQ", "UPRO", "YINN"]


def main():
    for p in (PRICES, SHOUTU):
        if not os.path.exists(p):
            print("缺文件：%s" % p)
            return 1

    px = pd.read_csv(PRICES, parse_dates=["date"])
    sh = pd.read_csv(SHOUTU, parse_dates=["date"])

    px = px[px["symbol"].isin(SYMS)][["date", "symbol", "close"]]
    sh = sh[sh["symbol"].isin(SYMS)][["date", "symbol", "price"]]
    print("prices.csv：%d 行（%s → %s）"
          % (len(px), px["date"].min().date(), px["date"].max().date()))
    print("shoutu_history.csv：%d 行（%s → %s）"
          % (len(sh), sh["date"].min().date(), sh["date"].max().date()))

    m = px.merge(sh, on=["date", "symbol"], how="inner")
    print("\n同 (date, symbol) 匹配：%d 对" % len(m))
    if m.empty:
        print("没有任何交集 ⇒ 检查日期格式或标的代码")
        return 1

    m = m[(m["close"] > 0) & (m["price"] > 0)].copy()
    m["dev_pct"] = (m["close"] / m["price"] - 1.0).abs() * 100.0

    print("平均偏差 %.3f%% ｜ 中位 %.3f%% ｜ 最大 %.2f%%"
          % (m["dev_pct"].mean(), m["dev_pct"].median(), m["dev_pct"].max()))

    bad = m[m["dev_pct"] > 1.0].sort_values("dev_pct", ascending=False)
    print("\n偏差 > 1%% 的样本：%d 个（占 %.1f%%）"
          % (len(bad), len(bad) / len(m) * 100))
    for _, r in bad.head(10).iterrows():
        print("  %s %-5s prices=%.4f shoutu=%.4f 偏差 %.2f%%"
              % (r["date"].date(), r["symbol"], r["close"], r["price"],
                 r["dev_pct"]))

    # 逐标的汇总
    print("\n=== 逐标的 ===")
    g = m.groupby("symbol")["dev_pct"].agg(["count", "median", "max"])
    for sym, r in g.iterrows():
        print("  %-5s 匹配 %4d 天 ｜ 中位 %.3f%% ｜ 最大 %.2f%%"
              % (sym, int(r["count"]), r["median"], r["max"]))

    # 覆盖差异
    print("\n=== 日期覆盖差异（各自独有）===")
    dp, ds = set(px["date"]), set(sh["date"])
    print("  只有 prices 有：%d 天（%s）"
          % (len(dp - ds),
             ", ".join(str(d.date()) for d in sorted(dp - ds)[:5])))
    print("  只有 shoutu 有：%d 天（%s）"
          % (len(ds - dp),
             ", ".join(str(d.date()) for d in sorted(ds - dp)[:5])))

    med = float(m["dev_pct"].median())
    verdict = ("✅ 两源一致（中位偏差 %.3f%% < 0.5%%）" % med if med < 0.5 else
               "⚠️ 有系统性偏差（中位 %.3f%%）⇒ 可能口径不同（收盘 vs 盘中）" % med
               if med < 2.0 else
               "❌ 有一方数据错误（中位 %.3f%% > 2%%）" % med)
    print("\n结论：%s" % verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
