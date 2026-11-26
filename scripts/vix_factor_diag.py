#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VIX 因子诊断：为什么 `score 6.2` 标成「极度恐惧」（2026-11-26）。

【矛盾】
  简报：`VIX 6.2 极度恐惧〔11-24〕`
  而 VIX 因子 = `1 - (0.7×水平分位 + 0.3×5日变化分位)`（`factors/vix.py`）
  ⇒ score 6.2 ⇒ composite 0.938 ⇒ **VIX 应在 93.8% 分位**
  但实际 VIX ≈ 15~20（历史中低位）⇒ 不可能在 93.8% 分位 ✗
  且市场快讯说「道指反弹、抹去 1100 点跌幅」⇒ 恐慌在缓解，不该更恐惧 ✗

【本脚本查什么】
  ① `vix.csv` 最后 10 天的**原始 VIX 值**
  ② `features.csv` 最后几行的 **vix 列**（因子分数）
  ③ 手算一遍 `rolling_pct`，看 composite 是不是 0.938
  ④ 若 ② 与 ③ 不符 ⇒ 因子实现与数据不一致（代码/数据错位）
"""
from __future__ import annotations

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fg_system import config  # noqa: E402
from fg_system.factors.base import rolling_pct  # noqa: E402


def main():
    # ① 原始 VIX
    vp = os.path.join(ROOT, "Data", "raw", "vix.csv")
    if os.path.exists(vp):
        v = pd.read_csv(vp, parse_dates=["date"]).sort_values("date")
        col = "close" if "close" in v.columns else v.columns[-1]
        print("=== ① vix.csv 最后 10 行（列=%s，共 %d 行）===" % (col, len(v)))
        print(v.tail(10)[["date", col]].to_string(index=False))
        print("  最新值 %.2f ｜ 全历史 min/max = %.2f / %.2f"
              % (v[col].iloc[-1], v[col].min(), v[col].max()))
    else:
        print("=== ① vix.csv 不存在 ===")
        v = None

    # ② features.csv 的 vix 列
    fp = os.path.join(ROOT, "Data", "features.csv")
    if os.path.exists(fp):
        f = pd.read_csv(fp, parse_dates=["date"]).sort_values("date")
        cols = [c for c in f.columns if "vix" in c.lower()]
        print("\n=== ② features.csv 最后 6 行（vix 相关列: %s）===" % cols)
        print(f.tail(6)[["date"] + cols].to_string(index=False))
    else:
        print("\n=== ② features.csv 不存在 ===")
        f = None

    # ③ 手算
    if v is not None:
        s = v.set_index("date")[col]
        chg5 = s.pct_change(5)
        lv = rolling_pct(s, config.RANK_WINDOW)
        cp = rolling_pct(chg5, config.RANK_WINDOW)
        comp = 0.7 * lv + 0.3 * cp
        score = (1.0 - comp) * 100
        print("\n=== ③ 手算（窗口 %d）===" % config.RANK_WINDOW)
        for i in range(-5, 0):
            d = s.index[i]
            print("  %s  VIX=%7.2f  水平分位=%.3f  变化分位=%.3f  "
                  "composite=%.3f  score=%6.2f"
                  % (d.date(), s.iloc[i], lv.iloc[i], cp.iloc[i],
                     comp.iloc[i], score.iloc[i]))

    print("\n判读：")
    print("  · ③ 的 score 与 ② 的 vix 列接近 ⇒ 因子实现正常，问题在**档位标签**")
    print("  · ③ 与 ② 差很多 ⇒ `features.csv` 的 vix 列不是这个公式算的（口径变了）")
    print("  · ③ 里水平分位接近 1.0 但 VIX 只有 15 ⇒ `vix.csv` 混入了别的价格序列")
    return 0


if __name__ == "__main__":
    sys.exit(main())
