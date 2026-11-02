#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ENE 减仓比例 `ratio` 的**扫描 + 二分细化**（2026-11-02 用户裁定）。

【要回答的问题】
`仓位 = 1 − pos × ratio` 里的 `ratio` 取多少合适？

已测过 0 / 0.5 / 0.7 / 1.0，但那是**四个离散点**，看不出曲线形状 ✗
⇒ 本脚本先**粗扫**（0~1，步长 0.1）看形状，再在最优附近**二分细化**到 0.01 ✓

【目标函数】
用 **Calmar**（年化 / 最大回撤）作主判据 ✓ 理由：
  - 只看年化会偏向「激进清仓」（ratio=1 在震荡市年化最高 ✗）
  - 只看回撤会偏向「一直空仓」（ratio 越大回撤越小 ✗）
  - Calmar 同时约束两者 ✓

同时报 Sharpe 作对照 ✓

【样本】
**只算杠杆 ETF**（YINN / GDXU / CONL）✓
SPY 已知「减仓是亏的」（2026-10-31 实测：年化 13.76% → 7.46% ✗）
⇒ 把它算进目标函数会**反向拉低**最优 ratio ✗

用法：
  .venv/bin/python scripts/sweep_ene_ratio.py
  .venv/bin/python scripts/sweep_ene_ratio.py --json evolution/ene-ratio.json
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fg_system.factors import ene as fene   # noqa: E402

DATA = REPO / "Data"
COST = 0.0008
#: 只对杠杆 ETF 优化 ✓（SPY 会反向拉低 ✗）
TARGETS = ("YINN", "GDXU", "CONL")
#: 粗扫步长
COARSE_STEP = 0.1
#: 二分细化精度
FINE_TOL = 0.01


def _prices():
    return pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])


def _metrics(ret, w):
    ret = ret.dropna()
    if len(ret) < 60:
        return None
    nav = (1.0 + ret).cumprod()
    yrs = len(ret) / 252.0
    annual = nav.iloc[-1] ** (1.0 / yrs) - 1.0
    mdd = float((nav / nav.cummax() - 1.0).min())
    vol = float(ret.std() * np.sqrt(252))
    return {
        "annual": float(annual), "mdd": mdd,
        "sharpe": float(ret.mean() * 252 / vol) if vol > 0 else np.nan,
        "calmar": float(annual / abs(mdd)) if mdd < 0 else np.nan,
        "avg_pos": float(w.mean()),
    }


def _run(close, pos, ratio):
    p = pos.reindex(close.index).ffill()
    r = close.pct_change()
    w = (1.0 - p * ratio).clip(0.0, 1.0).shift(1)
    turn = w.diff().abs().fillna(0.0)
    return _metrics(w * r - turn * COST, w)


def _score(prices, ratio):
    """三标的**平均 Calmar** ✓（缺失的标的跳过 ✓）。"""
    vals = []
    for sym in TARGETS:
        close = fene.close_series(prices, sym)
        if len(close) < 300:
            continue
        pos = fene.ene_pos(prices, sym)
        m = _run(close, pos, ratio)
        if m and np.isfinite(m["calmar"]):
            vals.append(m["calmar"])
    return float(np.mean(vals)) if vals else np.nan


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args(argv)

    prices = _prices()
    print("# ENE 减仓 ratio 扫描（目标 = 三杠杆 ETF 平均 Calmar）")
    print("# 标的：%s；成本 %.4f/单位换手\n" % ("/".join(TARGETS), COST))

    # --- 粗扫 ---
    grid = [round(i * COARSE_STEP, 2) for i in
            range(int(round(1.0 / COARSE_STEP)) + 1)]
    print("## 粗扫（步长 %.2f）" % COARSE_STEP)
    print("| ratio | 平均Calmar | 平均Sharpe | 平均年化 | 平均回撤 | 平均仓位 |")
    print("|---|---|---|---|---|---|")
    coarse = {}
    for r in grid:
        sc = _score(prices, r)
        # 取三标的均值做展示 ✓
        ms = []
        for sym in TARGETS:
            close = fene.close_series(prices, sym)
            if len(close) < 300:
                continue
            m = _run(close, fene.ene_pos(prices, sym), r)
            if m:
                ms.append(m)
        if not ms:
            continue
        avg = {k: float(np.mean([m[k] for m in ms])) for k in ms[0]}
        coarse[r] = {"score": sc, **avg}
        print("| %.2f | %+.3f | %+.3f | %+.2f%% | %.2f%% | %.0f%% |"
              % (r, sc, avg["sharpe"], avg["annual"] * 100,
                 avg["mdd"] * 100, avg["avg_pos"] * 100))

    if not coarse:
        print("✗ 无有效结果")
        return 2

    # --- 找粗扫最优点，二分细化 ---
    best_r = max(coarse, key=lambda k: coarse[k]["score"])
    lo, hi = max(0.0, best_r - COARSE_STEP), min(1.0, best_r + COARSE_STEP)
    print("\n## 二分细化（区间 [%.2f, %.2f]，精度 %.2f）"
          % (lo, hi, FINE_TOL))
    print("| 迭代 | lo | hi | mid | Calmar |")
    print("|---|---|---|---|---|")
    it = 0
    while hi - lo > FINE_TOL and it < 12:
        it += 1
        mid = round((lo + hi) / 2, 4)
        sc_mid = _score(prices, mid)
        # 用三点比较决定方向（mid vs lo vs hi）✓
        sc_lo, sc_hi = _score(prices, lo), _score(prices, hi)
        print("| %d | %.3f | %.3f | %.3f | %+.3f |"
              % (it, lo, hi, mid, sc_mid))
        if sc_mid >= max(sc_lo, sc_hi):
            # mid 最好 ⇒ 收窄到更靠 mid 的一侧 ✓
            lo, hi = (lo, mid) if sc_lo > sc_hi else (mid, hi)
        elif sc_lo > sc_mid:
            hi = mid
        else:
            lo = mid
    best_fine = round((lo + hi) / 2, 2)
    print("\n⇒ 粗扫最优 **%.2f**（Calmar %+.3f）" % (best_r, coarse[best_r]["score"]))
    print("⇒ 细化最优 **%.2f**（Calmar %+.3f）"
          % (best_fine, _score(prices, best_fine)))

    if args.json:
        p = Path(args.json)
        if not p.is_absolute():
            p = REPO / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "coarse": {str(k): v for k, v in coarse.items()},
            "best_coarse": best_r, "best_fine": best_fine,
            "targets": list(TARGETS),
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("\n[已写 %s]" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
