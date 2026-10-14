#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原油候选因子实检（MT-10，2026-10-14）。

按 docs/notes/2026-10-14-crude-factor-preregistration.md 的**先验固定判据**
执行：C-1 原油 20 日已实现波动 / C-2 油-股 60 日滚动相关 的 IC/IR
（目标 QQQ 未来 5/20 日，主判据；10/40 日参考）+ 与 fed 因子正交性
（|corr|<0.5 一票否决）+ C-3 单日跳涨/跳跌>5% 事件研究。

判定口径（写脚本时固定，不随结果调整）：
- IC/IR 门槛：5/20 日**任一** horizon 同时满足 |IC_mean|>0.03 且 |ICIR|>0.5；
  n≥60；近 120 日 |ICIR| ≥ 全段 |ICIR| × 0.5。
- 正交性：与 features.fed 的 Pearson |corr|<0.5，否则一票否决。
- 事件研究（C-3）：事件后 5/20 日平均收益 > 全样本基线 且 正占比≥60%、
  事件样本 n≥20；跳涨/跳跌分开看。

用法：.venv/bin/python scripts/crude_factor_check.py
输出：结果追加 evolution/factor-screen-results.md（MT-10 段）。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system.factors import eval as feval          # noqa: E402
from fg_system.factors import crude as fcrude        # noqa: E402
from fg_system.md_section import write_section       # noqa: E402

WTI = os.path.join(REPO, "Data", "raw", "fred_DCOILWTICO.csv")
PRICES = os.path.join(REPO, "Data", "raw", "prices.csv")
FEATURES = os.path.join(REPO, "Data", "features.csv")
RESULTS = os.path.join(REPO, "evolution", "factor-screen-results.md")


def load_wti():
    df = pd.read_csv(WTI)
    df["date"] = pd.to_datetime(df["observation_date"])
    return df.set_index("date")["DCOILWTICO"].dropna()


def load_qqq():
    df = pd.read_csv(PRICES)
    df["date"] = pd.to_datetime(df["date"])
    q = df[df["symbol"] == "QQQ"].set_index("date")["close"].dropna()
    return q


def load_fed_score():
    df = pd.read_csv(FEATURES, usecols=["date", "fed"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["fed"].dropna()


def icir_pass(stats):
    """IC/IR 门槛（预登记 §2.1）。stats = feval.icir() 输出或 None。"""
    if stats is None:
        return False
    return (abs(stats["ic_mean"]) > 0.03 and abs(stats["icir"]) > 0.5
            and stats["n"] >= 60)


def recent_decay(eval_result, horizon):
    """近窗衰减：近 120 日 |ICIR| ≥ 全段 |ICIR| × 0.5（无近窗数据则视作通过）。"""
    ws = feval.window_stats(eval_result, horizon, recent=120)
    if not ws["stats"] or not ws["recent_stats"]:
        return True
    full_icir = abs(ws["stats"]["icir"])
    recent_icir = abs(ws["recent_stats"]["icir"])
    return recent_icir >= full_icir * 0.5


def event_study(signal_ret, qqq_close, threshold=0.05, horizons=(5, 20)):
    """C-3 事件研究：油单日 |ret|>5% 事件日 → QQQ 事件后前瞻收益 vs 全样本基线。
    返回 {up: {...}, down: {...}}。"""
    ret = signal_ret.dropna()
    q = qqq_close.dropna()
    common = ret.index.intersection(q.index)
    ret, q = ret.loc[common], q.loc[common]
    events_up = ret[ret > threshold]
    events_down = ret[ret < -threshold]
    out = {}
    for name, ev in (("up", events_up), ("down", events_down)):
        row = {}
        for h in horizons:
            # 前瞻收益（shift(-h)）：仅供研究/评测（事件研究取证），
            # 禁止用于生成仓位 —— 已在 lookahead_audit RESEARCH_WHITELIST 登记。
            fwd = q.shift(-h) / q - 1.0
            ev_fwd = fwd.loc[ev.index].dropna()
            baseline = fwd.dropna()
            row[h] = {
                "n": int(len(ev_fwd)),
                "event_mean": float(ev_fwd.mean()) if len(ev_fwd) else None,
                "baseline_mean": float(baseline.mean()),
                "pos_ratio": float((ev_fwd > 0).mean()) if len(ev_fwd) else None,
                "pass": bool(len(ev_fwd) >= 20 and ev_fwd.mean() > baseline.mean()
                             and (ev_fwd > 0).mean() >= 0.6) if len(ev_fwd) else False,
            }
        out[name] = row
    return out


def main():
    wti = load_wti()
    qqq = load_qqq()
    fed = load_fed_score()

    # 对齐油价 × QQQ（QQQ 短，取其窗口）
    oil_ret = wti.pct_change().dropna()
    qqq_ret = qqq.pct_change().dropna()
    common = oil_ret.index.intersection(qqq_ret.index)
    oil_c = wti.loc[common]
    qqq_c = qqq.loc[common]
    oil_ret_c = oil_ret.loc[common]
    qqq_ret_c = qqq_ret.loc[common]

    # ---- C-1 原油 20 日已实现波动 ----
    sig_c1 = fcrude.crude_vol(oil_c, window=20).dropna()
    ev_c1 = feval.evaluate(sig_c1, qqq_c, horizons=(5, 10, 20, 40))
    # ---- C-2 油-股 60 日滚动相关 ----
    sig_c2 = fcrude.crude_equity_corr(oil_c, qqq_c, window=60).dropna()
    ev_c2 = feval.evaluate(sig_c2, qqq_c, horizons=(5, 10, 20, 40))

    # ---- 正交性（与 features.fed）----
    def ortho(sig):
        s = sig.dropna()
        common_f = s.index.intersection(fed.index)
        if len(common_f) < 30:
            return {"n": int(len(common_f)), "corr": None, "pass": None}
        c = float(np.corrcoef(s.loc[common_f], fed.loc[common_f])[0, 1])
        return {"n": int(len(common_f)), "corr": round(c, 4),
                "pass": abs(c) < 0.5}

    ortho_c1, ortho_c2 = ortho(sig_c1), ortho(sig_c2)

    # ---- C-3 事件研究 ----
    ev3 = event_study(oil_ret_c, qqq_c)

    # ---- 汇总判定 ----
    def summarize(name, ev, orth):
        rows = {}
        for h in (5, 20, 10, 40):
            st = ev[h]["stats"]
            rows[h] = (None if st is None else {
                "ic_mean": round(st["ic_mean"], 4),
                "icir": round(st["icir"], 4),
                "n": st["n"],
                "pos_ratio": round(st["ic_positive_ratio"], 3),
            })
        ic_pass = any(icir_pass(ev[h]["stats"]) for h in (5, 20))
        decay = all(recent_decay(ev, h) for h in (5, 20))
        return {
            "name": name, "ic": rows,
            "ic_ir_pass": ic_pass, "recent_decay_pass": decay,
            "ortho": orth,
            "verdict": ("通过" if (ic_pass and decay and orth["pass"])
                        else "未通过"),
            "blocks": [b for b, v in (
                ("IC/IR", ic_pass), ("近窗衰减", decay),
                ("正交性", orth["pass"])) if not v],
        }

    r1 = summarize("C-1 原油20日波动", ev_c1, ortho_c1)
    r2 = summarize("C-2 油股60日相关", ev_c2, ortho_c2)

    # ---- 输出报告 ----
    lines = [
        "",
        "---",
        "",
        "## MT-10 原油候选因子实检（2026-10-14）",
        "",
        "按 `docs/notes/2026-10-14-crude-factor-preregistration.md` 先验固定判据执行。",
        "目标 = QQQ 未来收益；IC = Spearman 滚动 60；门槛 |IC|>0.03 且 |ICIR|>0.5、n≥60、",
        "近120日|ICIR|≥全段×0.5；正交性：与 features.fed |corr|<0.5 一票否决。",
        "",
        "数据：DCOILWTICO 9517 观测（1986-至今）+ QQQ close（prices.csv），对齐后 %d 个共同交易日。" % len(common),
        "",
        "### C-1 原油 20 日已实现波动（风险溢价通道）",
        "",
        "| horizon | IC_mean | ICIR | n | 正占比 | 通过 |",
        "|---|---|---|---|---|---|",
    ]
    for h in (5, 20, 10, 40):
        v = r1["ic"][h]
        if v is None:
            lines.append("| %d | 样本不足 | - | - | - | ✗ |" % h)
        else:
            ok = abs(v["ic_mean"]) > 0.03 and abs(v["icir"]) > 0.5
            lines.append("| %d | %.4f | %.4f | %d | %.3f | %s |" % (
                h, v["ic_mean"], v["icir"], v["n"], v["pos_ratio"],
                "✓" if ok else "✗"))
    lines += [
        "",
        "正交性（vs fed）：corr=%.4f（n=%d）%s" % (
            ortho_c1["corr"] or 0, ortho_c1["n"],
            "⇒ 通过" if ortho_c1["pass"] else "⇒ 一票否决"),
        "近窗衰减：%s" % ("通过" if r1["recent_decay_pass"] else "未通过"),
        "",
        "**C-1 判定：%s**（%s）" % (
            r1["verdict"], "；".join(r1["blocks"]) if r1["blocks"] else "达标"),
        "",
        "### C-2 油-股 60 日滚动相关（机制切换探测）",
        "",
        "| horizon | IC_mean | ICIR | n | 正占比 | 通过 |",
        "|---|---|---|---|---|---|",
    ]
    for h in (5, 20, 10, 40):
        v = r2["ic"][h]
        if v is None:
            lines.append("| %d | 样本不足 | - | - | - | ✗ |" % h)
        else:
            ok = abs(v["ic_mean"]) > 0.03 and abs(v["icir"]) > 0.5
            lines.append("| %d | %.4f | %.4f | %d | %.3f | %s |" % (
                h, v["ic_mean"], v["icir"], v["n"], v["pos_ratio"],
                "✓" if ok else "✗"))
    lines += [
        "",
        "正交性（vs fed）：corr=%.4f（n=%d）%s" % (
            ortho_c2["corr"] or 0, ortho_c2["n"],
            "⇒ 通过" if ortho_c2["pass"] else "⇒ 一票否决"),
        "近窗衰减：%s" % ("通过" if r2["recent_decay_pass"] else "未通过"),
        "",
        "**C-2 判定：%s**（%s）" % (
            r2["verdict"], "；".join(r2["blocks"]) if r2["blocks"] else "达标"),
        "",
        "### C-3 单日跳涨/跳跌 >5% 事件研究（冲击通道）",
        "",
        "判据：事件后平均收益 > 全样本基线 且 正占比 ≥60%、n≥20。",
        "",
        "| 事件 | horizon | n | 事件均值 | 全样本基线 | 正占比 | 通过 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, zh in (("跳涨(+)", "up"), ("跳跌(-)", "down")):
        for h in (5, 20):
            v = ev3[zh][h]
            lines.append("| %s | %d | %d | %.4f | %.4f | %.3f | %s |" % (
                name, h, v["n"], v["event_mean"], v["baseline_mean"],
                v["pos_ratio"], "✓" if v["pass"] else "✗"))
    lines += [
        "",
        "### 结论",
        "",
    ]
    if r1["verdict"] == "通过" or r2["verdict"] == "通过":
        lines.append(
            "任一候选通过 ⇒ **仅登记为研究参考，不进合成权重**；"
            "进权重须变体回测 → OOS 终验 → 人工审批（trading-discipline 第 8 条）。")
    else:
        lines.append("两个候选均未通过门槛 ⇒ 不登记 factors.md，持续积累样本。")
    lines.append("")

    report = "\n".join(lines)

    # 幂等写入：同一标题重复运行不产生重复段（替换旧段）
    write_section(RESULTS, report, "## MT-10 原油候选因子实检（2026-10-14）")

    print(report)
    print("已追加:", RESULTS)
    # JSON 摘要供自动化
    print(json.dumps({
        "c1": {"verdict": r1["verdict"], "ortho_corr": ortho_c1["corr"]},
        "c2": {"verdict": r2["verdict"], "ortho_corr": ortho_c2["corr"]},
        "c3": {"up5": ev3["up"][5], "up20": ev3["up"][20],
               "down5": ev3["down"][5], "down20": ev3["down"][20]},
        "common_days": int(len(common)),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
