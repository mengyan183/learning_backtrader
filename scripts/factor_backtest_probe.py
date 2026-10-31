#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M2.2 回测裁判探针：候选因子 → OOS 单标的回测（含成本），供 C-3 审批。

用途：R1.1 评测通过（IC/ICIR 达标）的候选因子，未必能赚钱（评测是相关性强弱，
回测是净收益）。本脚本对单个因子做**确定性 OOS 回测裁判**，产出与既有回测
同口径的指标表，供 factor-adoption-pipeline 的 C-3 审批使用。

口径（全部无参数先验，非调参，可复核）：
- 信号：features 的因子列（如 putcall，生产同源，0-100 已归一）
- 方向：--direction positive（因子高=看多未来收益）或 negative（高=看空）
- 仓位映射：因子对其自身 756 日滚动百分位 rank ∈ [0,1]
    pos = 0.2 + 0.8 * (rank 或 1-rank)   （恐慌满仓、贪婪留 20% 底仓的先验）
- 执行：T 日信号 shift(1) → T+1 生效（pipeline §10.3 红线，无前视）
- 收益：daily_ret = pos.shift(1) * close.pct_change() - cost * |Δpos|
    cost = commission 0.0003 + slippage 0.00050（config 原值单边）
- 对照：B0 = 同期 TQQQ buy&hold；OOS 起点 = baseline meta（单一来源）

用法：
  .venv/bin/python scripts/factor_backtest_probe.py --factor putcall --symbol TQQQ
输出：evolution/experiments/factor-adoption/<factor>-<symbol>-oos.{md,json}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fg_system import evo_meta  # noqa: E402
from fg_system.backtest.runner import performance_metrics  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data"
RAW = DATA / "raw"
OUT_DIR = REPO / "evolution" / "experiments" / "factor-adoption"
OOS_START = evo_meta.oos_start()  # WT-18 单一来源
COST = 0.0003 + 0.00050  # commission + slippage（config 原值单边）
ROLL = 756


def rolling_rank(s: pd.Series, window: int = ROLL, min_periods: int = 60) -> pd.Series:
    """因子对自身滚动分位 rank ∈ [0,1]（只用 ≤T 数据，无前视）。"""
    def _rank_last(x):
        return (x <= x[-1]).mean() if len(x) > 0 and not np.isnan(x[-1]) else np.nan
    return s.rolling(window, min_periods=min_periods).apply(_rank_last, raw=True)


def run_probe(factor: str, symbol: str, direction: str, oos_start: str = OOS_START,
               features_path=None) -> dict:
    feats = pd.read_csv(features_path or (DATA / "features.csv"), parse_dates=["date"])
    prices = pd.read_csv(RAW / "prices.csv", parse_dates=["date"])
    if factor not in feats.columns:
        raise SystemExit("features 无因子列 %r（可用：%s）" % (factor, list(feats.columns)))
    px = prices[prices["symbol"] == symbol].set_index("date")["close"].rename("close")
    df = feats.set_index("date")[[factor]].join(px, how="inner").sort_index()
    df = df.dropna(subset=[factor, "close"])

    df["rank"] = rolling_rank(df[factor])
    df = df.dropna(subset=["rank"])
    # 方向：positive=高分看多（rank 直接映射仓位）；negative=高分看空（1-rank）
    base = df["rank"] if direction == "positive" else 1.0 - df["rank"]
    df["pos"] = (0.2 + 0.8 * base).clip(0.2, 1.0)
    df["ret"] = df["close"].pct_change()
    # T 信号 → T+1 生效；换仓成本按 |Δpos| * 单边成本
    df["pos_prev"] = df["pos"].shift(1)
    df["cost"] = df["pos"].diff().abs().fillna(0.0) * COST
    df["strat_ret"] = df["pos_prev"] * df["ret"] - df["cost"]

    oos = df[df.index >= oos_start].copy()
    if len(oos) < 60:
        raise SystemExit("OOS 样本不足：%d 行（%s 起）" % (len(oos), oos_start))

    strat = performance_metrics(oos["strat_ret"])
    bh = performance_metrics(oos["ret"])
    in_sample = performance_metrics(df[df.index < oos_start]["strat_ret"])

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "factor": factor, "symbol": symbol, "direction": direction,
        "oos_start": oos_start, "oos_days": len(oos),
        "cost_per_unit_turnover": COST,
        "metrics": {
            "strategy_oos": strat, "buyhold_oos": bh, "strategy_is": in_sample,
        },
        # 🔴 2026-10-31 用户裁定：判定标准加「**策略 Sharpe > 0**」✗
        # 实测（C5 ENE 六标的）：AXTX 策略年化 -65.83%、CRCG -33.92%、
        # YINN -9.85%，却都因为「B0 亏得更多」被判 **PASS** ✗
        # ⇒ 原标准在亏损标的上退化成「比烂」✗
        # 新标准三条全满足才算 PASS：① 跑赢 B0 ② 回撤不劣化 ③ **自己得赚钱** ✓
        "verdict": (
            "PASS（OOS 年化 > B0、回撤不劣化、且 Sharpe > 0）"
            if (strat["annual_return"] > bh["annual_return"]
                and strat["max_drawdown"] >= bh["max_drawdown"]
                and strat["sharpe"] > 0)
            else ("FAIL（OOS 亏钱：Sharpe ≤ 0，只是「比买入持有少亏」✗）"
                  if strat["sharpe"] <= 0
                  else "FAIL（OOS 未优于 B0，不采纳候选入生产）")),
    }
    return out


def render_md(out: dict) -> str:
    s, b = out["metrics"]["strategy_oos"], out["metrics"]["buyhold_oos"]
    i = out["metrics"]["strategy_is"]
    lines = [
        "# 回测裁判：%s（%s）→ %s OOS" % (out["factor"], out["direction"], out["symbol"]),
        "",
        "- 生成：%s · scripts/factor_backtest_probe.py" % out["generated_at"],
        "- 口径：因子 756 日滚动分位 → 仓位 0.2~1.0 线性映射（无参数先验）；"
        "T 信号 shift(1) → T+1 生效；换仓成本 %g/单位换手；OOS 起 %s（%d 日）"
        % (out["cost_per_unit_turnover"], out["oos_start"], out["oos_days"]),
        "- 判定：**%s**" % out["verdict"],
        "",
        "| 指标 | 策略（OOS） | B0 买入持有 | 样本内 |",
        "|---|---|---|---|",
        "| OOS 年化 | %.2f%% | %.2f%% | %.2f%% |" % (
            s["annual_return"] * 100, b["annual_return"] * 100, i["annual_return"] * 100),
        "| 最大回撤 | %.1f%% | %.1f%% | %.1f%% |" % (
            s["max_drawdown"] * 100, b["max_drawdown"] * 100, i["max_drawdown"] * 100),
        "| Sharpe | %.2f | %.2f | %.2f |" % (s["sharpe"], b["sharpe"], i["sharpe"]),
        "| Calmar | %.2f | %.2f | %.2f |" % (s["calmar"], b["calmar"], i["calmar"]),
        "",
        "> 由 scripts/factor_backtest_probe.py 生成 · 确定性判定，无 LLM 判决；",
        "> 仅作 C-3 审批证据，不直接改动生产。",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="M2.2 回测裁判探针")
    ap.add_argument("--factor", default="putcall", help="features 因子列（默认 putcall）")
    ap.add_argument("--symbol", default="TQQQ", help="目标标的（默认 TQQQ）")
    ap.add_argument("--direction", choices=["positive", "negative"], default="positive",
                    help="因子方向（F-011 正向：高分=恐慌=未来涨）")
    ap.add_argument("--oos-start", default=OOS_START)
    ap.add_argument("--features", default=None, help="研究专用特征文件（默认 Data/features.csv；F-013 用 evolution/experiments/factor-adoption/features_f013.csv）")
    args = ap.parse_args()

    out = run_probe(args.factor, args.symbol, args.direction, args.oos_start,
                     args.features)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUT_DIR / f"{args.factor}-{args.symbol}-oos.md"
    json_path = OUT_DIR / f"{args.factor}-{args.symbol}-oos.json"
    md_path.write_text(render_md(out), encoding="utf-8")
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(render_md(out))
    print("[probe] md → %s\n[probe] json → %s" % (md_path, json_path))
    return 0 if "PASS" in out["verdict"] else 1


if __name__ == "__main__":
    sys.exit(main())
