#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ENE **减仓触发** 专项回测（2026-10-31 用户裁定）。

【为什么单独做这个】

C5 六标的裁判（`c5_backtest`）的结论是：

  - 作为**全仓择时信号**：无效 ✗（只有 GDXU 一个真赚钱）
  - 但**回撤 6/6 全面改善**（AXTX +33.6pp、CRCG +28.7pp、GDXU +20.9pp …）✓

⇒ 正确用法不是「ENE 决定全仓比例」，而是「**ENE 超买时减仓**」✓
  本脚本专门测这个用法。

【规则】

    pos  = ENE 通道位置 ∈ [0,1]（0=触下轨超卖，1=触上轨超买）
    仓位 = 1 − pos × reduce_ratio

    reduce_ratio = 0（=B0 买入持有）/ 0.5 / 0.7 / 1.0

  ⇒ pos=0（超卖）恒为满仓 ✓；pos=1（超买）减到 `1−ratio` ✓
  ⇒ 连续函数，无「跳变」⇒ 换手温和 ✓

【口径】
  - T 日信号 shift(1) → T+1 生效（防前视 ✓）
  - 换仓成本 0.0008 / 单位换手（与 `factor_backtest_probe` 一致 ✓）
  - 全样本 + 前后半段（防「某段行情贡献全部收益」✗）

用法：
  .venv/bin/python scripts/backtest_ene_reduce.py
  .venv/bin/python scripts/backtest_ene_reduce.py --json evolution/ene-reduce.json
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
RATIOS = (0.0, 0.5, 0.7, 1.0)     # 0.0 = B0 买入持有
SYMBOLS = ("YINN", "GDXU", "CONL", "CRCG", "AXTX", "SPY")


def _prices():
    return pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])


def _metrics(ret, pos):
    """年化 / 回撤 / Sharpe / Calmar / 平均仓位 ✓。"""
    ret = ret.dropna()
    if len(ret) < 30:
        return None
    nav = (1.0 + ret).cumprod()
    yrs = len(ret) / 252.0
    annual = nav.iloc[-1] ** (1.0 / yrs) - 1.0 if yrs > 0 else np.nan
    peak = nav.cummax()
    mdd = float((nav / peak - 1.0).min())
    vol = float(ret.std() * np.sqrt(252))
    sharpe = float(ret.mean() * 252 / vol) if vol > 0 else np.nan
    return {
        "annual_return": float(annual), "max_drawdown": mdd,
        "sharpe": sharpe,
        "calmar": float(annual / abs(mdd)) if mdd < 0 else np.nan,
        "avg_pos": float(pos.mean()),
        "n_days": int(len(ret)),
    }


def _run(close, pos, ratio, start=None, end=None):
    """按 `仓位 = 1 − pos×ratio` 回测 ✓。"""
    px = close.loc[start:end] if start or end else close
    p = pos.reindex(px.index).ffill()
    r = px.pct_change()
    # T 信号 → T+1 生效 ✓
    w = (1.0 - p * ratio).clip(0.0, 1.0).shift(1)
    turn = w.diff().abs().fillna(0.0)
    ret = w * r - turn * COST
    return _metrics(ret, w)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH", help="把结果写到 JSON")
    args = ap.parse_args(argv)

    prices = _prices()
    out = {}
    print("# ENE 减仓触发回测（仓位 = 1 − pos×ratio；0 = 买入持有 B0）")
    print("# 成本 %.4f/单位换手；T 信号 shift(1) → T+1 生效\n" % COST)

    for sym in SYMBOLS:
        close = fene.close_series(prices, sym)
        if len(close) < 300:
            print("## %s —— 样本不足，跳过" % sym)
            continue
        pos = fene.ene_pos(prices, sym).reindex(close.index)
        if pos.dropna().empty:
            print("## %s —— 无信号，跳过" % sym)
            continue

        print("## %s（%s → %s，%d 天）"
              % (sym, close.index[0].date(), close.index[-1].date(),
                 len(close)))
        print("| ratio | 年化 | 回撤 | Sharpe | Calmar | 平均仓位 |")
        print("|---|---|---|---|---|---|")
        out[sym] = {}
        for ratio in RATIOS:
            m = _run(close, pos, ratio)
            if not m:
                continue
            tag = "B0 买入持有" if ratio == 0 else "减仓 %.0f%%" % (ratio * 100)
            out[sym][tag] = m
            print("| %.1f | %+.2f%% | %.2f%% | %.2f | %.2f | %.0f%% |"
                  % (ratio, m["annual_return"] * 100, m["max_drawdown"] * 100,
                     m["sharpe"], m["calmar"], m["avg_pos"] * 100))
        print()

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
