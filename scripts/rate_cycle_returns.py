#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""各标的在**历史加息 / 降息周期**中的表现 ✓（2026-11-24 用户要求）。

【为什么】
  用户复盘 2026 年下半年持仓亏损，提出「加息周期不该持有这类标的」✓
  但这是**单一样本**的推断 ✗ ⇒ 需要看历史上多个周期的分布 ✓

【做什么】
  ① 从 `Data/raw/fred_DFF.csv` 用 zigzag 拐点法识别主要周期（阈值 1pp）✓
  ② 取 `Data/raw/prices.csv` 里各标的在**每个周期内**的收益 ✓
  ③ 按方向汇总：加息期的平均/中位收益 vs 降息期 ✓
  ⚠️ 行情只有 2016-09 起 ⇒ 只能配对 **2016 年后**的 4~5 个周期 ✗

用法（Mac，经队列）：
    python scripts/rate_cycle_returns.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DFF = os.path.join(REPO, "Data", "raw", "fred_DFF.csv")
PRICES = os.path.join(REPO, "Data", "raw", "prices.csv")

SYMS = ["SPY", "QQQ", "TQQQ", "SOXL", "UPRO", "YINN", "GDXU", "CONL", "CRCG", "AXTX"]
TH = 1.0


def _cycles():
    """zigzag 识别主要利率周期 ⇒ [(起, 止, 是否加息)] ✓。"""
    d = pd.read_csv(DFF)
    d.columns = ["date", "v"][: len(d.columns)]
    d["date"] = pd.to_datetime(d["date"])
    s = (d.dropna().sort_values("date").set_index("date")["v"]
         .resample("ME").last().dropna().rolling(3, min_periods=1).median())
    i0, v0 = s.index[0], float(s.iloc[0])
    piv, direction, (ext_i, ext_v) = [], 0, (i0, v0)
    for dt, v in s.items():
        v = float(v)
        if direction == 0:
            if v - v0 >= TH:
                piv.append((i0, v0)); direction, ext_i, ext_v = 1, dt, v
            elif v0 - v >= TH:
                piv.append((i0, v0)); direction, ext_i, ext_v = -1, dt, v
            continue
        if direction == 1:
            if v > ext_v:
                ext_i, ext_v = dt, v
            elif ext_v - v >= TH:
                piv.append((ext_i, ext_v)); direction, ext_i, ext_v = -1, dt, v
        else:
            if v < ext_v:
                ext_i, ext_v = dt, v
            elif v - ext_v >= TH:
                piv.append((ext_i, ext_v)); direction, ext_i, ext_v = 1, dt, v
    piv.append((ext_i, ext_v))
    out = []
    for (a, v0_), (b, v1) in zip(piv, piv[1:]):
        if abs(v1 - v0_) >= TH:
            out.append((a, b, v1 > v0_, v0_, v1))
    return out


def main():
    px = pd.read_csv(PRICES, parse_dates=["date"])
    wide = px.pivot_table(index="date", columns="symbol", values="close",
                          aggfunc="last").sort_index()
    cols = [c for c in SYMS if c in wide.columns]
    print("行情：%s → %s（%d 个标的）"
          % (wide.index.min().date(), wide.index.max().date(), len(cols)))

    rows = []
    for a, b, up, v0, v1 in _cycles():
        if b < wide.index.min() or a > wide.index.max():
            continue
        seg = wide.loc[a:b]
        if len(seg) < 10:
            continue
        r = {"起": a.date(), "止": b.date(), "方向": "加息" if up else "降息",
             "幅度pp": round(v1 - v0, 2)}
        for c in cols:
            x = seg[c].dropna()
            r[c] = None if len(x) < 2 else round((x.iloc[-1] / x.iloc[0] - 1) * 100, 1)
        rows.append(r)

    if not rows:
        print("没有可配对的周期（行情区间太短）")
        return 1

    print("\n=== 各周期内收益（%）===")
    hdr = "%-11s %-11s %-4s %6s " % ("起", "止", "方向", "幅度")
    print(hdr + " ".join("%6s" % c[:6] for c in cols))
    for r in rows:
        line = "%-11s %-11s %-4s %+6.2f " % (r["起"], r["止"], r["方向"], r["幅度pp"])
        line += " ".join("%6s" % ("  n/a" if r[c] is None else "%+.1f" % r[c]) for c in cols)
        print(line)

    # 按方向汇总
    print("\n=== 按方向汇总（平均收益 %）===")
    for flag, name in ((True, "加息期"), (False, "降息期")):
        sub = [r for r in rows if (r["方向"] == "加息") == flag]
        if not sub:
            continue
        print("%s（%d 个样本）" % (name, len(sub)))
        for c in cols:
            vals = [r[c] for r in sub if r[c] is not None]
            if vals:
                print("  %-6s 均值 %+6.1f%% ｜ 各期 %s"
                      % (c, sum(vals) / len(vals),
                         " / ".join("%+.1f" % v for v in vals)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
