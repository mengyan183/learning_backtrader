#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-2 变更提案自动化：变体回测 OOS 结果 → 第 8 条标准提案文档。

流程（evolution-plan.md 第 8 条）：
  1. 跑变体（复用 fg_system/backtest/variants + runner，等价性守卫同 C-1）；
  2. **确定性判定**（无 LLM 判决）：OOS 年化 > B0 且最大回撤 <= B0 ⇒ 提案候选；
     否则 ⇒ 不采纳记录；
  3. 按模板生成标准提案（依据/口径/回测证据/风险/审批位）→ evolution/proposals/。

用法：.venv/bin/python scripts/evolve_propose.py
输出：evolution/proposals/proposal_<date>.md（每变体一份）
"""
import argparse
import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fg_system import config
from fg_system.backtest import runner
from fg_system.backtest import variants as vmod

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROPOSALS = os.path.join(REPO, "evolution", "proposals")
OOS_START = "2024-10-01"
TOL = 5e-5


def write_proposal(sym, vk, spec, m_b0, m_v, out_dir):
    """第 8 条标准提案模板（确定性内容，无 LLM 判决）。"""
    date_s = datetime.now().strftime("%Y-%m-%d")
    adopt = bool(m_v["annual_return"] > m_b0["annual_return"]
                 and m_v["max_drawdown"] >= m_b0["max_drawdown"])
    verdict = "提案候选（OOS 不劣化）" if adopt else "不采纳（OOS 未不劣化）"
    lines = [
        "# 变更提案：%s / %s（%s）" % (sym, vk, date_s), "",
        "## 1. 依据（先验来源，非调参）", "",
        spec["basis"] if "basis" in spec else "（待人工补充先验依据）", "",
        "## 2. 口径", "",
        "- 变体：%s" % spec["label"],
        "- OOS：%s 起（与 baseline meta 同口径，时间序 80/20）" % OOS_START,
        "- 回测：生产同款 runner（commission %.4f / slippage %.5f，config 原值）"
        % (config.COMMISSION, config.SLIPPAGE),
        "- 等价性守卫：B0 与 baseline 年化相对差 < %.0e（逐位相同红线）" % TOL,
        "", "## 3. 回测证据（OOS）", "",
        "| 指标 | B0 基线 | %s 变体 | 变化 |" % vk, "|---|---|---|---|",
        "| OOS 年化 | %.2f%% | %.2f%% | %+.2fpp |"
        % (m_b0["annual_return"] * 100, m_v["annual_return"] * 100,
           (m_v["annual_return"] - m_b0["annual_return"]) * 100),
        "| 最大回撤 | %.1f%% | %.1f%% | %+.1fpp |"
        % (m_b0["max_drawdown"] * 100, m_v["max_drawdown"] * 100,
           (m_v["max_drawdown"] - m_b0["max_drawdown"]) * 100),
        "| Sharpe | %.2f | %.2f |" % (m_b0.get("sharpe", 0), m_v.get("sharpe", 0)),
        "| Calmar | %.2f | %.2f |" % (m_b0.get("calmar", 0), m_v.get("calmar", 0)),
        "", "## 4. 判定（确定性，无 LLM 判决）", "",
        "**%s**" % verdict, "",
        "## 5. 风险", "",
        "- 0.5 折扣类先验值未经参数搜索；若采纳仅作研究观察，不直接动 config（第 8 条流程）。",
        "- OOS 样本自 %s 起，结论待更多 OOS 数据确认（季度 walk-forward 重检）。" % OOS_START,
        "- 变体规则可能错过阻断解除后的快速反弹。", "",
        "## 6. 审批", "",
        "- 人工审批：采纳（动 config.py）/ 观察（纳入 VARIANTS 长期观察）/ 否决（Y/N/Z）？",
    ]
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "proposal_%s_%s_%s.md" % (sym, vk, date_s))
    open(out_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return out_path, adopt


def main():
    ap = argparse.ArgumentParser(description="C-2 变更提案自动化")
    ap.add_argument("--out-dir", default=PROPOSALS)
    args = ap.parse_args()

    features = (pd.read_csv(config.FEATURES_PATH, parse_dates=["date"])
                .set_index("date"))
    pf_path = config.PORTFOLIO_FEATURES_PATH
    pf = pd.read_csv(pf_path, parse_dates=["date"]) if os.path.exists(pf_path) else None
    prices = pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"),
                         parse_dates=["date"])
    base = json.load(open(os.path.join(REPO, "evolution", "baseline.json")))

    ok = True
    for sym in config.SYMBOLS:
        feat = features.copy()
        px = prices[prices["symbol"] == sym].set_index("date")[
            ["open", "high", "low", "close", "volume"]]
        feat = feat.join(px, how="inner")
        rets = {}
        for vk in vmod.VARIANT_KEYS:
            fv = vmod.apply_variant(feat, pf, vk) if pf is not None else feat
            _, r = runner.run_single(fv, sym)
            rets[vk] = r
        # 等价性守卫
        b0_full = runner.performance_metrics(rets[vmod.BASELINE])
        b_ann = base["symbols"][sym]["strategy"]["full"]["annual_return"]
        diff = abs(b0_full["annual_return"] - b_ann) / max(abs(b_ann), 1e-9)
        if diff > TOL:
            print("⚠️ %s B0 守卫失败（相对差 %.2e）" % (sym, diff))
            ok = False
            continue
        for vk in vmod.VARIANT_KEYS[1:]:
            b0_oos = runner.performance_metrics(
                rets[vmod.BASELINE][rets[vmod.BASELINE].index >= pd.Timestamp(OOS_START)])
            v_oos = runner.performance_metrics(
                rets[vk][rets[vk].index >= pd.Timestamp(OOS_START)])
            path, adopt = write_proposal(sym, vk, vmod.VARIANTS[vk], b0_oos, v_oos,
                                         args.out_dir)
            print("  %-5s %-6s OOS %.2f%% vs %.2f%% ⇒ %s → %s"
                  % (sym, vk, b0_oos["annual_return"] * 100,
                     v_oos["annual_return"] * 100, "提案" if adopt else "不采纳", path))

    print("\n%s" % ("✅ 提案文档已生成（evolution/proposals/）" if ok
                    else "⚠️ 有守卫失败，见上；未全部生成"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
