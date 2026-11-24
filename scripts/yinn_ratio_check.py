#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 YINN 的 3.3% 系统性偏差是「分红/拆股」还是「常数缩放」✓，
并回传 `shoutu_history.csv` 的真实样本量 ✓（2026-11-24 用户要求）。

【背景】
  `price_crosscheck.py` 实测：YINN 中位偏差 **3.342%**、范围 3.3~5.6%（很窄）
  ⇒ 不是日期错位（那会忽大忽小），而是**稳定比例差**
  ⇒ 两种可能：
     ① **分红复权口径不同** ⇒ 比值呈**阶梯状**（每次除息跳一下）
     ② **常数缩放**（某个源用了不同乘数）⇒ 比值**平直**

【做什么】
  ① 打印 `shoutu_history.csv` 的行数 / 日期范围 / 逐标的条数
  ② 按**月**算 `prices.close / shoutu.price` 的中位数，看它是否阶梯
  ③ 找「月间比值跳变 > 0.5%」的位置 ⇒ 那就是除息/拆股日
  ④ 同样看 GDXU（它有 20.4% 的离群点），判断是日期错位还是真实波动

用法（Mac，经队列）：
    python scripts/yinn_ratio_check.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES = os.path.join(REPO, "Data", "raw", "prices.csv")
SHOUTU = os.path.join(REPO, "Data", "raw", "shoutu_history.csv")


def _stats(sh):
    print("=== shoutu_history.csv 样本量 ===")
    print("总行数 %d ｜ 标的 %d 个 ｜ 交易日 %d 天"
          % (len(sh), sh["symbol"].nunique(), sh["date"].nunique()))
    print("日期范围 %s → %s"
          % (sh["date"].min().date(), sh["date"].max().date()))
    g = sh.groupby("symbol")["date"].agg(["min", "max", "count"])
    for sym, r in g.sort_values("count", ascending=False).iterrows():
        print("  %-5s %4d 条 ｜ %s → %s"
              % (sym, int(r["count"]), r["min"].date(), r["max"].date()))


def _ratio(px, sh, sym):
    p = px[px["symbol"] == sym][["date", "close"]]
    s = sh[sh["symbol"] == sym][["date", "price"]]
    m = p.merge(s, on="date").dropna()
    m = m[(m["close"] > 0) & (m["price"] > 0)].copy()
    if m.empty:
        print("\n%s：没有交集" % sym)
        return
    m["ratio"] = m["close"] / m["price"]
    m["ym"] = m["date"].dt.to_period("M")

    print("\n=== %s 比值（prices.close / shoutu.price）===" % sym)
    print("全样本：中位 %.4f ｜ 均值 %.4f ｜ 标准差 %.4f ｜ 极差 %.4f"
          % (m["ratio"].median(), m["ratio"].mean(),
             m["ratio"].std(), m["ratio"].max() - m["ratio"].min()))

    bym = m.groupby("ym")["ratio"].median()
    print("\n按月中位数（只列变化处）：")
    prev = None
    steps = 0
    for ym, v in bym.items():
        if prev is None or abs(v - prev) / prev > 0.005:
            print("  %s  %.4f%s"
                  % (ym, v, "" if prev is None else "  ← 跳 %+.2f%%"
                     % ((v / prev - 1) * 100)))
            if prev is not None:
                steps += 1
        prev = v
    print("\n月间跳变 > 0.5%% 的次数：%d" % steps)
    if steps == 0:
        print("⇒ **常数缩放**（无阶梯）⇒ 不是分红/拆股，是乘数不同 ✗")
    elif steps <= 6:
        print("⇒ **阶梯状**（%d 次跳变）⇒ 符合分红/拆股复权差异 ✓" % steps)
    else:
        print("⇒ 跳变太多（%d 次）⇒ 更像两源各自采集时点不同 ✗" % steps)

    # 最大的单日偏离，看是不是日期错位
    m["dev"] = (m["ratio"] / m["ratio"].median() - 1).abs()
    worst = m.sort_values("dev", ascending=False).head(5)
    print("\n偏离中位比值最远的 5 天（可能是日期错位）：")
    for _, r in worst.iterrows():
        print("  %s  prices=%.4f shoutu=%.4f 比值 %.4f（中位 %.4f）"
              % (r["date"].date(), r["close"], r["price"],
                 r["ratio"], m["ratio"].median()))


def main():
    for p in (PRICES, SHOUTU):
        if not os.path.exists(p):
            print("缺文件：%s" % p)
            return 1
    px = pd.read_csv(PRICES, parse_dates=["date"])
    sh = pd.read_csv(SHOUTU, parse_dates=["date"])

    _stats(sh)
    _ratio(px, sh, "YINN")
    _ratio(px, sh, "GDXU")
    return 0


if __name__ == "__main__":
    sys.exit(main())
