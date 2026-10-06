#!/usr/bin/env python3
"""数学模型分析报告（2026-10-06 落地 4 个模型）。

运行：.venv/bin/python scripts/model_report.py [--out Data/model_report_YYYY-MM-DD.json]
输出：markdown 摘要（stdout）+ JSON（Data/model_report_*.json）供看板/简报引用。

模型（fg_system/models/，纯 numpy/pandas 零新依赖）：
- markov.py        档位转移矩阵 + 稳态 + 惯性 + 前瞻分布
- hmm.py           Gaussian HMM（EM+Viterbi）：当前市场 regime
- evt.py           极值理论 GPD/POT：极恐/极贪边界阈值校准
- bayes_update.py  Beta-Bernoulli：verifying 假说的观察计数 → 后验信心

纪律：只读历史数据输出分析，不改策略参数，不替代人工审批。
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DATA = REPO / "Data"

ZONE_NAMES = {0: "极度恐惧", 1: "恐惧", 2: "中性", 3: "贪婪", 4: "极度贪婪"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="JSON 输出路径（默认 Data/model_report_<今日>.json）")
    args = ap.parse_args()

    import pandas as pd
    from fg_system.models import markov, hmm, evt, bayes_update

    f = pd.read_csv(DATA / "features.csv", parse_dates=["date"])
    valid = f.dropna(subset=["fg_index", "zone"]).copy()

    report = {"generated": dt.datetime.now().isoformat(timespec="seconds"),
              "data": {"n": int(len(valid)),
                       "range": [str(valid["date"].min().date()),
                                 str(valid["date"].max().date())]},
              "models": {}}

    # ---- 1) 马尔可夫档位转移 ----
    try:
        zones = valid["zone"].astype(int).to_numpy()
        cur_zone = int(zones[-1])
        mk = markov.analyze(zones, start_zone=cur_zone)
        report["models"]["markov"] = mk
    except Exception as e:
        report["models"]["markov"] = {"error": str(e)}

    # ---- 2) HMM regime ----
    try:
        hm = hmm.analyze(DATA, K=3)
        report["models"]["hmm"] = hm
    except Exception as e:
        report["models"]["hmm"] = {"error": str(e)}

    # ---- 3) EVT 阈值校准 ----
    try:
        report["models"]["evt"] = evt.analyze(DATA / "features.csv")
    except Exception as e:
        report["models"]["evt"] = {"error": str(e)}

    # ---- 4) 贝叶斯假说信心 ----
    try:
        counts = bayes_update.parse_hypothesis_counts(REPO / "evolution" / "hypotheses.md")
        bx = {}
        for hid, c in list(counts.items())[:10]:
            bx[hid] = {"counts": c, "posterior": bayes_update.update(c["successes"], c["trials"])}
        report["models"]["bayes"] = bx
    except Exception as e:
        report["models"]["bayes"] = {"error": str(e)}

    # ---- markdown 摘要 ----
    print(_to_markdown(report, cur_zone))

    out_path = args.out or DATA / f"model_report_{dt.date.today().isoformat()}.json"
    out_path = Path(out_path)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[model] JSON 已写入: {out_path}")


def _to_markdown(r, cur_zone):
    L = ["# 贪恐系统数学模型分析", "",
         f"- 数据：{r['data']['n']} 个交易日（{r['data']['range'][0]} ~ {r['data']['range'][1]}）",
         f"- 生成：{r['generated']}", ""]
    mk = r["models"].get("markov") or {}
    if mk.get("matrix"):
        L += ["## 1. 档位转移马尔可夫矩阵", ""]
        L += ["| 从\\到 | 极恐 | 恐惧 | 中性 | 贪婪 | 极贪 |", "|---|---|---|---|---|---|"]
        for i in range(5):
            row = [f"{ZONE_NAMES[i]}"] + [f"{mk['matrix'][i][j]*100:.0f}%" for j in range(5)]
            L.append("| " + " | ".join(row) + " |")
        L += ["", f"- 档位惯性（自转移均值）：**{mk.get('persistence', 0)*100:.0f}%**"
              "（越接近 100% 状态越粘滞）"]
        if mk.get("steady_state"):
            ss = mk["steady_state"]
            top = max(range(5), key=lambda i: ss[i])
            L.append(f"- 长期稳态最可能档位：**{ZONE_NAMES[top]}**（{ss[top]*100:.0f}%）")
        if mk.get("horizons"):
            L.append(f"- 当前档位 {ZONE_NAMES[cur_zone]}：未来 5 日最可能 → "
                     f"{ZONE_NAMES[mk['horizons'][5]['most_likely']]}"
                     f"（{mk['horizons'][5]['prob']*100:.0f}%）")
        L += [""]
    hm = r["models"].get("hmm") or {}
    if hm.get("current_regime"):
        L += ["## 2. HMM 市场 regime（Gaussian HMM, K=3）", ""]
        L += [f"- **当前 regime：{hm['current_regime']}**（Viterbi 解码）"]
        for k, d in (hm.get("regime_desc") or {}).items():
            L.append(f"- regime {d['label']}：{d['n_days']} 天，fg 均值 {d['fg_mean']} ± {d['fg_std']}")
        L += [""]
    ev = r["models"].get("evt") or {}
    lo, up = ev.get("lower") or {}, ev.get("upper") or {}
    if lo.get("levels"):
        L += ["## 3. EVT 极端阈值校准（GPD/POT）", ""]
        L += [f"- 极恐：现状边界 **{lo['current_boundary']}** → 数据建议 **{lo['suggested_boundary']}**"
              f"（1 年重现 {lo['levels'][1]}，5 年 {lo['levels'][5]}，20 年 {lo['levels'][20]}）→ {lo['verdict']}"]
    if up.get("levels"):
        L += [f"- 极贪：现状边界 **{up['current_boundary']}** → 数据建议 **{up['suggested_boundary']}**"
              f"（1 年重现 {up['levels'][1]}，5 年 {up['levels'][5]}，20 年 {up['levels'][20]}）→ {up['verdict']}"]
        L += [""]
    bx = r["models"].get("bayes") or {}
    if bx and not bx.get("error"):
        L += ["## 4. 假说贝叶斯信心（Beta-Bernoulli，观察计数→后验）", ""]
        for hid, item in list(bx.items())[:10]:
            p = item["posterior"]
            L.append(f"- {hid}：{item['counts']['successes']}/{item['counts']['trials']} "
                     f"→ 后验均值 {p['posterior_mean']:.2f}，95%CI "
                     f"[{p['ci95'][0]:.2f}, {p['ci95'][1]:.2f}]")
        L += ["", "> 信心仅供人工参考；判决权在数据裁判+人工审批（LLM 永不判决）。"]
    L += ["", "---", "> 由 scripts/model_report.py 自动生成 · 只读分析，未改动任何策略参数"]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
