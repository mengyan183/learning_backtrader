#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-6 Put-Call 因子检验（E4 框架）：CBOE 官方每日 Put/Call 比率 vs SPY 次日收益。

口径（全部可指回文件）：
  - putcall.csv：CBOE Daily Market Statistics 官方页面逐日抓取（total/equity/index 比率）
  - prices.csv：SPY close（Data/raw/prices.csv，2016-09-26 起）
  - 次日收益 = 当日 close → 下一交易日 close
  - IC = 当日 total_ratio 与次日收益的 Spearman 秩相关；IR = mean(IC)/std(IC)
  - 事件研究：按 total_ratio 分位（5 档）统计次日收益均值
  - 检验样本：putcall 与 SPY 共同覆盖日（2026-10 起每日链增量追加）

用法：.venv/bin/python scripts/putcall_factor_check.py [--write]
"""
import argparse
import os

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "Data", "raw")


def load():
    pc = pd.read_csv(os.path.join(RAW, "putcall.csv"), parse_dates=["date"])
    prices = pd.read_csv(os.path.join(RAW, "prices.csv"), parse_dates=["date"])
    spy = prices[prices["symbol"] == "SPY"][["date", "close"]].sort_values("date")
    spy["ret"] = spy["close"].pct_change()
    spy["next_ret"] = spy["ret"].shift(-1)  # 当日收盘 → 次日收盘
    df = pc.merge(spy[["date", "next_ret"]], on="date", how="inner").dropna(subset=["total_ratio", "next_ret"])
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    df = load()
    if len(df) < 60:
        print("样本不足（%d 条），需 ≥60。回填未完成？" % len(df))
        return

    # IC / IR
    ic = df["total_ratio"].corr(df["next_ret"], method="spearman")
    ic_equity = df["equity_ratio"].corr(df["next_ret"], method="spearman")
    # 滚动 IC（60 日窗，显式 Spearman）→ IR
    from scipy.stats import spearmanr
    n = len(df)
    win = 60
    roll_ics = np.full(n, np.nan)
    for i in range(win - 1, n):
        a = df["total_ratio"].iloc[i - win + 1:i + 1]
        b = df["next_ret"].iloc[i - win + 1:i + 1]
        if a.nunique() > 1 and b.nunique() > 1:
            roll_ics[i] = spearmanr(a, b).correlation
    valid = roll_ics[~np.isnan(roll_ics)]
    ir = valid.mean() / valid.std() if len(valid) > 1 else float("nan")

    # 事件研究：total_ratio 5 分位 → 次日收益
    df["q"] = pd.qcut(df["total_ratio"], 5, labels=False)
    qtab = df.groupby("q")["next_ret"].agg(["mean", "count"])

    # 极端档：最高分位（put/call 高 = 恐慌）vs 最低分位
    fear = df[df["q"] == 4]["next_ret"].mean()
    greed = df[df["q"] == 0]["next_ret"].mean()

    lines = [
        "# Put-Call 因子检验（B-6，E4 框架）",
        "",
        "> 数据：Data/raw/putcall.csv（CBOE 官方页面，免 key）+ Data/raw/prices.csv SPY close；",
        "> 口径：当日 total_ratio → 次日 SPY 收益（close→close）；IC=Spearman；样本共同覆盖日。",
        "",
        "## 样本",
        "",
        "- 共同覆盖 %d 个交易日（%s → %s）" % (len(df), df["date"].min().date(), df["date"].max().date()),
        "",
        "## IC / IR（全样本）",
        "",
        "- total_ratio 与次日收益 IC = %.4f" % ic,
        "- equity_ratio 与次日收益 IC = %.4f" % ic_equity,
        "- 滚动 60 日 IC 均值 / 标准差 → IR = %.3f" % ir,
        "",
        "## 事件研究：total_ratio 五分位 → 次日 SPY 收益均值",
        "",
        "| 分位（put/call 从低到高） | 次日收益均值 | 样本 |",
        "|---|---|---|",
    ]
    for q in range(5):
        lines.append("| Q%d %s | %+.4f%% | %d |" % (
            q, "（恐慌）" if q == 4 else "（贪婪）" if q == 0 else "", qtab.loc[q, "mean"] * 100, qtab.loc[q, "count"]))
    lines += [
        "",
        "## 结论（仅研究参考，不直接执行）",
        "",
        "- 恐慌端（Q4）次日收益均值 %+.2f%%，贪婪端（Q0）%+.2f%%%s" % (
            fear * 100, greed * 100,
            " → 与 C-10 归因发现方向一致（恐惧→次日收益更高）" if fear > greed else " → 方向与 C-10 归因相反，需进一步观察"),
        "- 信号分级：🟡 研究参考（单因子检验，未经回测裁判，不进入合成权重）",
        "",
    ]
    report = "\n".join(lines)
    print(report)
    if args.write:
        with open(os.path.join(REPO, "evolution", "putcall-report.md"), "w", encoding="utf-8") as f:
            f.write(report)
        print("\n已写入 evolution/putcall-report.md")


if __name__ == "__main__":
    main()
