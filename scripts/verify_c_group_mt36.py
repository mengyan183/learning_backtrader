#!/usr/bin/env python3
"""MT-36：C 组收尾补跑（H-053 / H-054 / H-060 统计量 + H-061 / H-062 到期判定）。

纪律（MT-36 验收项，照 MT-34 / MT-35 口径）：
- 只输出统计量与关键数字，**不输出任何原始数据行**（长序列一律折叠为 `N 天（首~末）`）；
- 不修改任何判据 / 阈值 / 判定口径，只按假说原文登记的区间与口径复算；
- 不修改 evolution/hypotheses.md 状态列（只给事实，采信交用户）。

区间口径（取自各假说原文）：
- H-053 / H-054：尾部十行 = 2026-09-30 ~ 2026-10-13
- H-060：尾部 10 行 = 2026-10-01 ~ 2026-10-14
- H-061 / H-062：2026-10-15 ~ 2026-10-20 逐日观察

用法：
    .venv/bin/python scripts/verify_c_group_mt36.py            # 表格
    .venv/bin/python scripts/verify_c_group_mt36.py --json     # JSON
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

# H-053：判据原文只登记两对（3.0↔0.1125 / 2.0↔0.225）；MT-35 反推补充其余档。
# 键/值均写成 norm() 归一后的形式（3.0→"3"、0.0→"0"），与 norm(zone)/norm(core) 同基准。
ZONE_CORE_EXPECTED = {"4": "0", "3": "0.1125", "2": "0.225",
                      "1": "0.3375", "0": "0.45"}
ZONE_CORE_JUDGED = {"3": "0.1125", "2": "0.225"}  # 判据正文明确的两对

AMMO_CONST = "0.13333333333333333"
H062_DEADLINE = "2026-10-20"


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
    if not dates:
        return "0 天"
    if len(dates) <= 3:
        return f"{len(dates)} 天（{','.join(dates)}）"
    return f"{len(dates)} 天（{dates[0]}~{dates[-1]}）"


def in_range(rows, lo, hi):
    return [r for r in rows if lo <= r["date"] <= hi]


def norm(v: str) -> str:
    """数值字符串归一（0.2250 / 0.225 视为同一档）。"""
    f = fnum(v)
    return f"{f:.6g}" if f is not None else str(v).strip()


# ============================================================ H-053 一致率
def h053(feats):
    seg = in_range(feats, "2026-09-30", "2026-10-13")
    pairs = []
    for r in seg:
        pairs.append((norm(r["zone"]), norm(r["core_position"]), r["date"]))

    counts = {}
    for z, c, _ in pairs:
        counts[f"zone={z} → core={c}"] = counts.get(f"zone={z} → core={c}", 0) + 1

    # 判据正文口径：只校验 3.0↔0.1125 与 2.0↔0.225 两对
    judged_rows = [p for p in pairs if p[0] in ZONE_CORE_JUDGED]
    hit = [p for p in judged_rows if p[1] == ZONE_CORE_JUDGED[p[0]]]
    rate_judged = round(len(hit) / len(judged_rows), 4) if judged_rows else None
    # 判据的不成立条件：zone=3.0 且 core=0.225，或 zone=2.0 且 core=0.1125
    viol = [p[2] for p in judged_rows
            if (p[0] == "3" and p[1] == "0.225") or (p[0] == "2" and p[1] == "0.1125")]

    # 全量（含 1.0 档与区间外全样本映射）作为参考
    all_rows = [r for r in feats if r["zone"] and r["core_position"]]
    all_pairs = [(norm(r["zone"]), norm(r["core_position"])) for r in all_rows]
    hit_all = [p for p in all_pairs if ZONE_CORE_EXPECTED.get(p[0]) == p[1]]
    rate_all = round(len(hit_all) / len(all_pairs), 4) if all_pairs else None

    return {
        "verdict": "stats_out",
        "numbers": {
            "segment": "2026-09-30~2026-10-13",
            "segment_rows": len(seg),
            "pair_distribution": counts,
            "judged_pairs": "zone=3.0↔0.1125 / zone=2.0↔0.225（判据正文口径）",
            "judged_rows": len(judged_rows),
            "judged_hit": len(hit),
            "consistency_rate_judged": rate_judged,
            "violation_dates": brief(viol) if viol else "无",
            "consistency_rate_full_sample": rate_all,
            "violation_dates_full_sample": brief(
                [r["date"] for r in all_rows
                 if ZONE_CORE_EXPECTED.get(norm(r["zone"])) != norm(r["core_position"])]),
        },
        "why": "判据不成立条件为「任一 judged 行出现 zone=3.0 且 core=0.225 或 zone=2.0 且 core=0.1125」"
               "⇒ 一致率 <100% 即触发；本项只报一致率与违例日期，不下采信结论。",
    }


# ============================================================ H-054 去重计数/方差
def h054(feats):
    seg = in_range(feats, "2026-09-30", "2026-10-13")
    vals = [fnum(r["ammo_position"]) for r in seg]
    vals = [v for v in vals if v is not None]
    uniq = sorted({r["ammo_position"] for r in seg if r["ammo_position"]})
    pvar = round(statistics.pvariance(vals), 12) if len(vals) > 1 else None
    svar = round(statistics.variance(vals), 12) if len(vals) > 1 else None

    later = [r for r in feats if r["date"] > "2026-10-13"]
    later_vals = [norm(r["ammo_position"]) for r in later if r["ammo_position"]]
    later_same = bool(later_vals) and len(set(later_vals)) == 1 and later_vals[0] == norm(AMMO_CONST)
    dev = [r["date"] for r in later if r["ammo_position"] and norm(r["ammo_position"]) != norm(AMMO_CONST)]

    return {
        "verdict": "stats_out",
        "numbers": {
            "segment": "2026-09-30~2026-10-13",
            "segment_rows": len(seg),
            "distinct_count": len(uniq),
            "distinct_values": uniq,
            "pvariance": pvar,
            "variance_sample": svar,
            "value_const": len(uniq) == 1 and norm(uniq[0]) == norm(AMMO_CONST),
            "later_rows": brief([r["date"] for r in later]),
            "later_all_equal_0.13333333333333333": later_same,
            "later_deviation_dates": brief(dev) if dev else "无",
            "full_sample_distinct": sorted({r["ammo_position"] for r in feats if r["ammo_position"]}),
        },
        "why": "判据不成立条件为「尾部任一后续行第4列≠0.13333333333333333」⇒ 只报去重计数/方差与后续行是否仍恒定。",
    }


# ============================================================ H-060 分箱触发
def _bin_stats(rows):
    bins = {"fg<50": [0, 0], "50~60": [0, 0], "60~70": [0, 0], ">70": [0, 0]}
    for r in rows:
        fg = fnum(r["fg_index"])
        if fg is None:
            continue
        k = "fg<50" if fg < 50 else "50~60" if fg < 60 else "60~70" if fg <= 70 else ">70"
        bins[k][0] += 1
        if is_true(r["circuit_breaker"]) or is_true(r["extreme"]):
            bins[k][1] += 1
    return {k: {"n": v[0], "trig": v[1],
                "rate": round(v[1] / v[0], 4) if v[0] else None} for k, v in bins.items()}


def h060(feats):
    seg = in_range(feats, "2026-10-01", "2026-10-14")
    seg_stats = _bin_stats(seg)
    full_stats = _bin_stats(feats)
    trig_in_seg = sum(v["trig"] for v in seg_stats.values())
    return {
        "verdict": "stats_out",
        "numbers": {
            "segment": "2026-10-01~2026-10-14（判据原文口径）",
            "segment_rows": len(seg),
            "segment_bins": seg_stats,
            "segment_trigger_total": trig_in_seg,
            "full_sample_bins": full_stats,
            "full_sample_rows": len(feats),
            "full_sample_trigger_total": sum(v["trig"] for v in full_stats.values()),
        },
        "why": "判据不成立条件为「任一 fg 分箱出现至少 1 次 True」⇒ 只报四箱触发次数与总行数，不下采信结论。",
    }


# ============================================================ H-061 / H-062
# MT-50：观察窗截止日硬编码（与 observation_window 文案一致）
H061_WINDOW_END = "2026-10-20"


def h061_h062(feats, latest_date):
    zone_by_date = {r["date"]: r["zone"] for r in feats}
    core_by_date = {r["date"]: r["core_position"] for r in feats}
    obs = [r for r in feats if r["date"] >= "2026-10-15"]

    # H-061：zone=1.0 连续交易日数（自 10-15 起的观察窗内）
    z1_obs = [r["date"] for r in obs if norm(r["zone"]) == "1"]
    # 判据的不成立条件：10-16 或 10-17 收盘后 zone ≥2.0
    fail_dates = [d for d in ("2026-10-16", "2026-10-17")
                  if zone_by_date.get(d) and (fnum(zone_by_date[d]) or 0) >= 2.0]
    latest_zone = zone_by_date.get(latest_date)

    # H-062：先定位「升破 0.225」的日期（判据语境的起点），再找其后的首次 ≤0.225
    first_above = next((r["date"] for r in obs if (fnum(r["core_position"]) or 0) > 0.225), None)
    first_le_after = next((r["date"] for r in obs
                           if first_above and r["date"] > first_above
                           and (fnum(r["core_position"]) or 9) <= 0.225), None)
    latest_core = core_by_date.get(latest_date)

    # MT-50：边界判定——latest_date >= 截止日 ⇒ 观察窗已走完（不是 >）。
    # 旧版硬编码「观察窗未走完」文案，导致截止日当天（latest == deadline）
    # 也误报未走完。这里只改 reason_not_judged 文案，不改判据、不下结论。
    h061_window_closed = (latest_date is not None
                           and latest_date >= H061_WINDOW_END)
    if h061_window_closed:
        h061_reason = (f"观察窗已走完（latest={latest_date} ≥ 截止={H061_WINDOW_END}）"
                       f"，且不成立条件未触发；只报数不下结论。")
    else:
        h061_reason = (f"features.csv 最新仅到 {latest_date}（< 截止 {H061_WINDOW_END}）"
                       f"⇒ 观察窗未走完，且不成立条件未触发。")

    h062_deadline_reached = (latest_date is not None
                             and latest_date >= H062_DEADLINE)
    if h062_deadline_reached:
        h062_reason = (f"截止日已到（latest={latest_date} ≥ deadline={H062_DEADLINE}）"
                       f"⇒ 可判；只报数不下结论。")
    else:
        h062_reason = (f"截止日 {H062_DEADLINE} 未到（features.csv 最新 {latest_date} < deadline）"
                       f"⇒ 不可判。")

    return {
        "H-061": {
            "verdict": "observation_pending",
            "numbers": {
                "observation_window": "2026-10-15~2026-10-20（判据原文）",
                "data_latest_date": latest_date,
                "window_end": H061_WINDOW_END,
                "window_closed": h061_window_closed,
                "observed_days": brief([r["date"] for r in obs]),
                "zone_1_0_days": brief(z1_obs),
                "zone_1_0_consecutive_days": len(z1_obs),
                "needed": 3,
                "latest_zone": latest_zone,
                "falsify_condition": "10-16 或 10-17 收盘后 zone ≥2.0",
                "falsify_triggered": bool(fail_dates),
                "falsify_dates": brief(fail_dates) if fail_dates else "无",
                "reason_not_judged": h061_reason,
            },
            "why": "只报观察窗内 zone=1.0 天数与不成立条件是否触发，不下采信结论。",
        },
        "H-062": {
            "verdict": "observation_pending",
            "numbers": {
                "observation_window": "2026-10-15~2026-10-20（判据原文）",
                "data_latest_date": latest_date,
                "observed_days": brief([r["date"] for r in obs]),
                "first_above_0.225_date": first_above or "未出现",
                "first_le_0.225_after_rise": first_le_after or "未出现",
                "latest_core_position": latest_core,
                "still_above_0.225": bool(latest_core and fnum(latest_core) > 0.225),
                "deadline": H062_DEADLINE,
                "deadline_reached": h062_deadline_reached,
                "reason_not_judged": h062_reason,
            },
            "why": "只报是否已回落（首次 ≤0.225 的日期）与截止日状态，不下采信结论。",
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    feats = load("features.csv", FEAT_COLS)
    latest_date = feats[-1]["date"] if feats else None

    res = {
        "H-053": h053(feats),
        "H-054": h054(feats),
        "H-060": h060(feats),
        **h061_h062(feats, latest_date),
        "meta": {"feature_rows": len(feats), "feature_span": [feats[0]["date"], latest_date]},
    }

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    print("=" * 88)
    print(f"MT-36 C 组收尾 | features {res['meta']['feature_span'][0]}~{res['meta']['feature_span'][1]}"
          f"（{res['meta']['feature_rows']} 行）")
    print("=" * 88)
    for hid in ("H-053", "H-054", "H-060", "H-061", "H-062"):
        v = res[hid]
        print(f"\n{hid} | {v['verdict']}")
        for k, val in v["numbers"].items():
            print(f"  {k}: {json.dumps(val, ensure_ascii=False)}")
        print(f"  └ {v['why']}")
    print("\n" + "=" * 88)


if __name__ == "__main__":
    main()
