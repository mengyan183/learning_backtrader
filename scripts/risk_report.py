#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3.2 组合风险度量报告：三标的 OOS 尾部指标（VaR/CVaR/波动/回撤）+ HRP 参考权重。

- 收益口径：复用 M2.1 生产同款 runner（runner.run_single + FgStrategy +
  next_position，含成本），OOS 2024-10-03 起，等权组合 = Σ(1/3)·腿（与
  portfolio_backtest 构造一致，max|diff|=0 已在 M2.1 验证）。
- HRP：fg_system.risk.hrp_weights（相关矩阵层次聚类 + 递归二分 + 逆方差）。
- 对照纪律第 9 条（极贪降仓 25% 底仓 / 极恐分批释弹药）：尾部指标为第 9 条
  的执行提供量化证据（极端态下组合 CVaR 即"若次日再现最差 5% 场景的期望损失"）。
- 纪律：优化器输出仅是参考建议，不得绕过指令卡/人工审批（第 1、8 条）。

用法：.venv/bin/python scripts/risk_report.py [--json]
输出：evolution/experiments/risk/{risk-report.md,risk-report.json}
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fg_system import config  # noqa: E402
from fg_system.backtest import runner  # noqa: E402
from fg_system.risk import cvar, hrp_weights, max_drawdown, risk_report, var  # noqa: E402
import scripts.portfolio_backtest as pb  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data"
RAW = DATA / "raw"
OUT = REPO / "evolution" / "experiments" / "risk"


def _pct(v):
    return "—" if v is None else "%.2f%%" % (v * 100)


def main() -> int:
    ap = argparse.ArgumentParser(description="L3.2 组合风险度量报告")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    features = pd.read_csv(DATA / "features.csv", parse_dates=["date"])
    prices = pd.read_csv(RAW / "prices.csv", parse_dates=["date"])
    oos_start = pb.OOS_START

    # 三标的策略收益（生产同款 runner，与 pb.build_portfolio 同构）+ 等权组合
    legs = {}
    for sym in config.SYMBOLS:
        px = prices[prices["symbol"] == sym].set_index("date").sort_index()
        f = features.copy()
        if "date" in f.columns:
            f = f.set_index("date")
        f = f.join(px[["open", "high", "low", "close", "volume"]], how="inner")
        _, rets = runner.run_single(f, sym)
        legs[sym] = rets[rets.index >= oos_start]

    df = pd.DataFrame(legs).dropna(how="all")
    comb = sum((1.0 / len(config.SYMBOLS)) * df[c] for c in config.SYMBOLS)

    # 等权组合尾部 + HRP 参考权重
    report = risk_report(df)
    report["hrp_weights"] = hrp_weights(df)
    report["oos_start"] = oos_start
    report["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    report["discipline_note"] = ("优化器输出仅是参考建议，不得绕过指令卡/人工审批"
                                 "（纪律第 1、8 条）")

    md = ["# 组合风险度量报告（L3.2 · 尾部指标 + HRP 参考权重）", "",
          f"- 生成：{datetime.now().strftime('%Y-%m-%d %H:%M')} · scripts/risk_report.py",
          f"- 收益：M2.1 生产同款 runner（含成本），OOS {oos_start} 起",
          "- 纪律：优化器输出仅是参考建议，不得绕过指令卡/人工审批（第 1、8 条）", "",
          "## 单资产尾部指标（OOS 日收益）", "",
          "| 资产 | VaR95 | CVaR95 | 年化波动 | 最大回撤 |",
          "|---|---|---|---|---|"]
    for c, m in report["assets"].items():
        md.append("| %s | %s | %s | %s | %s |" % (
            c, _pct(m["var95"]), _pct(m["cvar95"]),
            _pct(m["annual_vol"]), _pct(m["max_drawdown"])))
    p = report["portfolio"]
    md += ["", "## 等权组合（1/3 × TQQQ/SOXL/UPRO）", "",
           "| 指标 | 值 |", "|---|---|",
           "| VaR95 | {} |".format(_pct(p["var95"])),
           "| **CVaR95（最差 5% 期望损失/日）** | **{}** |".format(_pct(p["cvar95"])),
           "| 年化波动 | {} |".format(_pct(p["annual_vol"])),
           "| 最大回撤 | {} |".format(_pct(p["max_drawdown"])),
           "",
           "## HRP 参考权重（vs 等权 1/3）", "",
           "| 资产 | 等权 | HRP 参考 |", "|---|---|---|"]
    hrp = report["hrp_weights"]
    for c in config.SYMBOLS:
        md.append("| {} | 33.33% | {} |".format(c, _pct(hrp.get(c, 0.0))))
    md += ["",
           "## 与纪律第 9 条对照（极贪降仓 / 极恐分批）", "",
           "- 9.1 极贪 ≥85 → 25% 底仓：组合 CVaR95（{}）量化了".format(_pct(p["cvar95"])),
           "  「若极端场景再现，单日期望损失」——是第 9 条强制降仓的尾部量化依据。",
           "- 9.3 极恐 ≤10 分批释弹药：VaR/CVaR 未覆盖的样本外尾部（黑天鹅）",
           "  恰是分批而非一次性投入的理由（一次投入=把全部弹药暴露在未知尾部）。",
           "- 结论：第 9 条的执行不改；HRP 权重仅作底仓权重优化参考，",
           "  实际调仓仍走指令卡 + C-3 人工审批（第 8 条）。"]
    md_text = "\n".join(md)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "risk-report.md").write_text(md_text, encoding="utf-8")
    print(md_text)
    if args.json:
        (OUT / "risk-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[risk-report] json → evolution/experiments/risk/risk-report.json")
    print("[risk-report] md → evolution/experiments/risk/risk-report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
