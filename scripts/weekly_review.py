#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""周度复盘 ✓（2026-11-03 用户裁定要做）。

【做什么】
  回顾最近 N 个交易日的：
    ① 各持仓的**实际涨跌** ✓
    ② 系统当时给的**减仓建议**（从 `Data/briefs/archive/` 的简报里解析 ✗）
    ③ 对照：建议减仓的标的，之后涨了还是跌了 ⇒ 判断质量 ✓

【为什么从简报解析而不是从结构化数据】
  ⚠️ 诚实地讲：**结构化数据更可靠** ✗ 但「当时建议什么」只在简报里 ✗
     `positions.csv` 只有持仓 ✗ 没有「建议」✗
  ⇒ 只能解析文本 ✗ 解析失败时**明确跳过** ✓ 不编造 ✗

【解析目标】简报里的这一段：
    **ENE 减仓触发**（ratio=1.0；仅杠杆 ETF ✓...）：
    · GDXU 通道位置 **0.00 超卖** ⇒ 均值回归视角可持有 ✓
    · AXTX 通道位置 **0.85 超买** ⇒ 建议减至 **15%** 仓位
    **减仓顺序**（浮亏深度×杠杆倍数...）：AXTX（-82%×2x） > GDXU（-40%×3x） ...
  以及逐标的行：
    · AXTX 市值779/上限215 | ... → 减仓至上限215

用法：
  .venv/bin/python scripts/weekly_review.py            # 最近 7 天
  .venv/bin/python scripts/weekly_review.py --days 14
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

DATA = REPO / "Data"
ARCHIVE = DATA / "briefs" / "archive"

#: 从简报里抓「减仓至上限 XXX」的标的 ✓
RE_CAP = re.compile(r"·\s*([A-Z]{2,6})\s*市值[\d.]+/上限([\d.]+)")
#: 抓「XXX 通道位置 **0.85 超买** ⇒ 建议减至 **15%** 仓位」
RE_ENE = re.compile(r"·\s*([A-Z]{2,6})\s*通道位置\s*\*\*([\d.]+)\s*超买\*\*"
                    r"\s*⇒\s*建议减至\s*\*\*(\d+)%")
#: 文件名里的日期
RE_DATE = re.compile(r"invest_brief_(\d{4}-\d{2}-\d{2})\.md$")


def _briefs(days):
    """最近 `days` 天内的简报文件 ✓（含 archive 与工作区根目录）。"""
    files = []
    for d in (ARCHIVE, DATA):
        for p in d.rglob("invest_brief_*.md"):
            m = RE_DATE.match(p.name)
            if m:
                files.append((m.group(1), p))
    files.sort(reverse=True)
    return files[:days]


def _parse(p):
    """解析一份简报 ⇒ `{symbol: {"cap": 上限, "ene": 建议仓位%}}` ✓。"""
    try:
        txt = p.read_text(encoding="utf-8")
    except Exception:                       # noqa: BLE001 —— 读不到就跳过 ✓
        return {}
    out = {}
    for sym, cap in RE_CAP.findall(txt):
        out.setdefault(sym, {})["cap"] = float(cap)
    for sym, pos, tgt in RE_ENE.findall(txt):
        out.setdefault(sym, {})["ene"] = float(tgt)
        out[sym]["ene_pos"] = float(pos)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="回顾最近 N 份简报")
    args = ap.parse_args(argv)

    prices = pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])

    def close(sym):
        s = (prices[prices["symbol"] == sym].set_index("date")["close"]
             .astype(float))
        return s[~s.index.duplicated(keep="last")].sort_index()

    briefs = _briefs(args.days)
    if not briefs:
        print("✗ 找不到简报（Data/briefs/archive/ 或 Data/ 下无 invest_brief_*.md）")
        return 2

    print("# 周度复盘（最近 %d 份简报：%s ~ %s）\n"
          % (len(briefs), briefs[-1][0], briefs[0][0]))

    rows = []
    for date_s, p in briefs:
        sig = _parse(p)
        if not sig:
            print("· %s —— 解析不到建议（跳过 ✗）" % date_s)
            continue
        d0 = pd.Timestamp(date_s)
        for sym, s in sorted(sig.items()):
            c = close(sym)
            if c.empty:
                continue
            after = c[c.index > d0]
            if after.empty:
                continue
            # 之后 5 个交易日 / 到最新的涨幅 ✓
            r5 = (after.iloc[min(4, len(after) - 1)] / after.iloc[0] - 1.0) * 100
            advice = []
            if "ene" in s:
                advice.append("ENE 减至%.0f%%" % s["ene"])
            if "cap" in s:
                advice.append("减至上限%.0f" % s["cap"])
            rows.append({
                "date": date_s, "sym": sym, "advice": " / ".join(advice),
                "r5": r5,
                # 「减仓」建议 ⇒ 之后**跌**才算对 ✓
                "hit": r5 < 0,
            })

    if not rows:
        print("\n✗ 没有可对照的记录 —— 简报里解析不到「减仓」建议 ✗")
        print("  （可能是最近几天没有触发 ✗ 或简报格式变了 ✗）")
        return 0

    print("\n## 建议 vs 实际（减仓建议 ⇒ 之后跌 = 对 ✓）\n")
    print("| 日期 | 标的 | 建议 | 之后 5 日 | 判断 |")
    print("|---|---|---|---|---|")
    for r in rows:
        print("| %s | %s | %s | %+.2f%% | %s |"
              % (r["date"], r["sym"], r["advice"], r["r5"],
                 "✓ 对" if r["hit"] else "✗ 错"))

    n = len(rows)
    hit = sum(1 for r in rows if r["hit"])
    print("\n## 汇总\n")
    print("| 项 | 值 |")
    print("|---|---|")
    print("| 建议条数 | %d |" % n)
    print("| 判断正确 | %d（%.0f%%）|" % (hit, 100.0 * hit / n))
    print("| 平均「之后 5 日」 | %+.2f%% |" % (sum(r["r5"] for r in rows) / n))
    print("\n⚠️ **样本很小** ✗ —— 一周的建议条数通常 < 20 ✗")
    print("   ⇒ 单周胜率**不能**当因子有效性证据 ✗ 要看**连续 8-12 周**趋势 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
