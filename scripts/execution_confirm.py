#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-6 E3 执行确认流：持仓 → 目标仓位确认清单 → 人工审批 → 可执行指令。

流程：
  1. 读 Data/positions.csv 最新快照（每 symbol 最新行）：
       qty / price / cost / market_value / bucket；
  2. 读 Data/raw/shoutu_fng.csv 各 symbol 最新 value（守猪待兔系数）+
     config.shoutu_lines(sym) 个性化买卖线 → 参考动作：
         系数 <= buy_line  → 买入区（加仓参考）
         系数 >= sell_line → 卖出区（减仓参考）
         其余              → 观望
  3. 计算浮盈 (price-cost)/cost；
  4. 生成执行确认清单 execution/confirm-YYYY-MM-DD.md：
       每行 symbol | 守猪待兔系数 | 档位 | 参考动作 | 现价/成本 | 浮盈 | 确认位(Y/N)；
  5. 人工确认后，`--finalize` 输出「可执行指令」（方向 + 数量 = qty 或目标减仓比例），
     供用户到券商/交易所执行。本脚本**永不直接下单**。

红线：只读数据、只生成确认清单与指令文本；不写 config.py、不触碰交易 API。

用法：
  .venv/bin/python scripts/execution_confirm.py               # 生成确认清单
  .venv/bin/python scripts/execution_confirm.py --finalize    # 生成可执行指令
"""
import argparse
import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "execution")

ZONE_TEXT = {0: "极度恐惧", 1: "恐惧", 2: "中性", 3: "贪婪", 4: "极度贪婪"}


def zone_of(v):
    for z, (lo, hi) in enumerate(zip([-100, -60, 0, 60], [-60, 0, 60, 100])):
        if lo <= v < hi:
            return z
    return 4 if v >= 100 else 0


def latest_positions():
    df = pd.read_csv(os.path.join(REPO, "Data", "positions.csv"))
    df = df.sort_values("date")
    return df.groupby("symbol").tail(1).set_index("symbol")


def latest_shoutu(sym):
    path = os.path.join(REPO, "Data", "raw", "shoutu_fng.csv")
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        return None, None
    sub = df[df["symbol"] == sym].sort_values("date")
    if sub.empty:
        return None, None
    last = sub.iloc[-1]
    return float(last["value"]), str(last["date"])


def build_rows():
    pos = latest_positions()
    rows = []
    for sym, r in pos.iterrows():
        v, vdate = latest_shoutu(sym)
        if v is None:
            rows.append({"sym": sym, "v": None, "zone": None, "action": "数据缺失(守猪待兔无该标的)",
                         "price": r["price"], "cost": r["cost"],
                         "qty": r["qty"], "pnl": (r["price"] - r["cost"]) / r["cost"],
                         "market_value": r["market_value"]})
            continue
        buy, sell = config.shoutu_lines(sym)
        if v <= buy:
            action = "买入区(加仓参考)"
        elif v >= sell:
            action = "卖出区(减仓参考)"
        else:
            action = "观望"
        rows.append({"sym": sym, "v": v, "zone": ZONE_TEXT[zone_of(v)], "action": action,
                     "price": r["price"], "cost": r["cost"], "qty": r["qty"],
                     "pnl": (r["price"] - r["cost"]) / r["cost"],
                     "market_value": r["market_value"]})
    return rows


def write_confirm():
    os.makedirs(OUT_DIR, exist_ok=True)
    date_s = dt.datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(OUT_DIR, "confirm-%s.md" % date_s)
    lines = ["# 执行确认清单（C-6，%s）" % date_s, "",
             "> 由 scripts/execution_confirm.py 生成 · 只读数据，不自动下单",
             "> 动作口径：守猪待兔系数 ≤ 个性化买入线 → 买入区；≥ 卖出线 → 卖出区；其余观望（config.shoutu_lines）",
             "", "| 标的 | 守猪待兔 | 档位 | 参考动作 | 现价 | 成本 | 浮盈 | 确认(Y/N) |",
             "|---|---|---|---|---|---|---|---|"]
    for r in build_rows():
        v_txt = "%+.0f" % r["v"] if r["v"] is not None else "—"
        lines.append("| %s | %s | %s | %s | %.2f | %.2f | %+.1f%% | |"
                     % (r["sym"], v_txt, r["zone"] or "—", r["action"],
                        r["price"], r["cost"], r["pnl"] * 100))
    lines += ["", "## 使用方式",
              "- 人工逐行审批后把 Y/N 填入确认列；",
              "- 运行 `--finalize` 生成可执行指令（仅输出文本，不自动交易）。"]
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("✅ 确认清单 → %s" % path)


def write_instructions():
    date_s = dt.datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(OUT_DIR, "instructions-%s.md" % date_s)
    lines = ["# 可执行指令（C-6，%s）" % date_s, "",
             "> 由 scripts/execution_confirm.py --finalize 生成；仅供人工到券商/交易所执行，系统不自动下单", "",
             "| 标的 | 方向 | 数量 | 参考价 | 说明 |", "|---|---|---|---|---|"]
    for r in build_rows():
        if r["v"] is None:
            continue
        if "买入区" in r["action"]:
            direction = "买入(加仓参考)"
            note = "守猪待兔 %+.0f ≤ 买入线；加仓前确认系统个股系数与仓位上限" % r["v"]
        elif "卖出区" in r["action"]:
            direction = "卖出(减仓参考)"
            note = "守猪待兔 %+.0f ≥ 卖出线；减仓量按简报减仓引擎与仓位目标" % r["v"]
        else:
            continue
        lines.append("| %s | %s | —(待确认数量) | %.2f | %s |" % (r["sym"], direction, r["price"], note))
    lines += ["", "> 数量留空：由人工在券商端按仓位目标填写；系统只提供方向与参考价。"]
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("✅ 可执行指令 → %s" % path)


def main():
    ap = argparse.ArgumentParser(description="C-6 执行确认流")
    ap.add_argument("--finalize", action="store_true", help="生成可执行指令")
    args = ap.parse_args()
    if args.finalize:
        write_instructions()
    else:
        write_confirm()


if __name__ == "__main__":
    main()
