#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1.4 归一化/档位对照实验（qjr1997/CNN 思想）。

对照三方案，用 OOS 组合收益裁判「固定边界是否跨 regime 失效」：
  A) 现状：生产 fg_index（756 日滚动百分位因子分 → 加权合成）+ 固定 ZONE_EDGES=[20,40,60,80]
  B) 252 日 z-score 截断标准化（qjr1997 式）：六因子分滚动 z-score，截断 ±2σ → 0-100 → 同权重合成 → 固定边界
  C) 动态档位（CNN 式「当前值 vs 自身历史」）：fg_index 252 日滚动百分位定档

口径说明（不改变生产）：
  - 因子分已含 756 日百分位信息；方案 B 的 z-score 作用于「因子分」而非原始信号
    （features.csv 无原始值），属对照近似，结论只用于决策依据。
  - 生产 ZONE_EDGES / 归一化 **不得直接改**；若某方案显著占优，走第 8 条纪律流程。

输出：evolution/experiments/norm_compare/norm-compare.{md,json}
用法：.venv/bin/python scripts/norm_compare.py [--json]
"""
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from fg_system import config
from fg_system import index as fidx
from fg_system import pipeline
from fg_system.backtest import runner

OUT_DIR = os.path.join(BASE, "evolution", "experiments", "norm_compare")
FEATURES = os.path.join(BASE, "Data", "features.csv")
PRICES = os.path.join(BASE, "Data", "raw", "prices.csv")
OOS_START = "2024-10-03"
FACTOR_COLS = ["vix", "term", "price", "breadth", "fed", "putcall"]
SYMBOLS = ["TQQQ", "SOXL", "UPRO"]


def plan_a_zone(features):
    """A 现状：生产 fg_index + 固定边界定档（index=date）。"""
    f = features.set_index("date") if "date" in features.columns else features
    z = f["fg_index"].map(fidx.factor_zone)
    return z


def plan_b_zone(features, window=252, cap=2.0):
    """B 方案：六因子 252 日 z-score 截断 ±2σ → 0-100 → 同权重合成 → 固定边界。

    返回 (档位 Series, 合成指数 Series)。
    """
    f = features.set_index("date") if "date" in features.columns else features
    scores = f[FACTOR_COLS]
    mu = scores.rolling(window, min_periods=60).mean()
    sd = scores.rolling(window, min_periods=60).std()
    z = (scores - mu) / sd.replace(0.0, np.nan)
    zc = z.clip(-cap, cap)
    resc = (zc + cap) / (2 * cap) * 100.0
    idx = fidx.combine(resc, factors=[type("F", (), {"name": c})()
                                      for c in FACTOR_COLS])
    idx = idx.clip(0, 100)
    return idx.map(fidx.factor_zone), idx


def plan_c_zone(features, window=252):
    """C 方案：fg_index 252 日滚动百分位定档（动态边界 = 自身历史分布）。"""
    f = features.set_index("date") if "date" in features.columns else features
    pct = f["fg_index"].rolling(window, min_periods=60).rank(pct=True) * 100.0
    # 分位 20/40/60/80 → 档位（与 ZONE_EDGES 同构）
    return pct.map(fidx.factor_zone)


def combo_oos_returns(features, prices):
    """M2.1 同口径组合 OOS 日收益（生产 runner.run_single，构造性一致 Σ w·leg）。"""
    n = len(SYMBOLS)
    w = 1.0 / n
    legs = {}
    for sym in SYMBOLS:
        px = prices[prices["symbol"] == sym].set_index("date").sort_index()
        f = features.copy()
        if "date" in f.columns:
            f = f.set_index("date")
        f = f.join(px[["open", "high", "low", "close", "volume"]], how="inner")
        _, ret = runner.run_single(f, sym)
        legs[sym] = ret
    idx = legs[SYMBOLS[0]].index
    comb = sum(w * legs[s].reindex(idx).fillna(0.0) for s in SYMBOLS)
    return comb[comb.index >= OOS_START].dropna()


def _spearman(a, b):
    a = pd.Series(a).reset_index(drop=True)
    b = pd.Series(b).reset_index(drop=True)
    return a.rank().corr(b.rank(), method="pearson")


def _dist(z):
    vc = z.value_counts().reindex(range(5), fill_value=0)
    return {int(k): int(v) for k, v in vc.items()}


def _mean_streak(z):
    """平均档位驻留（连续同档天数）。"""
    streaks, cur, cnt = [], None, 0
    for v in z.dropna():
        if v == cur:
            cnt += 1
        else:
            if cur is not None:
                streaks.append(cnt)
            cur, cnt = v, 1
    if cur is not None:
        streaks.append(cnt)
    return float(np.mean(streaks)) if streaks else 0.0


def _autocorr(z):
    s = z.dropna().astype(float)
    if len(s) < 3:
        return None
    return float(s.autocorr(lag=1))


def _analyze(zones, ret):
    """档位 vs 次日组合收益（OOS 对齐）。"""
    z = zones.reindex(ret.index).dropna()
    df = pd.DataFrame({"zone": z, "ret": ret.reindex(z.index)})
    df = df.dropna()
    if len(df) < 20:
        return None
    # 次日收益：T 日档位 vs T+1 收益
    fwd = df["ret"].shift(-1)
    pair = pd.DataFrame({"zone": df["zone"], "fwd": fwd}).dropna()
    ic = _spearman(pair["zone"], pair["fwd"])
    ic_pearson = pair["zone"].corr(pair["fwd"], method="pearson")
    by_zone = pair.groupby("zone")["fwd"].agg(["mean", "count"])
    # 极端档位后 1/5 日累计（纪律第 9 条相关证据）
    extreme = {}
    for zz in (0, 4):
        mask = pair["zone"] == zz
        if mask.sum() < 2:
            extreme[zz] = None
            continue
        sub = pair.loc[mask]
        extreme[zz] = {"n": int(mask.sum()),
                       "next1_mean": float(sub["fwd"].mean()),
                       "next5_geo": float(np.exp(np.log1p(sub["fwd"]).sum()) - 1)
                       if (sub["fwd"] > -1).all() else None}
    out = {
        "n": int(len(pair)),
        "ic_spearman": None if ic is None or ic != ic else round(float(ic), 4),
        "ic_pearson": None if ic_pearson != ic_pearson else round(float(ic_pearson), 4),
        "by_zone": {int(k): {"mean_next": None if v["mean"] != v["mean"] else round(float(v["mean"]), 5),
                             "n": int(v["count"])} for k, v in by_zone.iterrows()},
        "extreme": {str(k): v for k, v in extreme.items()},
    }
    return out


def main():
    features = pd.read_csv(FEATURES)
    features["date"] = pd.to_datetime(features["date"])
    prices = pd.read_csv(PRICES)
    prices["date"] = pd.to_datetime(prices["date"])
    zA = plan_a_zone(features)
    zB, idxB = plan_b_zone(features)
    zC = plan_c_zone(features)
    ret = combo_oos_returns(features, prices)

    res = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "oos_start": OOS_START,
        "sample": {"n_rows": int(len(features)),
                   "date_from": str(features["date"].iloc[0]),
                   "date_to": str(features["date"].iloc[-1])},
        "plans": {
            "A": {"desc": "生产：756日滚动百分位因子分 → 加权合成 → 固定 ZONE_EDGES [20,40,60,80]",
                  "dist": _dist(zA), "mean_streak": _mean_streak(zA),
                  "autocorr1": _autocorr(zA),
                  "oos": _analyze(zA, ret)},
            "B": {"desc": "252日 z-score 截断 ±2σ → 0-100 → 同权重合成 → 固定边界（qjr1997 式对照近似）",
                  "dist": _dist(zB), "mean_streak": _mean_streak(zB),
                  "autocorr1": _autocorr(zB),
                  "oos": _analyze(zB, ret)},
            "C": {"desc": "动态档位：fg_index 252日滚动百分位定档（CNN 式当前值 vs 自身历史）",
                  "dist": _dist(zC), "mean_streak": _mean_streak(zC),
                  "autocorr1": _autocorr(zC),
                  "oos": _analyze(zC, ret)},
        },
        "regime_shift": _regime_shift(zA, zC),
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "norm-compare.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    md = render_md(res)
    with open(os.path.join(OUT_DIR, "norm-compare.md"), "w", encoding="utf-8") as f:
        f.write(md)
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(md)
    return res


def _regime_shift(zA, zC):
    """A vs C 档位偏移统计（动态档位相对固定边界偏移了几档）。"""
    df = pd.DataFrame({"A": zA, "C": zC}).dropna()
    diff = (df["C"] - df["A"]).astype(int)
    vc = diff.value_counts().sort_index()
    return {"n": int(len(df)),
            "shift_dist": {int(k): int(v) for k, v in vc.items()},
            "pct_same": round(float((diff == 0).mean()), 4),
            "pct_shift_ge1": round(float((diff.abs() >= 1).mean()), 4)}


def render_md(res):
    lines = ["# R1.4 归一化/档位对照实验",
             "",
             f"- 生成时间：{res['generated_at']}；OOS 起点：{res['oos_start']}",
             f"- 样本：{res['sample']['n_rows']} 行（{res['sample']['date_from']} → {res['sample']['date_to']}）",
             "- 口径：因子分已含 756 日百分位信息；方案 B 的 z-score 作用于因子分（无原始值，属对照近似）。**生产 ZONE_EDGES/归一化不得直接改**。",
             "",
             "## 档位分布（全期）",
             "",
             "| 方案 | 极恐(0) | 恐惧(1) | 中性(2) | 贪婪(3) | 极贪(4) | 平均驻留(日) | 1日自相关 |",
             "|---|---|---|---|---|---|---|---|"]
    for k in ("A", "B", "C"):
        p = res["plans"][k]
        d = p["dist"]
        lines.append(f"| {k} | {d[0]} | {d[1]} | {d[2]} | {d[3]} | {d[4]} | "
                     f"{p['mean_streak']:.1f} | {p['autocorr1']} |")
    lines += ["", "## OOS 档位 → 次日组合收益（2024-10-03 起，M2.1 同口径组合）", ""]
    for k in ("A", "B", "C"):
        p = res["plans"][k]["oos"]
        if not p:
            lines.append(f"- {k}：样本不足")
            continue
        lines.append(f"- **{k}**：IC(Spearman)={p['ic_spearman']}，IC(Pearson)={p['ic_pearson']}，n={p['n']}")
        bz = p["by_zone"]
        rows = "；".join(f"档{i}→{v['mean_next']}(n={v['n']})" for i, v in sorted(bz.items()))
        lines.append(f"  - 分档次日均值：{rows}")
        ext = p["extreme"]
        for zz in ("0", "4"):
            if ext.get(zz):
                e = ext[zz]
                lines.append(f"  - 极{'恐' if zz=='0' else '贪'}档后：1日均值 {e['next1_mean']:.5f}，"
                             f"5日累计 {e['next5_geo']:.5f}（n={e['n']}）")
    rs = res["regime_shift"]
    lines += ["", "## 固定边界 vs 动态档位（跨 regime 证据）", "",
              f"- 对齐样本 n={rs['n']}；档位偏移分布：{rs['shift_dist']}",
              f"- 与动态档位一致率：**{rs['pct_same']*100:.1f}%**；偏移 ≥1 档比例：**{rs['pct_shift_ge1']*100:.1f}%**"]
    lines += ["", "## 结论（登记 decision-log.md）", "",
              "- 以 IC 绝对值与极端档位后收益方向为判据；若固定边界（A）与动态档位（C）在 OOS 上"
              "极端档位行为一致，则「固定边界跨 regime 失效」证据不足，维持现状；若显著分化，走第 8 条流程。"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
