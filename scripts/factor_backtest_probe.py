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

#: 🔴 2026-11-12 用户裁定 P0②：**Sharpe 差异 < 0.10 视为噪音** ✗
#:    实测 F-021/TQQQ：策略 0.48 vs B0 0.46（差 0.02）曾被当成「略优」✗
#:    但 OOS 仅 519 天 ⇒ 这个差异**统计上不可区分** ✗
#:    ⇒ 回执里显式给 `sharpe_delta` + 本阈值，判定时不拿噪音当证据 ✓
SHARPE_NOISE = 0.10


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

    # 🔴 2026-11-12 用户裁定 P0①：**加「同平均仓位基准」B0'** ✓
    #    问题：`pos = 0.2 + 0.8×rank` ⇒ 平均仓位约 60%，而 B0 是 **100% 满仓** ✗
    #    ⇒ 在长期上涨标的上，60% 仓位**数学上必然**跑输 100% 约 12pp ✗
    #    ⇒ 这是「仓位暴露差异」，不是「因子无效」✗
    #    实测 F-021/TQQQ：年化 19.62% vs B0 30.28%（-10.66pp ✗）
    #                     但 Sharpe 0.48 vs 0.46、Calmar 0.54 vs 0.52 ✓
    #    ⇒ 加 B0' = **同平均仓位恒定持有** ✓，主判据改成「**择时 alpha > 0**」✓
    pos_mean = float(oos["pos_prev"].mean())
    b0_equiv = performance_metrics(pos_mean * oos["ret"])
    alpha = strat["annual_return"] - b0_equiv["annual_return"]

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "factor": factor, "symbol": symbol, "direction": direction,
        "oos_start": oos_start, "oos_days": len(oos),
        "cost_per_unit_turnover": COST,
        "metrics": {
            "strategy_oos": strat, "buyhold_oos": bh, "strategy_is": in_sample,
            # 🔴 P0①：同仓位基准（衡量「择时能力」而非「仓位高低」）✓
            "buyhold_samepos_oos": b0_equiv,
        },
        "pos_mean": round(pos_mean, 4),
        # 择时 alpha = 策略年化 − 同平均仓位基准年化 ✓
        "timing_alpha": round(alpha, 6),
        # 🔴 P0②：**Sharpe 差异 < 0.10 视为噪音** ✗
        #    实测 F-021/TQQQ 0.48 vs 0.46（差 0.02）被当成「略优」✗
        #    而 519 天 OOS 上这个差异**统计上不可区分** ✗
        "sharpe_delta": round(strat["sharpe"] - bh["sharpe"], 4),
        "sharpe_noise_threshold": SHARPE_NOISE,
        # 🔴 2026-10-31 用户裁定：判定标准加「**策略 Sharpe > 0**」✗
        # 实测（C5 ENE 六标的）：AXTX 策略年化 -65.83%、CRCG -33.92%、
        # YINN -9.85%，却都因为「B0 亏得更多」被判 **PASS** ✗
        # ⇒ 原标准在亏损标的上退化成「比烂」✗
        # 🔴 2026-11-12 用户裁定 P0③：**主判据从「年化 vs 满仓 B0」改成
        #    「择时 alpha > 0」** ✓（年化作为参考，不再作为判定依据 ✗）
        #    三条全满足才算 PASS：① 择时 alpha > 0 ② 回撤不劣化 ③ 自己赚钱 ✓
        "verdict": (
            "PASS（择时 alpha > 0、回撤不劣化、且 Sharpe > 0）"
            if (alpha > 0
                and strat["max_drawdown"] >= bh["max_drawdown"]
                and strat["sharpe"] > 0)
            else ("FAIL（OOS 亏钱：Sharpe ≤ 0，只是「比买入持有少亏」✗）"
                  if strat["sharpe"] <= 0
                  else ("FAIL（**无择时 alpha** ✗：策略年化 %.2f%% ≤ 同仓位基准 "
                        "%.2f%%（pos_mean=%.2f）⇒ 它只是「仓位低」不是「择时好」）"
                        % (strat["annual_return"] * 100,
                           b0_equiv["annual_return"] * 100, pos_mean)
                        if alpha <= 0
                        else "FAIL（回撤劣化：%.1f%% < B0 %.1f%% ✗）"
                             % (strat["max_drawdown"] * 100,
                                bh["max_drawdown"] * 100)))),
    }
    return out


def render_md(out: dict) -> str:
    s, b = out["metrics"]["strategy_oos"], out["metrics"]["buyhold_oos"]
    i = out["metrics"]["strategy_is"]
    # 🔴 P0①：同平均仓位基准（衡量择时能力，不是仓位高低）✓
    q = out["metrics"].get("buyhold_samepos_oos") or {}
    _alpha = out.get("timing_alpha")
    _sd = out.get("sharpe_delta")
    lines = [
        "# 回测裁判：%s（%s）→ %s OOS" % (out["factor"], out["direction"], out["symbol"]),
        "",
        "- 生成：%s · scripts/factor_backtest_probe.py" % out["generated_at"],
        "- 口径：因子 756 日滚动分位 → 仓位 0.2~1.0 线性映射（无参数先验）；"
        "T 信号 shift(1) → T+1 生效；换仓成本 %g/单位换手；OOS 起 %s（%d 日）"
        % (out["cost_per_unit_turnover"], out["oos_start"], out["oos_days"]),
        # 🔴 P0①/②：把「同仓位基准」和「Sharpe 噪音阈值」写进回执 ✓
        "- 主判据：**择时 alpha > 0**（策略年化 − 同平均仓位基准 %.2f）✓ —— "
        "不再拿「年化 vs 满仓 B0」判定 ✗（仓位调节型因子天然输仓位）"
        % (out.get("pos_mean") or 0),
        "- 噪音阈值：Sharpe 差异 < **%.2f** 视为不可区分 ✗（OOS 仅 %d 日）"
        % (out.get("sharpe_noise_threshold") or 0, out["oos_days"]),
        "- 判定：**%s**" % out["verdict"],
        "",
        "| 指标 | 策略（OOS） | B0 满仓 | **B0' 同仓位** | 样本内 |",
        "|---|---|---|---|---|",
        "| OOS 年化 | %.2f%% | %.2f%% | **%.2f%%** | %.2f%% |" % (
            s["annual_return"] * 100, b["annual_return"] * 100,
            (q.get("annual_return") or 0) * 100, i["annual_return"] * 100),
        "| 最大回撤 | %.1f%% | %.1f%% | %.1f%% | %.1f%% |" % (
            s["max_drawdown"] * 100, b["max_drawdown"] * 100,
            (q.get("max_drawdown") or 0) * 100, i["max_drawdown"] * 100),
        "| Sharpe | %.2f | %.2f | %.2f | %.2f |" % (
            s["sharpe"], b["sharpe"], q.get("sharpe") or 0, i["sharpe"]),
        "| Calmar | %.2f | %.2f | %.2f | %.2f |" % (
            s["calmar"], b["calmar"], q.get("calmar") or 0, i["calmar"]),
        "",
        "- **择时 alpha = %+.2fpp**（vs B0' 同仓位）%s"
        % ((_alpha or 0) * 100,
           "✓ 有择时能力" if (_alpha or 0) > 0 else "✗ 只是仓位低，不是择时好"),
        "- **Sharpe delta = %+.2f**（vs B0 满仓）%s"
        % (_sd or 0,
           "（在噪音内 ✗ 不可当证据）"
           if abs(_sd or 0) < (out.get("sharpe_noise_threshold") or 0)
           else "（超出噪音 ✓ 可作证据）"),
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
