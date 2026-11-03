#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F-021 黄金相对强度（`GDX/GLD`）评测 ✓（2026-11-03）。

【为什么要先测方向】
  「金矿股跑赢金价」后续会怎样，两种理论**相反** ✗：
    - 动量说：跑赢继续跑赢（经营杠杆正反馈）⇒ 正向
    - 回归说：跑赢是透支（成本终会上升）⇒ 逆向
  ⇒ 本脚本用实测 IC 符号**定方向** ✓ 不预设 ✗

【目标标的三档】
  ① `SPY`  —— 看它是否是大盘层面的信号 ✓
  ② `GDX`  —— 看它是否预测金矿股本身 ✓（最直接）
  ③ `GDXU` —— 用户实际持仓（3 倍金矿 ✗ 但样本只到 2020-12 ✗）

用法：
  .venv/bin/python scripts/eval_gold_ratio.py
  .venv/bin/python scripts/eval_gold_ratio.py --json evolution/gold-ratio-eval.json
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

from fg_system.factors import gold_ratio as fgr    # noqa: E402
from fg_system.factors import protocol as fproto   # noqa: E402
from fg_system.factors import report as frep      # noqa: E402

DATA = REPO / "Data"
HORIZONS = frep.HORIZONS_DAILY
WINDOW = frep.WINDOW
TARGETS = ("GDX", "GDXU", "SPY")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH", help="把结果写到 JSON")
    ap.add_argument("--window", type=int, default=fgr.GOLD_RATIO_WINDOW,
                    help="比值分位窗（默认 %d 日）" % fgr.GOLD_RATIO_WINDOW)
    args = ap.parse_args(argv)

    prices = frep.load_prices(DATA)
    ratio = fgr.gold_ratio(prices)
    if ratio.empty:
        print("✗ 无 GDX/GLD 数据 —— 检查 prices.csv")
        return 2
    sig_all = fgr.gold_ratio_pct(prices, window=args.window).dropna()
    if sig_all.empty:
        print("✗ 分位窗 %d 太大，无有效信号" % args.window)
        return 2

    print("# F-021 黄金相对强度（GDX/GLD）评测")
    print("比值 %d 天：%s → %s"
          % (len(ratio), ratio.index[0].date(), ratio.index[-1].date()))
    print("分位窗 %d 日 ⇒ 有效信号 %d 天：%s → %s"
          % (args.window, len(sig_all),
             sig_all.index[0].date(), sig_all.index[-1].date()))
    print("比值范围 %.3f ~ %.3f（最新 %.3f）\n"
          % (ratio.min(), ratio.max(), ratio.iloc[-1]))

    out = {"window": args.window,
           "ratio_start": str(ratio.index[0].date()),
           "ratio_end": str(ratio.index[-1].date()),
           "targets": {}}

    for tgt in TARGETS:
        close = frep.close_series(prices, tgt)
        if close.empty:
            print("## %s —— ✗ 无价格数据，跳过\n" % tgt)
            continue
        sig = sig_all.reindex(close.index).dropna()
        close2 = close.reindex(sig.index).dropna()
        sig = sig.reindex(close2.index)
        if len(sig) < 300:
            print("## %s —— ✗ 样本 %d 天太少，跳过\n" % (tgt, len(sig)))
            continue

        # 🔴 先用**正向**跑一遍看符号 ✓ 符号为负就说明该用逆向 ✗
        rep = fproto.screen_report(
            sig, close2, factor_id="F-021_gold_ratio_%s" % tgt, target=tgt,
            direction="正向", horizons=HORIZONS, window=WINDOW,
            n_buckets=5, fee=fproto.DEFAULT_FEE)
        ic = rep.get("ic") or {}
        h40 = (ic.get(40) or {}).get("rank_icir")
        sign = "正向" if (h40 or 0) > 0 else "逆向"

        print(frep.report_block(
            rep, "目标 %s（样本 %d 天）" % (tgt, len(sig)),
            HORIZONS, sig=sig, close=close2))
        print("  ⇒ 实测 h40 rank_ICIR %s ⇒ **方向应为「%s」** ✓\n"
              % (frep.fmt(h40), sign))
        out["targets"][tgt] = {
            "n_days": len(sig), "h40_icir": h40, "suggest_direction": sign,
            "report": rep,
        }

    if args.json:
        p = Path(args.json)
        if not p.is_absolute():
            p = REPO / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2,
                                default=str), encoding="utf-8")
        print("[已写 %s]" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
