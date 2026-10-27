#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MT-76 供数：BAA10Y 信用利差 → 带 available_date 的评测用 CSV（防 lookahead）。

产出 Data/raw/fred_baa10y.csv，三列：date,value,available_date
  - date          : FRED 观测日（observation_date）
  - value         : BAA10Y（穆迪 Baa 公司债收益率 − 10Y 国债，单位 %，默认 revision）
  - available_date: 该观测值"实际可得"的保守日期，供因子层 merge_asof(direction="backward")
                    对齐；🔴 禁止直接用观测日（那会把尚未发布的值提前 = lookahead）。

available_date 口径（2026-10-27 实测校准）：
  FRED BAA10Y 为 Daily，实测工作日 T+1 发布、跨周末 3~4 自然日（如周五观测周二补发）。
  全历史逐格真实首发日无法从现 API 端点取回（早期观测在任一当前 realtime 窗口都被
  钳到窗口起点），故采用任务书允许的「显式滞后 N 天（可配）」保守口径：
      available_date = date + lag_days（自然日）
  默认 lag_days=5：覆盖实测最大 4 天并留 1 天美国公共假日余量；宁可多藏 1 天，
  也不把未发布值提前。可用 --lag-days 调整。

🔴 只供评测（M2.2 观察池），不进合成权重；与大写 fred_BAA10Y.csv（H-065 主口径，
observation_date,BAA10Y 两列）互不影响，本脚本不动后者。

用法：.venv/bin/python scripts/fetch_baa10y_avail.py [--lag-days 5] [--debug]
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
RAW = os.path.join(REPO, "Data", "raw")

API_URL = ("https://api.stlouisfed.org/fred/series/observations"
           "?series_id=BAA10Y&api_key=%s&file_type=json&observation_start=1776-07-04"
           "&sort_order=asc")
GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAA10Y"
OUT = os.path.join(RAW, "fred_baa10y.csv")


def read_fred_key():
    """本地 FRED key：环境变量优先，其次 Data/fred_key（🔴 key 不入库、不回传）。"""
    env = os.environ.get("FRED_API_KEY", "").strip()
    if env:
        return env
    kf = os.path.join(REPO, "Data", "fred_key")
    if os.path.exists(kf):
        k = open(kf, encoding="utf-8").read().strip()
        if k:
            return k
    return None


def fetch_observations(key, debug=False):
    """返回 [(date_iso, value_float), ...] 升序；有 key 走 api 全历史，无 key 走免key CSV。"""
    if key:
        raw = urllib.request.urlopen(API_URL % key, timeout=30).read().decode("utf-8")
        obs = (json.loads(raw) or {}).get("observations", []) or []
        rows = [(o["date"], float(o["value"])) for o in obs
                if o.get("value", ".") not in (".", "", None)]
        if debug:
            print(f"[baa10y] api-key：{len(rows)} 行，首 {rows[0]}，尾 {rows[-1]}")
        return rows
    # 免 key 兜底（仅近段，与 fetch_fred.py 一致；本机有 key 不走此路）
    raw = urllib.request.urlopen(GRAPH_URL, timeout=25).read().decode("utf-8")
    rows = []
    for line in raw.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 2 and parts[1] not in (".", "", None):
            rows.append((parts[0], float(parts[1])))
    return rows


def build_rows(rows, lag_days):
    """纯逻辑：给定 [(date_iso, value_float), ...]，加 available_date=date+lag_days。

    返回 [(date, value, available_date)] 升序；🔴 available_date 恒 ≥ date（防 lookahead）。
    抽出便于离线单测，不触发网络。
    """
    lag = dt.timedelta(days=lag_days)
    out = []
    for d, v in sorted(rows, key=lambda r: r[0]):
        avail = (dt.date.fromisoformat(d) + lag).isoformat()
        out.append((d, float(v), avail))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lag-days", type=int, default=5,
                    help="available_date = 观测日 + N 自然日（默认 5，保守防 lookahead）")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    key = read_fred_key()
    rows = fetch_observations(key, args.debug)

    built = build_rows(rows, args.lag_days)
    os.makedirs(RAW, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("date,value,available_date\n")
        for d, v, avail in built:
            f.write(f"{d},{v:.4f},{avail}\n")

    n = len(built)
    print(f"✅ fred_baa10y.csv：{n} 个观测日（lag={args.lag_days} 自然日，"
          f"{'api-key' if key else '免key'}）")
    print(f"   观测区间 {built[0][0]} → {built[-1][0]}，"
          f"最新 available_date {built[-1][2]}")
    print("   口径：available_date=date+lag，因子层 merge_asof(backward,on=available_date)；"
          "禁止 reindex().ffill()")


if __name__ == "__main__":
    main()
