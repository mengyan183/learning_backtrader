#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""算持仓候选标的的两两相关性 ✓（2026-11-24，第 4E 条 step ③ 的输入）。

【为什么】
  第 4E 条（假分散禁令）主张：2026-09-22 持有的 5 只杠杆 ETF + BTC
  「表面分散、实为同一赌注」✗ —— 但这是**定性推断**，需要用数据证实/证伪 ✓

【做什么】
  ① 读 `Data/raw/prices.csv`（Mac 上有 10 万行，无需同步到 Windows）
  ② 取日收益，算两个窗口的两两 Pearson 相关：
     · **全 2026 年**（平静期 + 加息后）
     · **2026-09-17 起**（加息落地后至今）← 这是「压力情景」口径
  ③ 打印矩阵（保留 2 位）+ 统计「有多少对 ρ ≥ 0.7」
  ⇒ ρ 高 ⇒ 「假分散」成立 ✓；ρ 低 ⇒ 我的判断过重，要撤回 ✗

用法（Mac，经队列）：
    python scripts/corr_matrix.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES = os.path.join(REPO, "Data", "raw", "prices.csv")

#: 关注标的（9-22 快照的 5 只 ETF + YINN + 基准）
WATCH = ["AXTX", "CONL", "CRCG", "GDXU", "YINN", "TQQQ", "SOXL", "UPRO",
         "SPY", "QQQ"]

RATE_HIKE = "2026-09-17"      # 加息落地日（fred_DFF 实测）


def _load():
    df = pd.read_csv(PRICES, parse_dates=["date"])
    px = df.pivot_table(index="date", columns="symbol", values="close",
                        aggfunc="last").sort_index()
    return px


def _corr(px, start=None, end=None, min_n=20):
    sub = px.loc[start:end] if (start or end) else px
    ret = sub.pct_change(fill_method=None).dropna(how="all")
    cols = [c for c in WATCH if c in ret.columns]
    ret = ret[cols].dropna()
    if len(ret) < min_n:
        return None, len(ret), cols
    return ret.corr(), len(ret), cols


def _report(title, corr, n, cols):
    print("\n=== %s（%d 个交易日）===" % (title, n))
    if corr is None:
        print("样本不足，跳过")
        return
    print("        " + " ".join("%6s" % c[:6] for c in cols))
    for a in cols:
        print("%-7s " % a[:7]
              + " ".join("%6.2f" % corr.loc[a, b] for b in cols))
    # 统计高相关对
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            pairs.append((corr.loc[a, b], a, b))
    pairs.sort(reverse=True)
    hi = [p for p in pairs if p[0] >= 0.7]
    print("ρ ≥ 0.7 的对数：%d / %d" % (len(hi), len(pairs)))
    for v, a, b in pairs[:5]:
        print("  最相关：%s~%s ρ=%.2f" % (a, b, v))
    avg = sum(p[0] for p in pairs) / len(pairs) if pairs else 0
    print("平均两两 ρ = %.2f" % avg)


def main():
    if not os.path.exists(PRICES):
        print("找不到 %s" % PRICES)
        return 1
    px = _load()
    print("prices.csv：%d 行 × %d 标的，%s → %s"
          % (len(px), len(px.columns),
             px.index.min().date(), px.index.max().date()))

    # ① 全 2026 年
    c, n, cols = _corr(px, "2026-01-01", None)
    _report("2026 全年", c, n, cols)

    # ② 加息后（压力情景口径）
    c2, n2, cols2 = _corr(px, RATE_HIKE, None)
    _report("加息后（%s 起）" % RATE_HIKE, c2, n2, cols2)

    # ③ 各标的区间收益
    print("\n=== 区间收益（%）===")
    for s in cols2 or []:
        try:
            a = px.loc[:"2026-01-01", s].dropna().iloc[-1]
            b = px[s].dropna().iloc[-1]
            print("  %-6s 2026 全年 %+7.1f%%" % (s, (b / a - 1) * 100))
        except (IndexError, KeyError):
            continue
    return 0


if __name__ == "__main__":
    sys.exit(main())
