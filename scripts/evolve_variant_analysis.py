#!/usr/bin/env python3
"""MT-08 补充分析：B2 判据应用 + B3 重叠率表 + gap 情景（5×SLIPPAGE）。

可复算入口：.venv/bin/python scripts/evolve_variant_analysis.py
输出：把结论追加到 evolution/experiments/variant_h007_<date>.md（--report 指定）。

内容：
1. B2（V-PVOL）预登记判据应用：
   判据 = 「OOS 年化相对 B0 下降 ≥5pp 且回撤改善 < 2×年化下降 ⇒ 默认不采纳」。
2. B3（V-DDC）重叠率表：
   强触发日（组合回撤因子 ≤0.5，即组合回撤 ≥10%）与趋势阻断日（trend_blocked_us）
   的重叠率 = 交集日数 / 趋势阻断日数（全样本 + OOS）。
3. B3 gap 情景：5×SLIPPAGE 下 V-DDC 的 OOS 年化/回撤（与 1× 对比）。
"""
import argparse
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fg_system import config
from fg_system.backtest import variants as vmod
from fg_system.backtest import runner
from fg_system import evo_meta
from scripts.evolve_variant import build_basket_returns, metrics  # 复用编排层

OOS_START = evo_meta.oos_start()
DEFAULT_REPORT = os.path.join(
    "evolution", "experiments", "variant_h007_%s.md" % date.today().isoformat())


def dd_strong_days(pf, dd_floor=0.20):
    """V-DDC 因子 ≤0.5（组合回撤 ≥10%）的强触发日（date index）。"""
    if "date" in pf.columns:
        pf = pf.set_index("date")
    br = pf["basket_ret"]
    nav = (1.0 + br).cumprod()
    dd = nav / nav.cummax() - 1.0            # ≤0
    factor = np.clip(1.0 + dd / dd_floor, 0.0, 1.0)
    strong = factor <= 0.5
    return strong


def overlap_table(pf):
    """B3 重叠率表：V-DDC 强触发日 ∩ 趋势阻断日 / 趋势阻断日。"""
    if "date" in pf.columns:
        pf = pf.set_index("date")
    strong = dd_strong_days(pf)
    blocked = pf["trend_blocked_us"].fillna(False).astype(bool)
    rows = []
    for label, m in (("全样本", slice(None)),
                     ("OOS", pf.index >= pd.Timestamp(OOS_START))):
        s, b = strong.loc[m], blocked.loc[m]
        inter = int((s & b).sum())
        n_blocked = int(b.sum())
        n_strong = int(s.sum())
        ov = inter / n_blocked if n_blocked else float("nan")
        rows.append((label, n_strong, n_blocked, inter, ov))
    return rows


def run_gap_ddc(sym, prices, features, pf, slip_mult=5.0):
    """5×SLIPPAGE 下重跑 V-DDC：OOS 年化/回撤。"""
    old = config.SLIPPAGE
    config.SLIPPAGE = old * slip_mult
    try:
        feat = features.copy()
        px = prices[prices["symbol"] == sym].set_index("date")[
            ["open", "high", "low", "close", "volume"]]
        feat = feat.join(px, how="inner")
        fv = vmod.apply_variant(feat, pf, "V-DDC")
        _, ret = runner.run_single(fv, sym)
    finally:
        config.SLIPPAGE = old
    if ret is None or len(ret) == 0:
        return None
    oos = ret[ret.index >= pd.Timestamp(OOS_START)]
    m = metrics(oos)
    return m["annual_return"], m["max_drawdown"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", default=DEFAULT_REPORT)
    ap.add_argument("--append", action="store_true",
                    help="把结论追加到报告（默认只打印）")
    args = ap.parse_args()

    features = (pd.read_csv(config.FEATURES_PATH, parse_dates=["date"])
                .set_index("date"))
    prices = pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"),
                         parse_dates=["date"])
    pf = pd.read_csv(config.PORTFOLIO_FEATURES_PATH, parse_dates=["date"])
    basket_ret = build_basket_returns(prices)
    if "date" in pf.columns:
        pf = pf.set_index("date")
    pf["basket_ret"] = basket_ret.reindex(pf.index)

    # 1) B2 判据应用（复用主实验报告数据，避免重算口径漂移）
    lines = []
    lines.append("")
    lines.append("## B2/B3 结论层（MT-08 补充，2026-10-13）")
    lines.append("")
    lines.append("### B2（V-PVOL）预登记判据应用")
    lines.append("判据：**OOS 年化相对 B0 下降 ≥5pp 且回撤改善 < 2×年化下降 ⇒ 默认不采纳**。")
    lines.append("")
    lines.append("| 标的 | OOS 年化下降(pp) | OOS 回撤改善(pp) | 2×下降 | 判据判定 |")
    lines.append("|---|---|---|---|---|")
    # 从主实验报告解析 V-PVOL 行：| sym | V-PVOL | b0_ann | v_ann | b0_dd | v_dd | 否 |
    vpvol_rows = {}
    if os.path.exists(args.report):
        with open(args.report, encoding="utf-8") as fh:
            for line in fh:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 8 and parts[2] == "V-PVOL":
                    try:
                        b0_ann = float(parts[3].rstrip("%")) / 100
                        v_ann = float(parts[4].rstrip("%")) / 100
                        b0_dd = float(parts[5].rstrip("%")) / 100
                        v_dd = float(parts[6].rstrip("%")) / 100
                    except ValueError:
                        continue
                    vpvol_rows[parts[1]] = (b0_ann, v_ann, b0_dd, v_dd)
    for sym in config.SYMBOLS:
        if sym not in vpvol_rows:
            continue
        b0_ann, v_ann, b0_dd, v_dd = vpvol_rows[sym]
        d_ann = (b0_ann - v_ann) * 100
        r_dd = (v_dd - b0_dd) * 100          # 回撤改善（负→正）
        reject = d_ann >= 5 and r_dd < 2 * d_ann
        lines.append("| %s | %.2f | %.2f | %.2f | %s |"
                     % (sym, d_ann, r_dd, 2 * d_ann,
                        "默认不采纳" if reject else "待人工权衡"))

    # 2) B3 重叠率表
    lines.append("")
    lines.append("### B3（V-DDC）强触发日 vs 趋势阻断日重叠率")
    lines.append("强触发日 = 组合回撤因子 ≤0.5（组合回撤 ≥10%）；"
                 "趋势阻断日 = `trend_blocked_us=True`。")
    lines.append("")
    lines.append("| 区间 | 强触发日数 | 趋势阻断日数 | 交集日数 | 重叠率 |")
    lines.append("|---|---|---|---|---|")
    for label, n_strong, n_blocked, inter, ov in overlap_table(pf):
        lines.append("| %s | %d | %d | %d | %.1f%% |"
                     % (label, n_strong, n_blocked, inter, ov * 100))

    # 3) B3 gap 情景（5×SLIPPAGE）
    lines.append("")
    lines.append("### B3（V-DDC）gap 情景：5×SLIPPAGE 敏感性")
    lines.append("")
    lines.append("| 标的 | 1×SLIPPAGE OOS 年化 | 1×回撤 | 5×SLIPPAGE OOS 年化 | 5×回撤 | 年化差(pp) |")
    lines.append("|---|---|---|---|---|---|")
    for sym in config.SYMBOLS:
        feat = features.copy()
        px = prices[prices["symbol"] == sym].set_index("date")[
            ["open", "high", "low", "close", "volume"]]
        feat = feat.join(px, how="inner")
        fv = vmod.apply_variant(feat, pf, "V-DDC")
        _, ret = runner.run_single(fv, sym)
        oos = ret[ret.index >= pd.Timestamp(OOS_START)]
        m1 = metrics(oos)
        g = run_gap_ddc(sym, prices, features, pf)
        lines.append("| %s | %.2f%% | %.1f%% | %.2f%% | %.1f%% | %.2f |"
                     % (sym, m1["annual_return"] * 100,
                        m1["max_drawdown"] * 100,
                        g[0] * 100, g[1] * 100,
                        (g[0] - m1["annual_return"]) * 100))

    text = "\n".join(lines)
    print(text)
    if args.append:
        with open(args.report, "a", encoding="utf-8") as fh:
            fh.write("\n" + text + "\n")
        print("已追加到 %s" % args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
