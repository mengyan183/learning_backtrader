#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-1 变体实验设施：adopted 假说 → 变体回测 → OOS 对比 → 变更提案草稿。

编排（evolution-plan.md 第 ⑤ 步）：
  1. 读 features + portfolio_features + prices；
  2. 对每标的 × 每变体（B0 + V-H7）跑 `runner.run_single`（生产同款回测）；
  3. **等价性自查**：B0 输出 vs baseline.json 全区间 annual_return，相对差
     必须 < 1e-6（默认参数逐位相同红线；防 feed/浮点漂移）；
  4. OOS 对比（OOS = 2024-10-01 起，与 baseline meta 同口径）：
     变体 OOS 年化 > B0 且最大回撤 ≤ B0 ⇒ 提案候选；否则如实记录不采纳；
  5. 产出变更提案草稿（第 8 条流程格式）→ evolution/experiments/。

用法：.venv/bin/python scripts/evolve_variant.py [--out-dir evolution/experiments]
"""
import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fg_system import config
from fg_system.backtest import runner
from fg_system.backtest import variants as vmod

OOS_START = "2024-10-01"   # 与 baseline meta.is_oos 同口径（时间序 80/20）
TOL = 5e-5                 # baseline.json 存 round-4 值 ⇒ 容差取 half-ulp 量级


def metrics(returns, full=False):
    """复用 baseline 的绩效口径（runner.performance_metrics）。"""
    if returns is None or len(returns) < 2:
        return None
    return runner.performance_metrics(returns)


def main():
    ap = argparse.ArgumentParser(description="C-1 变体实验")
    ap.add_argument("--out-dir", default=os.path.join("evolution", "experiments"))
    args = ap.parse_args()

    features = (pd.read_csv(config.FEATURES_PATH, parse_dates=["date"])
                .set_index("date"))
    pf_path = config.PORTFOLIO_FEATURES_PATH
    pf = pd.read_csv(pf_path, parse_dates=["date"]) if os.path.exists(pf_path) else None
    prices = pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"),
                         parse_dates=["date"])

    base = json.load(open(os.path.join("evolution", "baseline.json")))
    results = {}
    guard_fail = []

    for sym in config.SYMBOLS:
        # 与 baseline（evolve_baseline.build_symbol）逐位一致：
        # features inner join 价格列，**不 dropna**（warmup 段 target NaN 保留，
        # 其行为由 feed/strategy 与 baseline 相同处理）。
        feat = features.copy()
        px = prices[prices["symbol"] == sym].set_index("date")[
            ["open", "high", "low", "close", "volume"]]
        feat = feat.join(px, how="inner")

        results[sym] = {}
        for vk in vmod.VARIANT_KEYS:
            fv = vmod.apply_variant(feat, pf, vk) if pf is not None else feat
            _, ret = runner.run_single(fv, sym)
            results[sym][vk] = ret

        # 等价性自查：B0 vs baseline
        b0_ann = metrics(results[sym][vmod.BASELINE])["annual_return"]
        base_ann = base["symbols"][sym]["strategy"]["full"]["annual_return"]
        diff = abs(b0_ann - base_ann) / max(abs(base_ann), 1e-9)
        if diff > TOL:
            guard_fail.append((sym, b0_ann, base_ann, diff))
        print("  %-5s B0 年化 %.4f vs baseline %.4f（相对差 %.2e%s）"
              % (sym, b0_ann, base_ann, diff,
                 "" if diff <= TOL else " ⚠️ 守卫失败"))

    # OOS 对比 + 提案草稿
    os.makedirs(args.out_dir, exist_ok=True)
    proposals = []
    for sym in config.SYMBOLS:
        b0 = results[sym][vmod.BASELINE]
        for vk in vmod.VARIANT_KEYS[1:]:
            vr = results[sym][vk]
            if vr is None or len(vr) == 0:
                continue
            oos_mask = (vr.index >= pd.Timestamp(OOS_START))
            b0_oos = b0[b0.index >= pd.Timestamp(OOS_START)]
            m_b0 = metrics(b0_oos)
            m_v = metrics(vr[oos_mask])
            if m_b0 is None or m_v is None:
                continue
            better = (m_v["annual_return"] > m_b0["annual_return"]
                      and m_v["max_drawdown"] >= m_b0["max_drawdown"])
            row = {"symbol": sym, "variant": vk, "label": vmod.VARIANTS[vk]["label"],
                   "b0_oos_annual": m_b0["annual_return"],
                   "b0_oos_dd": m_b0["max_drawdown"],
                   "v_oos_annual": m_v["annual_return"],
                   "v_oos_dd": m_v["max_drawdown"],
                   "better": bool(better)}
            results.setdefault("_oos", []).append(row)
            proposals.append(row)
            print("  %-5s %-6s OOS 年化 B0 %.2f%% vs %s %.2f%%；回撤 B0 %.1f%% vs %.1f%% ⇒ %s"
                  % (sym, vk, m_b0["annual_return"] * 100, vk,
                     m_v["annual_return"] * 100,
                     m_b0["max_drawdown"] * 100, m_v["max_drawdown"] * 100,
                     "提案候选" if better else "不采纳"))

    # 提案草稿（第 8 条流程格式：依据/口径/回测证据/风险）
    date_s = datetime.now().strftime("%Y-%m-%d")
    lines = ["# 变更提案草稿（C-1 变体实验）", "",
             "生成时间：%s" % date_s, "",
             "依据：H-007（adopted）—— trend_blocked_us=True 组最大回撤",
             "  -37.37% > 未阻断组 -34.24%（1760 日，2026-10-08 验证）。",
             "变体：V-H7 = 趋势阻断日 target_position × 0.5（先验固定折扣，非调参）。",
             "口径：OOS = %s 起（与 baseline meta 同口径）；回测 = 生产同款 runner；" % OOS_START,
             "commission %.4f / slippage %.5f（config 原值）。" % (config.COMMISSION, config.SLIPPAGE),
             "", "## OOS 对比", "",
             "| 标的 | 变体 | B0 年化 | 变体年化 | B0 回撤 | 变体回撤 | 采纳? |",
             "|---|---|---|---|---|---|---|"]
    for p in proposals:
        lines.append("| %s | %s | %.2f%% | %.2f%% | %.1f%% | %.1f%% | %s |"
                     % (p["symbol"], p["variant"], p["b0_oos_annual"] * 100,
                        p["v_oos_annual"] * 100, p["b0_oos_dd"] * 100,
                        p["v_oos_dd"] * 100, "是" if p["better"] else "否"))
    lines += ["", "## 风险",
              "- 0.5 折扣为先验固定值，未经参数搜索；若采纳，仅作为研究观察，",
              "  不直接动 config（第 8 条：先改文档 → 再改代码 → 再回测）。",
              "- OOS 样本较短（自 %s），结论待更多 OOS 数据确认。" % OOS_START,
              "- 阻断日 = 趋势过滤未开仓日；降仓后可能错过阻断解除后的快速反弹。",
              "", "## 裁决",
              "- 人工审批：是否将 V-H7 纳入 VARIANTS 长期观察 / 升级为提案（Y/N）？"]
    out_path = os.path.join(args.out_dir, "variant_h007_%s.md" % date_s)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n✅ 提案草稿 → %s" % out_path)

    if guard_fail:
        print("\n⚠️ 等价性守卫失败（%d 项）：%s" % (len(guard_fail), guard_fail))
        sys.exit(1)
    print("✅ 等价性守卫通过（B0 与 baseline 一致）")


if __name__ == "__main__":
    main()
