#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M2.3 权重/档位敏感性：WEIGHTS 扰动 → fg_index 变化 → 组合回测。

与阶段 1（circuit/zone/core/trim）合并进 evolution/sensitivity/，为 C-3 审批
提供「WEIGHTS 变动 → 输出影响」证据表（M2.3 验收：审批提案必须附敏感性表）。

口径（纪律）：
- 只测量不改参：monkeypatch config.WEIGHTS 临时扰动，try/finally 恢复；
  `pipeline.run(write=False)` 不写 features.csv / state.json，生产零改动。
- 扰动：每因子 w_k → w_k × (1 ± 0.10)，其余因子等比例缩放重归一（Σ=1）。
- 影响维度：
  1) fg_index Δ（max|Δ|、mean|Δ|）——指数输出变化；
  2) zone 翻转天数——档位边界 [20,40,60,80] 跨越次数；
  3) target_position 变化天数——仓位信号变化；
  4) 组合回测（复用 M2.1 scripts.portfolio_backtest.build_portfolio）——
     组合 OOS 年化/回撤/Sharpe（含成本，与基线同引擎）。

用法：
  .venv/bin/python scripts/weight_sensitivity.py [--delta 0.10] [--factors vix,term]
输出：evolution/sensitivity/sensitivity_weights.md + .json（README 汇总由 main 追加）
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/ 在 sys.path

from fg_system import config  # noqa: E402
from fg_system import pipeline  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data"
RAW = DATA / "raw"
OUT = REPO / "evolution" / "sensitivity"

import scripts.portfolio_backtest as pb  # noqa: E402  # M2.1 组合层复用


def perturb(weights: dict, factor: str, delta: float) -> dict:
    """因子 ±delta 扰动，其余等比例缩放重归一（Σ=1，保持总量不变）。"""
    w = dict(weights)
    w[factor] *= (1.0 + delta)
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def run_perturbed(features, prices, factor, delta, oos_start) -> dict:
    new_w = perturb(dict(config.WEIGHTS), factor, delta)
    old_w = dict(config.WEIGHTS)
    try:
        config.WEIGHTS = new_w
        feats = pipeline.run(write=False)
    finally:
        config.WEIGHTS = old_w

    base = features.set_index("date")
    fg_delta = (feats["fg_index"] - base["fg_index"]).dropna()
    zone_flip = (feats["zone"] != base["zone"]).sum()
    tgt_flip = ((feats["target_position"].fillna(0) - base["target_position"].fillna(0)).abs() > 1e-9).sum()

    port = pb.build_portfolio(feats, prices, oos_start=oos_start)
    oos = port["metrics"]["portfolio"]["oos"]
    b0 = port["metrics"]["buyhold"]["oos"]
    return {
        "factor": factor, "delta": delta,
        "fg_delta_max": float(fg_delta.abs().max()) if len(fg_delta) else None,
        "fg_delta_mean": float(fg_delta.abs().mean()) if len(fg_delta) else None,
        "zone_flip_days": int(zone_flip),
        "target_flip_days": int(tgt_flip),
        "portfolio_oos": {"annual_return": oos["annual_return"],
                          "max_drawdown": oos["max_drawdown"],
                          "sharpe": oos["sharpe"]},
        "buyhold_oos": {"annual_return": b0["annual_return"],
                        "max_drawdown": b0["max_drawdown"],
                        "sharpe": b0["sharpe"]},
    }


def render(results, base_w, base, delta) -> str:
    lines = [
        "# 权重敏感性（M2.3）：WEIGHTS 扰动 → fg_index → 组合回测",
        "",
        "- 生成：%s · scripts/weight_sensitivity.py" % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "- 口径：仅测不改（monkeypatch 临时扰动，try/finally 恢复；pipeline.run(write=False) 生产零改动）",
        "- 扰动：单因子 ×(1±%.0f%%)，其余等比例重归一 Σ=1" % (delta * 100),
        "- 基准 WEIGHTS：%s" % json.dumps(base_w, ensure_ascii=False),
        "- 组合回测：M2.1 复用（等权 1/3 TQQQ/SOXL/UPRO，含成本，OOS 2024-10-03 起）",
        "- 基准组合 OOS：年化 %.2f%% / 回撤 %.1f%% / Sharpe %.2f" % (
            base["annual_return"] * 100, base["max_drawdown"] * 100, base["sharpe"]),
        "",
        "| 因子 | 扰动 | fg_index max\\|Δ\\| | mean\\|Δ\\| | zone 翻转天数 | target 变化天数 | 组合年化 | 组合回撤 | 组合 Sharpe |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append("| %s | %+.0f%% | %.2f | %.2f | %d | %d | %.2f%% | %.1f%% | %.2f |" % (
            r["factor"], r["delta"] * 100,
            r["fg_delta_max"] or 0, r["fg_delta_mean"] or 0,
            r["zone_flip_days"], r["target_flip_days"],
            (r["portfolio_oos"]["annual_return"] or 0) * 100,
            (r["portfolio_oos"]["max_drawdown"] or 0) * 100,
            r["portfolio_oos"]["sharpe"] or 0))
    lines += ["", "> 只测量不改参；如需调参走阶段 2 变体 + C-2/C-3 审批（附本表）。"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="M2.3 权重敏感性扫描")
    ap.add_argument("--delta", type=float, default=0.10)
    ap.add_argument("--factors", default=",".join(list(config.WEIGHTS.keys())))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    factors = [f.strip() for f in args.factors.split(",") if f.strip()]
    features = pd.read_csv(DATA / "features.csv", parse_dates=["date"])
    prices = pd.read_csv(RAW / "prices.csv", parse_dates=["date"])

    # 基准组合（生产 WEIGHTS）
    base_port = pb.build_portfolio(features, prices)
    base_metrics = base_port["metrics"]["portfolio"]["oos"]
    base_w = dict(config.WEIGHTS)

    results = []
    for f in factors:
        for d in (+args.delta, -args.delta):
            print("[weight-sens] %s %+.0f%% ..." % (f, d * 100), flush=True)
            results.append(run_perturbed(features, prices, f, d,
                                         oos_start=pb.OOS_START))

    md = render(results, base_w, base_metrics, args.delta)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sensitivity_weights.md").write_text(md, encoding="utf-8")
    print(md)
    if args.json:
        (OUT / "sensitivity_weights.json").write_text(
            json.dumps({"base_weights": base_w,
                        "base_portfolio_oos": base_metrics,
                        "delta": args.delta, "results": results},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print("[weight-sens] json → evolution/sensitivity/sensitivity_weights.json")
    print("[weight-sens] md → evolution/sensitivity/sensitivity_weights.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
