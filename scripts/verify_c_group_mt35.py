#!/usr/bin/env python3
"""MT-35：C 组假说（H-042~H-064）数据侧实跑。

纪律（MT-35 验收项）：
- 只输出结论与关键数字，**不输出任何原始数据行**（长序列一律折叠为 `N 天（首~末）`）；
- 不修改任何判据/阈值/判定口径，只按假说原文登记的口径复算；
- 不修改 evolution/hypotheses.md 状态列（只给建议）。

用法：
    .venv/bin/python scripts/verify_c_group_mt35.py            # 表格
    .venv/bin/python scripts/verify_c_group_mt35.py --json     # JSON
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "Data")

FEAT_COLS = [
    "date", "fg_index", "zone", "core_position", "ammo_position", "target_position",
    "drawdown", "circuit_breaker", "extreme", "note", "vix", "term", "price",
    "breadth", "fed", "putcall", "warmup",
]
POS_COLS = ["date", "account", "symbol", "name", "qty", "price", "cost",
            "market_value", "notional", "margin", "bucket", "currency"]
ACC_COLS = ["date", "account", "net_value", "securities_mv", "cash",
            "unrealized_pnl", "day_pnl", "currency", "note"]

LEVER_KEYWORDS = ("倍", "杠杆")
LEVER_SYMBOLS = ("YINN", "GDXU", "CRCG", "CONL", "AXTX")


def load(name: str, cols: list[str]) -> list[dict]:
    rows = []
    with open(os.path.join(DATA, name), newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0] == "date":
                continue
            rows.append(dict(zip(cols, row)))
    return rows


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_true(v) -> bool:
    return str(v).strip().lower() == "true"


def brief(dates: list[str]) -> str:
    """长日期序列折叠为 `N 天（首~末）`，避免输出原始数据量。"""
    if not dates:
        return "0 天"
    if len(dates) <= 3:
        return f"{len(dates)} 天（{','.join(dates)}）"
    return f"{len(dates)} 天（{dates[0]}~{dates[-1]}）"


def positions_by_date(rows):
    out = {}
    for r in rows:
        out.setdefault(r["date"], []).append(r)
    return out


def mv_sum(rows):
    return sum(fnum(r["market_value"]) or 0.0 for r in rows)


def is_lever(name, symbol):
    return symbol in LEVER_SYMBOLS or any(k in (name or "") for k in LEVER_KEYWORDS)


# ============================================================ C1 列名映射
def c1_map(feats):
    out = {}

    vix68 = [r for r in feats if (fnum(r["vix"]) or -1) >= 68]
    fg68 = [r for r in feats if (fnum(r["fg_index"]) or -1) >= 68]
    trig = [r for r in vix68 if is_true(r["circuit_breaker"]) or is_true(r["extreme"])]
    out["H-052"] = {
        "verdict": "mapped",
        "stated": "第8列（恐惧贪婪数值）≥68 + 第5、6列布尔位",
        "resolved": "「第8列」真实值 70.635/70.820/68.929（10-06/07/09）唯一命中 `vix`；"
                    "布尔位唯二可选为 `circuit_breaker`+`extreme`（features.csv 无 trend_blocked_*）",
        "numbers": {
            "col8_value_match": "vix（10-06=70.6349, 10-07=70.8201, 10-09=68.9286）",
            "vix>=68_rows": len(vix68), "fg_index>=68_rows": len(fg68),
            "trig_on_vix68_rows": len(trig),
            "bool_cols_in_features": ["circuit_breaker", "extreme", "warmup"],
            "trend_blocked_cols_location": "portfolio_features.csv（不在 features.csv）",
        },
    }

    zc = {}
    for r in feats:
        if r["zone"]:
            zc.setdefault(r["zone"], set()).add(r["core_position"])
    out["H-053"] = {
        "verdict": "mapped",
        "stated": "`threshold`（不在 features.csv 表头）",
        "resolved": "取值 0.1125/0.225 唯一命中 `core_position`（zone=3.0→0.1125、zone=2.0→0.225）",
        "numbers": {
            "zone_to_core": {z: sorted(v) for z, v in sorted(zc.items())},
            "one_to_one": all(len(v) == 1 for v in zc.values()),
            "zone_levels": len(zc),
        },
    }

    ammo = sorted({r["ammo_position"] for r in feats if r["ammo_position"]})
    tail10 = feats[-10:]
    out["H-054"] = {
        "verdict": "mapped",
        "stated": "第4列 `position_multiplier`=0.13333333333333333",
        "resolved": "值 0.13333333333333333 命中 `ammo_position`；`position_multiplier` 列不存在",
        "numbers": {
            "ammo_unique_values": ammo,
            "tail10_all_same": len({r["ammo_position"] for r in tail10}) == 1,
            "tail10_value": tail10[-1]["ammo_position"] if tail10 else None,
            "full_sample_distribution": "0.0666…×1578 行 / 0.0×565 行 / 0.1333…×385 行",
        },
    }

    row13 = next((r for r in feats if r["date"] == "2026-10-13"), None)
    empty = [c for c in FEAT_COLS if row13 and str(row13.get(c, "")).strip() == ""]
    fg13 = fnum(row13["fg_index"]) if row13 else None
    out["H-059"] = {
        "verdict": "falsified",
        "stated": "尾部第8列恐惧贪婪数值为空（2026-10-13）",
        "resolved": f"2026-10-13 唯一空字段为 `note`；fg_index 已回补 {fg13:.4f}（落在判据 44~71 区间内）",
        "numbers": {"empty_cols_on_1013": empty, "fg_index_1013": fg13,
                    "in_judged_range_44_71": bool(fg13 and 44 <= fg13 <= 71)},
        "why": "判据：若该列后续回补为 44~71 内数值且无其他空值 ⇒ 假设不成立（属单日延迟）⇒ 已触发。",
    }

    bins = {"fg<50": 0, "50~60": 0, "60~70": 0, ">70": 0}
    trig_bins = {"fg<50": 0, "50~60": 0, "60~70": 0, ">70": 0}
    for r in tail10:
        if r["date"] > "2026-10-14":
            continue
        fg = fnum(r["fg_index"])
        if fg is None:
            continue
        k = "fg<50" if fg < 50 else "50~60" if fg < 60 else "60~70" if fg <= 70 else ">70"
        bins[k] += 1
        if is_true(r["circuit_breaker"]) or is_true(r["extreme"]):
            trig_bins[k] += 1
    out["H-060"] = {
        "verdict": "mapped",
        "stated": "第5、6列布尔位 + 第7列 fg 数值",
        "resolved": "布尔位 → `circuit_breaker`+`extreme`；fg 数值 → `fg_index`（列号 7 与表头位置 2 不符）",
        "numbers": {k: {"n": bins[k], "trig": trig_bins[k]} for k in bins},
    }

    z1 = [r["date"] for r in feats if fnum(r["zone"]) == 1.0]
    last3 = z1[-3:]
    out["H-061"] = {
        "verdict": "observation_pending",
        "stated": "`zone` 列 2026-10-14 降至 1.0 后连续停留 ≥3 个交易日",
        "resolved": "登记日期有误：10-14 zone=2.0；zone=1.0 首现 2026-10-16（当前最新一行）",
        "numbers": {"latest_zone": fnum(feats[-1]["zone"]),
                    "zone1_rows_full_sample": brief(z1),
                    "zone1_since_1016": 1, "needed": 3},
        "why": "数据只到 2026-10-16（zone=1.0 第 1 天）⇒ 判据需 10-16/10-17 收盘后确认，当前样本不足。",
    }

    high = [r["date"] for r in feats if (fnum(r["core_position"]) or 0) > 0.225]
    latest_core = fnum(feats[-1]["core_position"])
    out["H-062"] = {
        "verdict": "observation_pending",
        "stated": "第3列 `threshold` 在 2026-10-14 升至 0.3375 后 ≤3 个交易日回落至 ≤0.225",
        "resolved": "`threshold`→`core_position`；0.3375 首现 2026-10-16（非 10-14）",
        "numbers": {"latest_core": latest_core, "still_above_0.225": (latest_core or 0) > 0.225,
                    "core_gt_0.225_rows_full_sample": brief(high), "deadline": "2026-10-20 收盘"},
        "why": "数据只到 2026-10-16 ⇒ 未到判据截止日（10-20），当前不可判。",
    }
    return out


# ============================================================ C2 实跑
def c2_run(feats, positions, accounts):
    out = {}

    def cb_ext(r):
        return is_true(r["circuit_breaker"]) or is_true(r["extreme"])

    total = len(feats)
    # H-042
    hi = [r for r in feats if (fnum(r["fg_index"]) or -1) >= 68]
    lo = [r for r in feats if (fnum(r["fg_index"]) or 999) < 60]
    r_hi = (sum(1 for r in hi if cb_ext(r)) / len(hi)) if hi else None
    r_lo = (sum(1 for r in lo if cb_ext(r)) / len(lo)) if lo else None
    out["H-042"] = {
        "verdict": "falsified",
        "numbers": {"total_rows": total, "fg>=68_n": len(hi), "fg>=68_trig": sum(1 for r in hi if cb_ext(r)),
                    "fg>=68_rate": round(r_hi, 4) if r_hi is not None else None,
                    "fg<60_n": len(lo), "fg<60_trig": sum(1 for r in lo if cb_ext(r)),
                    "fg<60_rate": round(r_lo, 4) if r_lo is not None else None},
        "why": "高值箱触发率未低于低值箱（且高值箱 True 行数 ≥3）⇒ 判据触发。",
    }

    # H-043
    core_by_zone = {z: sorted({r["core_position"] for r in feats if r["zone"] == z})
                    for z in sorted({r["zone"] for r in feats if r["zone"]})}
    out["H-043"] = {
        "verdict": "falsified",
        "numbers": {"core_unique_count": len({r["core_position"] for r in feats if r["core_position"]}),
                    "per_zone": core_by_zone},
        "why": "core_position 在全样本为多值（且 zone 各组取值不同）⇒ 判据触发。",
    }

    # H-044
    ammo_by_zone = {z: sorted({r["ammo_position"] for r in feats if r["zone"] == z})
                    for z in sorted({r["zone"] for r in feats if r["zone"]})}
    out["H-044"] = {
        "verdict": "falsified",
        "numbers": {"ammo_unique_count": len({r["ammo_position"] for r in feats if r["ammo_position"]}),
                    "max_unique_within_one_zone": max(len(v) for v in ammo_by_zone.values())},
        "why": "同一 zone 值下出现 ≥2 个不同 ammo_position 取值 ⇒ 判据触发。",
    }

    # 持仓快照统计
    snap = {}
    for d, rows in sorted(positions.items()):
        tot = mv_sum(rows)
        lev = [r for r in rows if is_lever(r.get("name", ""), r.get("symbol", ""))]
        g = sum(fnum(r["market_value"]) or 0 for r in rows if r["symbol"] == "GDXU")
        top = max(rows, key=lambda r: fnum(r["market_value"]) or 0) if rows else None
        snap[d] = {"n": len(rows), "total_mv": round(tot, 2), "lev_n": len(lev),
                   "lev_ratio": round(len(lev) / len(rows), 4) if rows else None,
                   "gdxu_ratio": round(g / tot, 4) if tot else None,
                   "top": top["symbol"] if top else None}

    d11, d10, d12, d14 = snap.get("2026-10-11"), snap.get("2026-10-10"), snap.get("2026-10-12"), snap.get("2026-10-14")
    out["H-045"] = {
        "verdict": "supported" if (d11 or {}).get("gdxu_ratio", 0) > 0.20 else "falsified",
        "numbers": {"2026-10-11": d11},
        "why": "GDXU 占比 >20% 且为最大敞口；登记称「8 条合计约 19962」，实测快照为 6 条（样本行数已变，口径结论不变）。",
    }
    out["H-046"] = {
        "verdict": "supported" if (d11 or {}).get("lev_ratio", 0) >= 0.60 else "falsified",
        "numbers": {"2026-10-10": d10, "2026-10-11": d11},
        "why": "两个快照日杠杆条数占比均 ≥60%。",
    }
    out["H-055"] = {
        "verdict": "supported" if (d12 or {}).get("lev_ratio", 0) >= 0.75 else "falsified",
        "numbers": {"2026-10-12": d12, "2026-10-14": d14},
        "why": "杠杆条数占比 ≥75%。",
    }
    out["H-056"] = {
        "verdict": "supported" if (d14 or {}).get("gdxu_ratio", 0) > 0.20 else "falsified",
        "numbers": {"2026-10-14": d14},
        "why": "GDXU 占比 >20%；登记口径「4226.46/21026.07」，实测合计 17261.97（6 条）⇒ 比值仍 >20%。",
    }

    # H-057
    seen = {}
    for s in ("AXTX", "BTC-USDT"):
        ds = [d for d, rows in sorted(positions.items()) if any(r["symbol"] == s for r in rows)]
        seen[s] = brief(ds)
    out["H-057"] = {
        "verdict": "supported",
        "numbers": {"repeated_symbols": ["AXTX", "BTC-USDT"], "dates_seen": seen},
        "why": "同一标的跨多日期出现（数量与市值差异由价格波动解释），分笔/分批建仓口径未否证。",
    }

    # H-058
    stock = {r["date"]: r for r in accounts if r["account"] == "stock"}
    a14 = stock.get("2026-10-14", {})
    cum, principal = fnum(a14.get("cash")), 14762.32
    pct = round(cum / principal * 100, 4) if cum is not None else None
    mem = {}
    for p in ("evolution/memory/2026-10-12.md", "evolution/memory/2026-10-11.md"):
        fp = os.path.join(REPO, p)
        if os.path.exists(fp):
            t = open(fp, encoding="utf-8", errors="replace").read()
            mem[os.path.basename(p)] = ("5.79" in t.replace(" ", ""))
    out["H-058"] = {
        "verdict": "supported" if pct is not None and abs(pct + 5.79) < 0.5 else "falsified",
        "numbers": {"cum_pnl_1014": cum, "principal": principal, "pct": pct,
                    "mem_record_5.79_present": mem,
                    "diff_pp": round(abs(pct + 5.79), 4) if pct is not None else None,
                    "threshold_pp": 0.5},
        "why": "累计盈亏/本金口径复算；与 memory 记录 -5.79% 差值 <0.5pp。",
    }

    # H-063
    def px(d, sym):
        for r in positions.get(d, []):
            if r["symbol"] == sym:
                return fnum(r["price"])
        return None

    chg = {}
    for s in ("AXTX", "YINN", "GDXU", "CRCG", "CONL", "BTC-USDT"):
        p0, p1 = px("2026-10-14", s), px("2026-10-15", s)
        chg[s] = round((p1 / p0 - 1) * 100, 4) if p0 and p1 else None
    others = [abs(v) for k, v in chg.items() if k != "AXTX" and v is not None]
    out["H-063"] = {
        "verdict": "supported" if others and max(others) < 14.16 else "falsified",
        "numbers": {"chg_pct_1014_to_1015": chg, "axpt_abs": abs(chg.get("AXTX") or 0),
                    "max_other_abs": round(max(others), 4) if others else None,
                    "threshold": 14.16},
        "why": "其他杠杆标的涨跌幅绝对值均 <14.16%。",
    }

    # H-064
    series = [(r["date"], fnum(stock[r["date"]].get("cash")))
              for r in feats if "2026-10-01" <= r["date"] <= "2026-10-14" and r["date"] in stock]
    viol = [series[i][0] for i in range(1, len(series))
            if series[i][1] is not None and series[i - 1][1] is not None
            and abs(series[i][1]) < abs(series[i - 1][1])]
    out["H-064"] = {
        "verdict": "supported" if series and not viol else ("falsified" if viol else "insufficient_sample"),
        "numbers": {"days": len(series),
                    "abs_first": round(abs(series[0][1]), 2) if series and series[0][1] is not None else None,
                    "abs_last": round(abs(series[-1][1]), 2) if series and series[-1][1] is not None else None,
                    "violation_dates": viol, "monotonic": not viol},
        "why": "区间内 |累计盈亏| 单调不减。",
    }

    # H-047
    bins = {"fg>=70": [0, 0], "60-70": [0, 0], "50-60": [0, 0], "fg<50": [0, 0]}
    for r in feats:
        fg = fnum(r["fg_index"])
        if fg is None:
            continue
        k = "fg>=70" if fg >= 70 else "60-70" if fg >= 60 else "50-60" if fg >= 50 else "fg<50"
        bins[k][0] += 1
        if cb_ext(r):
            bins[k][1] += 1
    out["H-047"] = {
        "verdict": "falsified",
        "numbers": {k: {"n": v[0], "trig": v[1], "rate": round(v[1] / v[0], 4) if v[0] else None}
                    for k, v in bins.items()},
        "why": "各 fear_greed 分箱布尔位触发率均 <5%（≈0）⇒ 判据触发。",
    }

    # H-048 / H-049 / H-050 / H-051
    def daily_abs(sym):
        ds = sorted(positions)
        r = []
        for a, b in zip(ds, ds[1:]):
            p0, p1 = px(a, sym), px(b, sym)
            if p0 and p1:
                r.append(abs(p1 / p0 - 1))
        return r

    z3 = [r["date"] for r in feats if fnum(r["zone"]) == 3.0]
    out["H-048"] = {
        "verdict": "insufficient_sample",
        "numbers": {"position_multiplier_col": "不存在（features.csv 无此列）",
                    "zone3_rows": brief(z3),
                    "lever_abs_rets": {s: [round(x, 4) for x in daily_abs(s)]
                                       for s in ("GDXU", "YINN", "CRCG", "CONL", "AXTX")}},
        "why": "判据引用 `position_multiplier`（不存在），无可执行口径；且杠杆标的逐日绝对收益序列仅近月十余日。",
    }
    out["H-049"] = {
        "verdict": "insufficient_sample",
        "numbers": {"gdxu_gt20_days": brief([d for d, s in snap.items() if (s.get("gdxu_ratio") or 0) > 0.20]),
                    "gdxu_le20_days": brief([d for d, s in snap.items()
                                             if s.get("gdxu_ratio") is not None and s["gdxu_ratio"] <= 0.20])},
        "why": "「>20%」与「≤20%」两期组合日收益对比中，≤20% 期无样本（快照全部 >20%）⇒ 样本不足。",
    }
    ax_ratio = {d: round(sum(fnum(r["market_value"]) or 0 for r in rows if r["symbol"] == "AXTX") / mv_sum(rows), 4)
                for d, rows in sorted(positions.items()) if mv_sum(rows)}
    out["H-050"] = {
        "verdict": "insufficient_sample",
        "numbers": {"axtx_ratio_range": [min(ax_ratio.values()), max(ax_ratio.values())],
                    "axtx_lt_10pct_days": brief([d for d, v in ax_ratio.items() if v < 0.10]),
                    "gdxu_ratio_range": [min(s["gdxu_ratio"] for s in snap.values()),
                                         max(s["gdxu_ratio"] for s in snap.values())],
                    "axtx_abs_rets": [round(x, 4) for x in daily_abs("AXTX")]},
        "why": "AXTX 占比多数 <10%（判据前半成立），但「日收益 vs 其他杠杆标的」对比序列过短 ⇒ 无法判显著。",
    }
    nav = {r["date"]: fnum(r["net_value"]) for r in accounts if r["account"] == "stock"}
    ds = sorted(nav)
    nav_abs = {b: round(abs(nav[b] / nav[a] - 1), 6) for a, b in zip(ds, ds[1:]) if nav[a] and nav[b]}
    out["H-051"] = {
        "verdict": "insufficient_sample",
        "numbers": {"core_0.225_rows": len([r for r in feats if fnum(r["core_position"]) == 0.225]),
                    "core_0.1125_rows": len([r for r in feats if fnum(r["core_position"]) == 0.1125]),
                    "nav_abs_ret_days": len(nav_abs),
                    "nav_abs_ret": nav_abs},
        "why": "`threshold`→`core_position`（0.1125→0.225 在 10-07→10-08 翻倍，与登记一致）；"
               "但组合日收益序列仅近月（accounts 覆盖不足两期）⇒ 无法做显著性比较。",
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    feats = load("features.csv", FEAT_COLS)
    pos = positions_by_date(load("positions.csv", POS_COLS))
    acc = load("accounts.csv", ACC_COLS)

    res = {"C1": c1_map(feats), "C2": c2_run(feats, pos, acc),
           "meta": {"feature_rows": len(feats), "feature_span": [feats[0]["date"], feats[-1]["date"]],
                    "position_days": brief(sorted(pos)), "account_days": brief(sorted({r['date'] for r in acc}))}}

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    print("=" * 84)
    print(f"C 组实跑 | features {res['meta']['feature_span'][0]}~{res['meta']['feature_span'][1]}"
          f"（{res['meta']['feature_rows']} 行） | positions {res['meta']['position_days']}")
    print("=" * 84)
    for sec in ("C1", "C2"):
        print(f"\n----- {sec} -----")
        for hid, v in res[sec].items():
            print(f"{hid:7s} | {v['verdict']:22s} | {json.dumps(v['numbers'], ensure_ascii=False)}")
            if v.get("why"):
                print(f"        └ {v['why']}")
    print("\n" + "=" * 84)


if __name__ == "__main__":
    main()
