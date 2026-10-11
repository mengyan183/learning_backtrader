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

用法：.venv/bin/python scripts/evolve_walkforward.py [--write] [--decision]
输出：evolution/walkforward-report.md（--write 时生成）
      evolution/walkforward-decision.md（--decision 时生成，含维持/归档建议）
      --decision 同时追加写 docs/decision-log.md（M2.5 季度裁判常态化）
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


def verdict_for(n_total, n_good, min_q=MIN_QUARTERS, ratio=KEEP_RATIO):
    """确定性判定：样本不足 / 维持观察 / 建议归档（无 LLM 判决）。"""
    if n_total < min_q:
        return "样本不足，继续积累"
    if n_good / n_total >= ratio:
        return "维持观察"
    return "建议归档"


def perf(returns):
    return runner.performance_metrics(returns)


def main():
    ap = argparse.ArgumentParser(description="C-5 季度 walk-forward 重标定")
    ap.add_argument("--write", action="store_true", help="生成 walkforward-report.md")
    ap.add_argument("--decision", action="store_true", help="生成建议文件并追加写 decision-log.md（M2.5）")
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
    verdicts = []
    for sym in config.SYMBOLS:
        px = prices[prices["symbol"] == sym].set_index("date")[
            ["open", "high", "low", "close", "volume"]]
        feat = features.join(px, how="inner")
        lines += ["## %s" % sym, "", "| 窗 | B0 年化 | %s 年化 | B0 回撤 | %s 回撤 | 判定 |" % ("变体", "变体"), "|---|---|---|---|---|---|"]
        for vk in vmod.VARIANT_KEYS[1:]:
            n_good = 0
            n_total = 0
            rows = []
            # R-3：`apply_variant` 是纯函数（与窗口无关）⇒ 提到窗口循环外，
            # 原来每个季度窗都重算一遍（窗多时纯浪费）。
            fv = vmod.apply_variant(feat, pf, vk) if pf is not None else feat
            for (a, b) in windows:
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
            verdict = verdict_for(n_total, n_good)
            if verdict == "样本不足，继续积累":
                total["accum"] += 1
            elif verdict == "维持观察":
                total["keep"] += 1
            else:
                total["archive"] += 1
            verdicts.append({"sym": sym, "variant": vk, "verdict": verdict,
                             "n_good": n_good, "n_total": n_total,
                             "n_accum": n_total if n_total < MIN_QUARTERS else 0})
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

    if args.decision:
        write_decision(verdicts, total, date_s)


def write_decision(verdicts, total, date_s):
    """M2.5：生成建议文件 + 追加写 decision-log.md（确定性判定，无 LLM 判决）。

    建议文件供 C-3 归档流程使用；归档/维持由人工按第 8 条流程确认，脚本不改生产。
    """
    q = (datetime.now().month - 1) // 3 + 1
    qlabel = "%dQ%d" % (datetime.now().year, q)
    lines = ["# walk-forward 季度裁判建议（M2.5，%s）" % qlabel, "",
             "> 由 scripts/evolve_walkforward.py --decision 生成 · 确定性判据（无 LLM 判决）",
             "> 判据：>=%.0f%% 季度窗不劣化/等价 ⇒ 维持观察；否则建议归档；窗数<%d ⇒ 样本不足"
             % (KEEP_RATIO * 100, MIN_QUARTERS), "",
             "| 标的 | 变体 | 判定 | 证据（不劣化窗/总窗） |", "|---|---|---|---|"]
    for v in verdicts:
        if v["n_accum"]:
            evidence = "样本不足（%d 窗）" % v["n_total"]
        else:
            evidence = "%d/%d 窗不劣化" % (v["n_good"], v["n_total"])
        lines.append("| %s | %s | %s | %s |" % (v["sym"], v["variant"], v["verdict"], evidence))
    lines += ["", "## 汇总", "",
              "| 判定 | 数量 |", "|---|---|",
              "| 维持观察 | %d |" % total["keep"],
              "| 建议归档 | %d |" % total["archive"],
              "| 样本不足 | %d |" % total["accum"],
              "", "## 说明",
              "- 建议文件**不改任何生产状态**；「建议归档」仅表示从 VARIANTS 长期观察移除的候选，"
              "需人工按第 8 条流程（C-3 审批）确认后执行。",
              "- 完整证据：evolution/walkforward-report.md（%s）" % date_s]
    dec = "\n".join(lines) + "\n"
    dec_out = os.path.join(REPO, "evolution", "walkforward-decision.md")
    open(dec_out, "w", encoding="utf-8").write(dec)
    print("\n✅ 建议文件 → %s" % dec_out)

    # decision-log 追加
    dl = os.path.join(REPO, "docs", "decision-log.md")
    entry = ["",
             "## %s walk-forward 季度裁判（M2.5）" % date_s,
             "",
             "- **判定清单**（确定性判据，无 LLM 判决）：" + 
             "；".join("%s/%s=%s(%s)" % (v["sym"], v["variant"], v["verdict"],
                                          v["n_good"] if not v["n_accum"] else "样本不足")
                       for v in verdicts),
             "- **汇总**：维持 %d / 归档 %d / 样本不足 %d。" % (total["keep"], total["archive"], total["accum"]),
             "- **动作**：不自动改生产；「建议归档」项走 C-3 人工审批（第 8 条流程）；"
             "「维持观察」项继续留 VARIANTS 长期观察。",
             "- **证据**：evolution/walkforward-report.md + walkforward-decision.md（%s）。" % date_s]
    with open(dl, "a", encoding="utf-8") as f:
        f.write("\n".join(entry) + "\n")
    print("\n✅ decision-log.md 已追加（%s）" % qlabel)


if __name__ == "__main__":
    main()
