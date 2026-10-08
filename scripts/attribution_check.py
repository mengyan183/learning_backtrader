#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-10 实盘-回测归因校验：信号方向 vs 实际收益（预测-实际对齐）。

两种口径（合并在一份报告里）：
  1. **回测归因**：对 TQQQ/SOXL/UPRO，用 features.csv 的当日 zone（0 极恐/1 恐/2 中性/
     3 贪婪/4 极贪）→ 对齐 prices 的**次日**收益（信号 T+1 生效口径）；
     统计各档位组的次日收益均值/中位数/正收益占比/样本数。
     「方向一致率」= 贪婪档（≥2）次日收益 >0 的占比 与 恐惧档（≤1）次日收益 <0 的占比。
  2. **实盘归因**：positions.csv 最新快照浮盈 vs 守猪待兔当日系数（同样给出
     「恐慌日买入的持仓至今浮盈」对照），如实标注快照日期。

结论只报现象与统计，不替用户下判断；数字可指回 features/prices/positions 文件。

用法：.venv/bin/python scripts/attribution_check.py [--write]
输出：evolution/attribution-report.md
"""
import argparse
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system.config import shoutu_lines

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "Data")
OUT = os.path.join(REPO, "evolution", "attribution-report.md")

SYMS = ["TQQQ", "SOXL", "UPRO"]


def main():
    ap = argparse.ArgumentParser(description="C-10 归因校验")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    feats = pd.read_csv(os.path.join(DATA, "features.csv"), parse_dates=["date"])
    feats = feats.dropna(subset=["zone"]).set_index("date")
    prices = pd.read_csv(os.path.join(DATA, "raw", "prices.csv"), parse_dates=["date"])

    date_s = dt.datetime.now().strftime("%Y-%m-%d")
    lines = ["# 实盘-回测归因校验报告（C-10，%s）" % date_s, "",
             "> 由 scripts/attribution_check.py 生成 · 只统计，不判决；数字可指回 features.csv / prices.csv / positions.csv",
             "", "## 1. 回测归因（信号 → 次日收益）", "",
             "口径：features 当日 zone（0/1 恐惧类、2 中性、3/4 贪婪类）→ prices 次日收益；",
             "方向一致率 = 贪婪档次日收益>0 占比（看多方向）与恐惧档次日收益<0 占比（看空方向）。",
             "", "| 标的 | 档位组 | 样本 | 次日收益均值 | 中位数 | 正收益占比 | 方向一致率 |",
             "|---|---|---|---|---|---|---|"]
    for sym in SYMS:
        px = prices[prices["symbol"] == sym].set_index("date")["close"]
        df = feats.join(px.rename("close"), how="inner")
        df["ret_next"] = df["close"].shift(-1) / df["close"] - 1
        df = df.dropna(subset=["ret_next"])
        for grp, mask in [("恐惧(0/1)", df["zone"] <= 1),
                          ("中性(2)", df["zone"] == 2),
                          ("贪婪(3/4)", df["zone"] >= 3)]:
            sub = df[mask]
            if len(sub) < 10:
                lines.append("| %s | %s | %d | — | — | — | 样本不足 |" % (sym, grp, len(sub)))
                continue
            pos = (sub["ret_next"] > 0).mean()
            if "恐惧" in grp:
                agree = (sub["ret_next"] < 0).mean()
            elif "贪婪" in grp:
                agree = pos
            else:
                agree = np.nan
            lines.append("| %s | %s | %d | %+.2f%% | %+.2f%% | %.0f%% | %s |"
                         % (sym, grp, len(sub), sub["ret_next"].mean() * 100,
                            sub["ret_next"].median() * 100, pos * 100,
                            ("%.0f%%" % (agree * 100)) if not np.isnan(agree) else "—"))

    lines += ["", "## 2. 实盘归因（持仓快照浮盈 vs 守猪待兔系数）", "",
              "> positions.csv 最新快照日期：2026-10-08（如实标注，不假装今日行情）。", "",
              "| 标的 | 守猪待兔系数 | 档位 | 参考动作 | 浮盈 | 归因注记 |", "|---|---|---|---|---|---|"]
    pos = pd.read_csv(os.path.join(DATA, "positions.csv"), parse_dates=["date"])
    pos = pos.sort_values("date").groupby("symbol").tail(1)
    st = pd.read_csv(os.path.join(DATA, "raw", "shoutu_fng.csv"), parse_dates=["date"])
    for _, r in pos.iterrows():
        sym = r["symbol"]
        sub = st[st["symbol"] == sym].sort_values("date")
        if sub.empty:
            lines.append("| %s | — | — | — | %+.1f%% | 守猪待兔无该标的，无法归因 |"
                         % (sym, (r["price"] - r["cost"]) / r["cost"] * 100))
            continue
        v = float(sub.iloc[-1]["value"])
        buy, sell = shoutu_lines(sym)
        if v <= buy:
            action = "买入区"
        elif v >= sell:
            action = "卖出区"
        else:
            action = "观望"
        lines.append("| %s | %+.0f | %s | %s | %+.1f%% | 当日系数与快照同日，浮盈为该快照口径 |"
                     % (sym, v, "恐慌" if v <= -60 else ("贪婪" if v >= 60 else "中性"),
                        action, (r["price"] - r["cost"]) / r["cost"] * 100))

    lines += ["", "## 3. 使用说明",
              "- 方向一致率只衡量「信号方向与次日实际方向」的吻合度，不构成买卖建议；",
              "- 实盘归因受快照频率限制（仅交易日快照），长期连续归因需接入富途实时行情（已落地 futu_realtime）。"]
    report = "\n".join(lines) + "\n"
    print(report)
    if args.write:
        open(OUT, "w", encoding="utf-8").write(report)
        print("\n✅ 报告 → %s" % OUT)


if __name__ == "__main__":
    main()
