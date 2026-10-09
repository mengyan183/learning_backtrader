#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-5 季度 walk-forward 重标定：滚动验证窗下 B0 vs 变体（如 V-H7）的绩效对比。

用途：
  - V-H7 长期观察的季度重检裁判（variants 层）；
  - C-11 假说/因子衰减重检的通用机制（adopted 假说 → 变体 → 滚动窗对比）。

方法：
  1. 以季度为 OOS 验证窗，逐季滚动：该窗数据为 OOS，之前数据为 IS（仅用于
     确定百分位等状态，回测本身在窗内跑——本脚本复用生产 runner，不改参数）；
  2. 对 B0 与每个变体分别在各季度窗回测 → 计算窗内年化/最大回撤；
  3. 确定性判定（无 LLM 判决）：
       - 多数季度窗（>= 60%）OOS 年化 > B0 且回撤 <= B0 → 变体"维持观察"；
       - 否则 → "建议归档"（保留记录，退出 VARIANTS 长期观察）；
       - 数据不足（窗数 < 3）→ "样本不足，继续积累"。

红线：只读 baseline.json / Data/*（无前视）；不修改 config.py；OOS 禁调参（本脚本无任何调参逻辑）。

用法：.venv/bin/python scripts/evolve_walkforward.py [--write]
输出：evolution/walkforward-report.md（--write 时生成）
"""
import argparse
import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fg_system import config
from fg_system.backtest import runner
from fg_system.backtest import variants as vmod

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "evolution", "walkforward-report.md")
MIN_QUARTERS = 3      # 少于 3 个季度窗 → 样本不足
KEEP_RATIO = 0.6      # >=60% 窗不劣化/等价 → 维持观察
EQ_ANN = 0.005        # 年化 ±0.5pp 内视为等价
EQ_DD = 0.01          # 回撤 ±1pp 内视为等价


def quarter_windows(features):
    """按季度生成滚动验证窗（每窗 3 个月，窗与窗不重叠）。"""
    dates = features.index
    start = dates.min()
    end = dates.max()
    windows = []
    cur = pd.Timestamp(start)
    q = pd.Timestamp(year=cur.year, month=1, day=1)
    while q < end:
        w_end = q + pd.DateOffset(months=3) - pd.Timedelta(days=1)
        if w_end > end:
            w_end = end
        if q > start:
            windows.append((q, w_end))
        q = q + pd.DateOffset(months=3)
    return windows


def perf(returns):
    return runner.performance_metrics(returns)


def main():
    ap = argparse.ArgumentParser(description="C-5 季度 walk-forward 重标定")
    ap.add_argument("--write", action="store_true", help="生成 walkforward-report.md")
    args = ap.parse_args()

    features = pd.read_csv(config.FEATURES_PATH, parse_dates=["date"]).set_index("date")
    pf_path = config.PORTFOLIO_FEATURES_PATH
    pf = pd.read_csv(pf_path, parse_dates=["date"]) if os.path.exists(pf_path) else None
    prices = pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"), parse_dates=["date"])

    windows = quarter_windows(features)
    date_s = datetime.now().strftime("%Y-%m-%d")

    lines = ["# walk-forward 重标定报告（C-5，%s）" % date_s, "",
             "> 由 scripts/evolve_walkforward.py 生成 · 确定性判据（无 LLM 判决）",
             "> 判据：>=%.0f%% 季度窗「不劣化/等价」⇒ 维持观察；否则建议归档；窗数<%d ⇒ 样本不足" % (KEEP_RATIO * 100, MIN_QUARTERS),
             "> 等价口径：年化差 < ±%.2fpp 且回撤差 < ±%.1fpp 视为等价（不拖累判定）" % (EQ_ANN * 100, EQ_DD * 100),
             "", "## 季度验证窗", ""]
    for i, (a, b) in enumerate(windows, 1):
        lines.append("%d. %s ~ %s" % (i, a.date(), b.date()))
    lines.append("")

    total = {"keep": 0, "archive": 0, "accum": 0}
    for sym in config.SYMBOLS:
        px = prices[prices["symbol"] == sym].set_index("date")[
            ["open", "high", "low", "close", "volume"]]
        feat = features.join(px, how="inner")
        lines += ["## %s" % sym, "", "| 窗 | B0 年化 | %s 年化 | B0 回撤 | %s 回撤 | 判定 |" % ("变体", "变体"), "|---|---|---|---|---|---|"]
        for vk in vmod.VARIANT_KEYS[1:]:
            n_good = 0
            n_total = 0
            rows = []
            for (a, b) in windows:
                fv = vmod.apply_variant(feat, pf, vk) if pf is not None else feat
                window = fv.loc[a:b]
                if len(window) < 30:
                    continue
                _, rets = runner.run_single(window, sym)
                m = perf(rets)
                _, rets0 = runner.run_single(feat.loc[a:b], sym)
                m0 = perf(rets0)
                n_total += 1
                d_ann = m["annual_return"] - m0["annual_return"]
                d_dd = m["max_drawdown"] - m0["max_drawdown"]
                if (d_ann > -EQ_ANN and d_dd >= -EQ_DD):
                    good = True   # 不劣化或等价
                    tag = "不劣化/等价"
                else:
                    good = False
                    tag = "劣化"
                if good:
                    n_good += 1
                rows.append("%s ~ %s | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %s"
                            % (a.date(), b.date(), m0["annual_return"] * 100,
                               m["annual_return"] * 100, m0["max_drawdown"] * 100,
                               m["max_drawdown"] * 100, tag))
            if n_total < MIN_QUARTERS:
                verdict = "样本不足，继续积累"
                total["accum"] += 1
            elif n_good / n_total >= KEEP_RATIO:
                verdict = "维持观察"
                total["keep"] += 1
            else:
                verdict = "建议归档"
                total["archive"] += 1
            lines += ["### %s" % vk] + rows
            lines.append("| **合计** | | | | | **%d/%d 窗不劣化 ⇒ %s** |" % (n_good, n_total, verdict))
        lines.append("")

    lines += ["## 汇总", "",
              "| 判定 | 数量 |", "|---|---|",
              "| 维持观察 | %d |" % total["keep"],
              "| 建议归档 | %d |" % total["archive"],
              "| 样本不足 | %d |" % total["accum"]]
    lines += ["",
              "## 说明",
              "- 本报告只做重标定裁判，不自动改任何生产状态；归档/维持由人工按第 8 条流程确认。",
              "- V-H7 若多数窗劣化，则在下次 C-3 审批时从 VARIANTS 长期观察名单移除。",
              "- OOS 禁调参：脚本无任何参数搜索/调优逻辑。"]

    report = "\n".join(lines) + "\n"
    print(report)
    if args.write:
        open(OUT, "w", encoding="utf-8").write(report)
        print("\n✅ 报告 → %s" % OUT)
    else:
        print("\n(dry-run，加 --write 生成文件)")


if __name__ == "__main__":
    main()
