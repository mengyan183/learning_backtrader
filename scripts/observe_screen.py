#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-9 个股指数扩池-策略侧：OBSERVE_SYMBOLS 观察池扫描。

背景：观察池 6 只（NVDL/TSLL/FNGU/FAS/TNA/SQQQ）数据侧已入库（task #23），
策略侧此前因 `SIGNAL_UNDERLYING_MAP` 缺底层映射而指数不可算（回退市场级）。
2026-10-08 补齐：NVDL→NVDA、TSLL→TSLA、FAS→XLF、TNA→IWM（Nasdaq 补抓），
FNGU→QQQ（近似底层，已声明）、SQQQ→QQQ（反向，指数=纳指情绪）。

本脚本对观察池逐只计算系统个股指数 → 档位 → 参考动作，输出当日观察表。
**白名单未动**：观察池不参与生产仓位，仅研究观察。

参考动作口径（与 dashboard 持仓卡一致，见 report.py）：
  ≤40 恐惧区 → 买入 / 40-60 中性 → 观望 / ≥60 贪婪区 → 卖出。
SQQQ 为反向标的：指数表达**纳指情绪**，动作反向（纳指贪婪时 SQQQ 偏空），
不给买卖建议，仅标注观察。

用法：.venv/bin/python scripts/observe_screen.py [--out Data/observe_screen_YYYY-MM-DD.md]
"""
import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fg_system import config
from fg_system.factors import symbol as smod

ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]
ZONE_BOUNDS = [20, 40, 60, 80]
REVERSE = {"SQQQ"}   # 反向标的（做空纳指），指数=纳指情绪


def screen(symbols=None):
    prices = pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"),
                         parse_dates=["date"])
    symbols = symbols or config.OBSERVE_SYMBOLS
    rows = []
    for s in symbols:
        idx = smod.symbol_fg_index(s, prices=prices)
        if idx is None or idx.dropna().empty:
            rows.append({"symbol": s, "index": None, "zone": None,
                         "n": 0, "action": "数据不足，不可算"})
            continue
        v = float(idx.dropna().iloc[-1])
        n = int(idx.dropna().shape[0])
        z = int(np.clip(np.searchsorted(ZONE_BOUNDS, v, side="right"), 0, 4))
        if s in REVERSE:
            action = ("反向标的：指数=纳指情绪（纳指贪婪时 SQQQ 偏空），"
                      "仅供参考，不给出买卖建议")
        elif z <= 1:
            action = "买入区（恐惧）"
        elif z >= 3:
            action = "卖出区（贪婪）"
        else:
            action = "观望（中性）"
        rows.append({"symbol": s, "index": v, "zone": ZONE_NAMES[z],
                     "n": n, "action": action})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description="C-9 观察池扫描")
    ap.add_argument("--out", default=os.path.join(
        config.DATA_DIR, "observe_screen_%s.md" % datetime.now().strftime("%Y-%m-%d")))
    args = ap.parse_args()

    df = screen()
    for _, r in df.iterrows():
        idx = ("%.1f" % r["index"]) if r["index"] is not None else "—"
        zn = r["zone"] if r["zone"] else "—"
        print("  %-5s 指数 %5s  档位 %-5s  %s" % (r["symbol"], idx, zn, r["action"]))

    lines = [
        "# 观察池扫描（C-9 策略侧）",
        "",
        "生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "数据源：Data/raw/prices.csv（观察池底层映射见 config.SIGNAL_UNDERLYING_MAP）",
        "口径：系统个股指数 symbol_fg_index（无杠杆底层动量+波动率，滚动分位）；",
        "参考动作 ≤40 恐惧→买入 / 40-60 中性→观望 / ≥60 贪婪→卖出；SQQQ 反向仅观察。",
        "**白名单未动**：观察池不参与生产仓位。",
        "",
        "| 标的 | 系统指数 | 档位 | 样本 | 参考动作 |",
        "|---|---|---|---|---|",
    ]
    for _, r in df.iterrows():
        idx = ("%.1f" % r["index"]) if r["index"] is not None else "—"
        zn = r["zone"] if r["zone"] else "—"
        lines.append("| %s | %s | %s | %d | %s |"
                     % (r["symbol"], idx, zn, r["n"], r["action"]))
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n✅ 已写入 %s" % args.out)


if __name__ == "__main__":
    main()
