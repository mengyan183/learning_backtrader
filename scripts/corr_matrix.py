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


def _corr_pairwise(px, start=None, end=None, min_n=20):
    """**逐对**算相关性 ✓ —— 不做 complete-case 丢弃。

    🔴 2026-11-24 实测：原实现 `ret[cols].dropna()` 要求 10 只**同时**有值 ✗
       2026 全年应有 ~230 个交易日，只剩 **110 个**（覆盖率 48%）✗
       加息后窗口只剩 **10 个** ⇒ 直接判「样本不足」跳过 ✗
       ⇒ 改成**每对各自取交集**，样本量按对记录 ✓
    """
    sub = px.loc[start:end] if (start or end) else px
    ret = sub.pct_change(fill_method=None)
    cols = [c for c in WATCH if c in ret.columns]
    mat = pd.DataFrame(index=cols, columns=cols, dtype=float)
    ns = pd.DataFrame(index=cols, columns=cols, dtype=int)
    for i, a in enumerate(cols):
        for b in cols[i:]:
            # 🔴 2026-11-24 实测：`a == b` 时 `ret[[a, b]]` 是**重复列** ✗
            #   ⇒ `s[a]` 返回 DataFrame 而非 Series ⇒ `.corr()` 返回 DataFrame
            #   ⇒ `mat.loc[a, b] = <DataFrame>` 抛
            #   "Cannot set a DataFrame with multiple columns to the single column" ✗
            #   ⇒ 对角线单独处理 ✓
            if a == b:
                mat.loc[a, a] = 1.0
                ns.loc[a, a] = int(ret[a].notna().sum())
                continue
            s = ret[[a, b]].dropna()
            k = len(s)
            ns.loc[a, b] = ns.loc[b, a] = k
            v = s[a].corr(s[b]) if k >= min_n else float("nan")
            mat.loc[a, b] = mat.loc[b, a] = v
    return mat, ns, cols


def _report(title, corr, ns, cols):
    print("\n=== %s ===" % title)
    nmin, nmax = int(ns.values.min()), int(ns.values.max())
    print("每对样本：%d ~ %d 个交易日（pairwise，不再丢弃整行）" % (nmin, nmax))
    print("        " + " ".join("%6s" % c[:6] for c in cols))
    for a in cols:
        print("%-7s " % a[:7] + " ".join(
            "   n/a" if pd.isna(corr.loc[a, b]) else "%6.2f" % corr.loc[a, b]
            for b in cols))
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            v = corr.loc[a, b]
            if not pd.isna(v):
                pairs.append((float(v), a, b))
    pairs.sort(reverse=True)
    hi = [p for p in pairs if p[0] >= 0.7]
    print("ρ ≥ 0.7 的对数：%d / %d（有效对）" % (len(hi), len(pairs)))
    for v, a, b in pairs[:5]:
        print("  最相关：%s~%s ρ=%.2f" % (a, b, v))
    if pairs:
        print("平均两两 ρ = %.2f" % (sum(p[0] for p in pairs) / len(pairs)))


def main():
    if not os.path.exists(PRICES):
        print("找不到 %s" % PRICES)
        return 1
    px = _load()
    print("prices.csv：%d 行 × %d 标的，%s → %s"
          % (len(px), len(px.columns),
             px.index.min().date(), px.index.max().date()))

    # ① 全 2026 年
    c, ns, cols = _corr_pairwise(px, "2026-01-01", None)
    _report("2026 全年", c, ns, cols)

    # ② 加息后（压力情景口径）
    c2, ns2, cols2 = _corr_pairwise(px, RATE_HIKE, None)
    _report("加息后（%s 起）" % RATE_HIKE, c2, ns2, cols2)

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
