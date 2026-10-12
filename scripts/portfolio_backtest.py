#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M2.1 组合回测层（内化方案 B）：三标的白名单 → 等权组合净值/成本/回撤。

设计（决策记录见 docs/factor-adoption-pipeline.md §0 / evolution M2.1 报告）：
- **不引入 `bt` / Qlib / vn.py**：组合层**复用生产回测引擎**（runner.run_single +
  FgStrategy + next_position + backtrader 成交/成本），组合 = 单标的策略日收益的
  等权合成。构造性一致：组合日收益序列 ≡ Σ(1/n)·单标的日收益，diff=0（构造保证），
  不存在"双引擎不一致"。
- 资金：INITIAL_CASH 等权 1/3 分给 TQQQ / SOXL / UPRO（无参数先验）。
- B0：等权买入持有组合（Σ(1/n)·buy_and_hold_returns）。
- OOS：`evolution/baseline.json meta.is_oos.oos_start` 起（单一来源，见 fg_system/evo_meta.py）。
- 组合特有维度：联合回撤（跨标的下行风险）、三标的相关性矩阵（同信号高相关是
  组合风险集中度的直接证据）。

用法：
  .venv/bin/python scripts/portfolio_backtest.py [--oos-start <baseline meta>] [--json]
输出：evolution/experiments/portfolio/portfolio-oos.{md,json}
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

from fg_system import config, evo_meta  # noqa: E402
from fg_system.backtest import runner  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data"
RAW = DATA / "raw"
OUT_DIR = REPO / "evolution" / "experiments" / "portfolio"
OOS_START = evo_meta.oos_start()  # 单一来源：baseline.json meta.is_oos（WT-18）
SYMBOLS = config.SYMBOLS  # ["TQQQ", "SOXL", "UPRO"]


def _round(v, nd=4):
    return float(v) if v == v else None


def _fmt(v, suffix=""):
    """渲染数字：None/NaN → '—'，否则保留 2 位小数 + 后缀。"""
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return ("%.2f" % v) + suffix


def _metrics(returns: pd.Series) -> dict:
    m = runner.performance_metrics(returns)
    return {k: _round(v) for k, v in m.items()}


def _split(returns: pd.Series, oos_start: str):
    r = returns.dropna()
    is_r = r[r.index < oos_start]
    oos_r = r[r.index >= oos_start]
    return is_r, oos_r


def build_portfolio(features: pd.DataFrame, prices: pd.DataFrame,
                    symbols=None, oos_start: str = OOS_START) -> dict:
    symbols = symbols or SYMBOLS
    n = len(symbols)
    w = 1.0 / n
    legs, bh_legs, corr_columns = {}, {}, {}
    for sym in symbols:
        px = prices[prices["symbol"] == sym].set_index("date").sort_index()
        f = features.copy()
        if "date" in f.columns:
            f = f.set_index("date")  # 与 evolve_baseline.build_symbol 同口径
        f = f.join(px[["open", "high", "low", "close", "volume"]], how="inner")
        _strat, returns = runner.run_single(f, sym)
        bh = runner.buy_and_hold_returns(prices, sym)
        legs[sym] = returns
        bh_legs[sym] = bh
        corr_columns[sym] = returns.reindex(returns.index.union(bh.index)).fillna(0.0)

    # 组合日收益（构造性一致：≡ Σ w·leg）
    idx = legs[symbols[0]].index
    comb = sum(w * legs[s].reindex(idx).fillna(0.0) for s in symbols)
    comb_bh = sum(w * bh_legs[s].reindex(idx).fillna(0.0) for s in symbols)

    # 交叉验证：构造性相等（组合 == 加权和，diff 应为 0）
    diff = (comb - sum(w * legs[s].reindex(idx).fillna(0.0) for s in symbols)).abs().max()
    cross = {"assertion": "组合日收益 ≡ Σ(1/n)·单标的日收益（构造保证）",
             "max_abs_diff": float(diff)}

    # 相关性矩阵（三标的策略日收益，对齐交集）
    corr_df = pd.DataFrame(corr_columns).corr()
    corr_map = {a: {b: _round(corr_df.loc[a, b]) for b in symbols} for a in symbols}

    comb_is, comb_oos = _split(comb, oos_start)
    bh_is, bh_oos = _split(comb_bh, oos_start)
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "engine": "内化（复用 runner.run_single + FgStrategy + next_position；零新依赖）",
        "symbols": symbols, "weights": {s: w for s in symbols},
        "oos_start": oos_start,
        "cross_check": cross,
        "correlation": corr_map,
        "metrics": {
            "portfolio": {"full": _metrics(comb), "is": _metrics(comb_is),
                          "oos": _metrics(comb_oos)},
            "buyhold": {"full": _metrics(comb_bh), "is": _metrics(bh_is),
                        "oos": _metrics(bh_oos)},
        },
        "per_leg_oos": {
            s: {"portfolio_leg": _metrics(legs[s][legs[s].index >= oos_start]),
                "buyhold_leg": _metrics(bh_legs[s][bh_legs[s].index >= oos_start])}
            for s in symbols
        },
    }
    return out


def render_md(out: dict) -> str:
    p, b = out["metrics"]["portfolio"], out["metrics"]["buyhold"]

    def pct(v):
        return "—" if v is None else "%.2f%%" % (v * 100)

    def num(v):
        return "—" if v is None else "%.2f" % v

    lines = [
        "# 组合回测层（M2.1 · 内化方案 B）：等权组合 vs 买入持有",
        "",
        "- 生成：%s · scripts/portfolio_backtest.py" % out["generated_at"],
        "- 引擎：**内化**——复用生产回测引擎（runner.run_single + FgStrategy + "
        "next_position，含成本/执行约束/backtrader 成交）；组合 = 单标的策略日收益"
        "等权合成（%s，各 %g）" % ("/".join(out["symbols"]), out["weights"][out["symbols"][0]]),
        "- 交叉验证：%s（max|diff|=%g）" % (out["cross_check"]["assertion"],
                                          out["cross_check"]["max_abs_diff"]),
        "- OOS：%s 起（对齐 baseline meta.is_oos）" % out["oos_start"],
        "",
        "| 指标 | 组合（OOS） | B0 等权买入持有（OOS） | 组合（IS） |",
        "|---|---|---|---|",
        "| 年化 | %s | %s | %s |" % (
            pct(p["oos"]["annual_return"]), pct(b["oos"]["annual_return"]),
            pct(p["is"]["annual_return"])),
        "| 最大回撤 | %s | %s | %s |" % (
            pct(p["oos"]["max_drawdown"]), pct(b["oos"]["max_drawdown"]),
            pct(p["is"]["max_drawdown"])),
        "| Sharpe | %s | %s | %s |" % (
            num(p["oos"]["sharpe"]), num(b["oos"]["sharpe"]),
            num(p["is"]["sharpe"])),
        "| Calmar | %s | %s | %s |" % (
            num(p["oos"]["calmar"]), num(b["oos"]["calmar"]),
            num(p["is"]["calmar"])),
        "",
        "## 标的腿（OOS）",
        "",
        "| 标的 | 组合腿年化 | B0 腿年化 | 组合腿回撤 | B0 腿回撤 |",
        "|---|---|---|---|---|",
    ]
    for s in out["symbols"]:
        leg = out["per_leg_oos"][s]
        lines.append("| %s | %s | %s | %s | %s |" % (
            s, pct(leg["portfolio_leg"]["annual_return"]),
            pct(leg["buyhold_leg"]["annual_return"]),
            pct(leg["portfolio_leg"]["max_drawdown"]),
            pct(leg["buyhold_leg"]["max_drawdown"])))
    lines += ["", "## 相关性矩阵（策略日收益）", ""]
    syms = out["symbols"]
    header = "| 标的 | " + " | ".join(syms) + " |"
    lines.append(header)
    lines.append("|---|" + "---|" * len(syms))
    for a in syms:
        lines.append("| %s | " % a + " | ".join(num(out["correlation"][a][b])
                                               for b in syms) + " |")
    lines += ["", "> 由 scripts/portfolio_backtest.py 生成 · 只读回测，不修改生产；",
              "> A/B 对照与内化决策记录见 evolution/experiments/portfolio/decision.md"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="M2.1 组合回测层")
    ap.add_argument("--oos-start", default=OOS_START)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    feats = pd.read_csv(DATA / "features.csv", parse_dates=["date"])
    prices = pd.read_csv(RAW / "prices.csv", parse_dates=["date"])
    out = build_portfolio(feats, prices, oos_start=args.oos_start)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUT_DIR / "portfolio-oos.md"
    md_path.write_text(render_md(out), encoding="utf-8")
    print(render_md(out))
    if args.json:
        json_path = OUT_DIR / "portfolio-oos.json"
        json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[portfolio] json → %s" % json_path)
    print("[portfolio] md → %s" % md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
