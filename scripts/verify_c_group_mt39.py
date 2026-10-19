#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MT-39 实跑：H-070 / H-072 / H-074 / H-075 / H-076 / H-077 / H-078（**只报数**）。

口径（照 MT-34 / MT-35 / MT-36，逐条遵守）：
  1. 只报数与关键数字，**不下采信结论**（是否采信交用户裁决）；
  2. **不改**任何判据 / 阈值 / 判定口径；
  3. **不回传任何原始数据行**（只出统计量与定位所需的关键数值）；
  4. 数据未到（H-078 / MT-37 需 2026-10-20 收盘）⇒ 明确报「数据未到」，**不提前判**。

⚠️ 列名口径（本脚本不替用户裁定，两种口径都报数）：
  MT-39 字面写 `fg_index == 1.0`，但实测 `fg_index` 列**不存在 1.0 取值**；
  而 memory / 假说证据里所说的「恐惧贪婪指数 1.0」，与 **`zone == 1.0`** 自洽。
  ⇒ H-070 / H-072 同时给 `fg_index==1.0` 与 `zone==1.0` 两组数字。

用法：
  .venv/bin/python scripts/verify_c_group_mt39.py
  .venv/bin/python scripts/verify_c_group_mt39.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "Data")
MEM = os.path.join(REPO, "evolution", "memory")

COLS = ["ammo_position", "drawdown", "core_position", "target_position"]


def _num(x):
    """安全转 float；NaN / 空 ⇒ None。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _bool(v):
    """CSV 里的 True/False 稳妥转 bool（避免被读成字符串导致全 False）。"""
    return str(v).strip().lower() == "true"


def _stat(series):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return {"n": 0, "mean": None, "max": None, "min": None}
    return {"n": int(s.size), "mean": round(float(s.mean()), 8),
            "max": round(float(s.max()), 8), "min": round(float(s.min()), 8)}


def col_probe(feats):
    """列分布探针：确认「1.0」「≥68」等口径落在哪一列（只报分布）。"""
    zc = feats["zone"].value_counts().to_dict()
    return {
        "n_rows": int(len(feats)),
        "date_min": feats["date"].iloc[0],
        "date_max": feats["date"].iloc[-1],
        "fg_index_min": round(float(feats["fg_index"].min()), 6),
        "fg_index_max": round(float(feats["fg_index"].max()), 6),
        "fg_index_eq_1_n": int((feats["fg_index"] == 1.0).sum()),
        "fg_index_lt_2_n": int((feats["fg_index"] < 2.0).sum()),
        "zone_counts": {str(k): int(v) for k, v in zc.items()},
        "zone_eq_1_n": int((feats["zone"] == 1.0).sum()),
        "zone_eq_1_dates": feats.loc[feats["zone"] == 1.0, "date"].tolist()[-15:],
    }


def h070(feats):
    """H-070：低 fg 行的 ammo_position 均值/最大值 vs 高 fg 行（双口径报数）。"""
    out = {}
    for tag, low in (("fg_index_eq_1", feats[feats["fg_index"] == 1.0]),
                     ("zone_eq_1", feats[feats["zone"] == 1.0])):
        out[tag + "_n"] = int(len(low))
        out[tag + "_dates"] = low["date"].tolist()[-15:]
        for c in COLS:
            out[tag + "_" + c] = _stat(low[c])
    high = feats[feats["fg_index"] > 1.0]
    out["fg_gt_1_n"] = int(len(high))
    for c in COLS:
        out["fg_gt_1_" + c] = _stat(high[c])
    for name, mask in (("fg_ge_50", feats["fg_index"] >= 50),
                       ("fg_ge_68", feats["fg_index"] >= 68),
                       ("zone_ge_2", feats["zone"] >= 2.0)):
        out[name + "_n"] = int(mask.sum())
        out[name + "_ammo"] = _stat(feats.loc[mask, "ammo_position"])
    return out


def h072(feats, accts):
    """H-072：低 fg 对应日的股票账户累计盈亏（双口径：fg_index==1.0 / zone==1.0）。"""
    seq = feats["date"].tolist()
    out = {}
    for tag, sub in (("fg_index_eq_1", feats[feats["fg_index"] == 1.0]),
                     ("zone_eq_1", feats[feats["zone"] == 1.0])):
        dates = sub.sort_values("date")["date"].tolist()
        rows = []
        for d in dates:
            i = seq.index(d)
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            for lab, day in (("当日", d), ("次一交易日", nxt)):
                if not day:
                    continue
                a = accts[(accts["date"] == day) & (accts["account"] == "stock")]
                if a.empty:
                    rows.append({"label": lab, "date": day, "found": False})
                    continue
                r = a.iloc[0]
                rows.append({"label": lab, "date": day, "found": True,
                             "net_value": _num(r.get("net_value")),
                             "securities_mv": _num(r.get("securities_mv")),
                             "cash": _num(r.get("cash")),
                             "unrealized_pnl": _num(r.get("unrealized_pnl"))})
        out[tag] = {"dates": dates, "rows": rows}
    return out


def _trig(frame):
    n = int(len(frame))
    if not n:
        return {"n": 0, "circuit_breaker_true": 0, "extreme_true": 0,
                "either_true": 0, "rate_either": None}
    cb = int(frame["circuit_breaker"].sum())
    ex = int(frame["extreme"].sum())
    either = int((frame["circuit_breaker"] | frame["extreme"]).sum())
    return {"n": n, "circuit_breaker_true": cb, "extreme_true": ex,
            "either_true": either, "rate_either": round(either / n, 6)}


def h074(feats):
    """H-074：10-05~10-16 十行布尔位触发率 + 回溯 fg_index ≥ 68 行。"""
    w = feats[(feats["date"] >= "2026-10-05") & (feats["date"] <= "2026-10-16")]
    back = feats[feats["fg_index"] >= 68]
    named = feats[feats["date"].isin(["2026-10-06", "2026-10-07", "2026-10-09"])]
    return {
        "window_rows": [{"date": r["date"], "fg_index": _num(r["fg_index"]),
                         "zone": _num(r["zone"]),
                         "circuit_breaker": bool(r["circuit_breaker"]),
                         "extreme": bool(r["extreme"])}
                        for _, r in w.iterrows()],
        "window": _trig(w),
        "back_fg_ge_68": _trig(back),
        "back_fg_ge_68_dates": back["date"].tolist()[:8],
        "named_rows_1006_1007_1009": [
            {"date": r["date"], "fg_index": _num(r["fg_index"]),
             "circuit_breaker": bool(r["circuit_breaker"]),
             "extreme": bool(r["extreme"])} for _, r in named.iterrows()],
        "all_sample": _trig(feats),
    }


def h075(feats):
    """H-075：2026-10-12~10-16 五行 zone 与 ammo_position 的变动方向。"""
    w = feats[(feats["date"] >= "2026-10-12") & (feats["date"] <= "2026-10-16")]
    rows = [{"date": r["date"], "zone": _num(r["zone"]),
             **{c: _num(r[c]) for c in COLS if c in feats.columns}}
            for _, r in w.iterrows()]
    return {"rows": rows}


def h076(pos, accts):
    """H-076：10-18 / 10-19 快照中 AXTX 与 BTC-USDT 的重复行（含/去重两种口径）。"""
    out = {}
    for d in ("2026-10-18", "2026-10-19"):
        sub = pos[pos["date"] == d]
        axtx = sub[sub["symbol"] == "AXTX"]
        btc = sub[sub["symbol"] == "BTC-USDT"]
        stock = sub[sub["account"] == "stock"]
        crypto = sub[sub["account"] == "crypto"]
        row = {
            "axtx_rows": int(len(axtx)), "btc_rows": int(len(btc)),
            "axtx_qty": _num(axtx["qty"].iloc[0]) if len(axtx) else None,
            "axtx_price": _num(axtx["price"].iloc[0]) if len(axtx) else None,
            "axtx_mv_with_dup": round(float(axtx["market_value"].sum()), 2),
            "btc_mv_with_dup": round(float(btc["market_value"].sum()), 2),
            "axtx_mv_dedup": round(float(axtx["market_value"].drop_duplicates().sum()), 2),
            "btc_mv_dedup": round(float(btc["market_value"].drop_duplicates().sum()), 2),
            "stock_mv_sum": round(float(stock["market_value"].sum()), 2),
            "crypto_mv_sum": round(float(crypto["market_value"].sum()), 2),
        }
        a = accts[(accts["date"] == d) & (accts["account"] == "stock")]
        if not a.empty:
            r = a.iloc[0]
            row["acct_stock_net_value"] = _num(r.get("net_value"))
            row["acct_stock_securities_mv"] = _num(r.get("securities_mv"))
            row["acct_stock_cash"] = _num(r.get("cash"))
            for key in ("net_value", "securities_mv"):
                av = _num(r.get(key))
                if av is not None:
                    row["diff_stock_mv_sum_vs_" + key] = round(
                        row["stock_mv_sum"] - av, 2)
        out[d] = row
    return out


def _read_memory_baseline(day):
    """从 memory/<day>.md 抽取「本金」与该日 memory 自述的百分数。"""
    p = os.path.join(MEM, day + ".md")
    if not os.path.exists(p):
        return {"file": False}
    txt = open(p, encoding="utf-8", errors="replace").read()
    base = re.search(r"本金\s*([0-9]+(?:\.[0-9]+)?)", txt)
    pct = re.search(r"约\s*-?([0-9]+(?:\.[0-9]+)?)\s*%", txt)
    return {"file": True,
            "baseline": _num(base.group(1)) if base else None,
            "pct": _num(pct.group(1)) if pct else None}


def h077(accts):
    """H-077：本金口径变化 —— 各口径与 -879.99 互推百分比。"""
    pnl = -879.99
    mem = {d: _read_memory_baseline(d)
           for d in ("2026-10-14", "2026-10-15", "2026-10-17")}
    snap = accts[(accts["date"] == "2026-10-19") & (accts["account"] == "stock")]
    base_1019 = _num(snap.iloc[0]["securities_mv"]) if not snap.empty else None
    derived = round(pnl / -0.0688, 2)          # 用 10-17 memory 的 -6.88% 反推
    cand = {}
    for label, b in (("10-14 memory 本金", mem["2026-10-14"].get("baseline")),
                     ("10-15 memory 本金", mem["2026-10-15"].get("baseline")),
                     ("10-16 由 -6.88% 反推", derived),
                     ("10-19 快照 securities_mv", base_1019)):
        cand[label] = {"baseline": b,
                       "pct": (round(pnl / b * 100, 2) if b else None)}
    return {"pnl": pnl, "memory": mem, "candidates": cand,
            "derived_1016_baseline": derived}


def h078_and_mt37(feats):
    """H-078 / MT-37：需 2026-10-20 收盘数据 ⇒ 报「数据未到」。"""
    last = feats["date"].iloc[-1]
    tail = feats.tail(5)[["date", "fg_index", "zone", "core_position"]]
    return {"features_last_date": last,
            "need_dates": ["2026-10-20", "2026-10-21", "2026-10-22"],
            "tail_rows": [{"date": r["date"], "fg_index": _num(r["fg_index"]),
                           "zone": _num(r["zone"]),
                           "core_position": _num(r["core_position"])}
                          for _, r in tail.iterrows()]}


def main():
    ap = argparse.ArgumentParser(description="MT-39 实跑（只报数、不下采信结论）")
    ap.add_argument("--json", action="store_true", help="JSON 输出（默认即 JSON）")
    ap.parse_args()

    feats = pd.read_csv(os.path.join(DATA, "features.csv"))
    accts = pd.read_csv(os.path.join(DATA, "accounts.csv"))
    pos = pd.read_csv(os.path.join(DATA, "positions.csv"))
    for c in ("circuit_breaker", "extreme"):
        if c in feats.columns:
            feats[c] = feats[c].apply(_bool)

    rep = {
        "列分布探针": col_probe(feats),
        "H-070": h070(feats),
        "H-072": h072(feats, accts),
        "H-074": h074(feats),
        "H-075": h075(feats),
        "H-076": h076(pos, accts),
        "H-077": h077(accts),
        "H-078 与 MT-37": h078_and_mt37(feats),
    }
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
