#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FRED 免 key 宏观数据接入（2026-10-11，L3.x 观察项）。

补强点：fed 因子当前数据源 fedwatch.csv 仅 2026-10 起（CME FedWatch 会话抓取，
历史不足）；FRED DFF（有效联邦基金利率）1954 年至今官方全历史，作为 fed 因子
level 分量的**官方长期数据源 + 交叉校验基准**。

通道：fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES> 免 API key 直连 CSV
（美国站点，直连失败自动走本地代理 7890，与 fetch_stablecoin_usage 同模式）。
有本地 key（Data/fred_key 或环境变量 FRED_API_KEY）时自动升级为官方
api.stlouisfed.org 全历史通道（MT-27：BAMLH0A0HYM2 免 key 只有近 3 年窗口，
key 可抓 1996 至今）。🔴 key 只存本地，不入库、不随 fg-sync 回传。

产出：
  Data/raw/fred_DFF.csv      observation_date,DFF     （有效联邦基金利率 %）
  Data/raw/fred_T10Y2Y.csv   observation_date,T10Y2Y  （10Y-2Y 国债利差 %）
  Data/raw/fred_DGS10.csv    observation_date,DGS10   （10Y 国债收益率 %）
  Data/raw/fred_BAMLH0A0HYM2.csv  observation_date,BAMLH0A0HYM2 （HY OAS %）
增量 append，同日期幂等覆盖；仅入 Data/raw，**不改任何生产计算**。

用法：.venv/bin/python scripts/fetch_fred.py [--series DFF,T10Y2Y] [--debug]
"""
import argparse
import json
import os
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
RAW = os.path.join(REPO, "Data", "raw")

BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s"
API_URL = ("https://api.stlouisfed.org/fred/series/observations"
           "?series_id=%s&api_key=%s&file_type=json&observation_start=1776-07-04")
PROXY = "http://127.0.0.1:7890"
SERIES = {
    "DFF": "有效联邦基金利率(%)，1954-至今，fed 因子 level 分量官方源",
    "T10Y2Y": "10Y-2Y 国债利差(%)，2000-至今，term/宏观观察指标",
    "DCOILWTICO": "WTI 原油现货价(美元/桶)，1986-至今，原油候选因子前置数据源",
    "DCOILBRENTEU": "Brent 原油现货价(美元/桶)，1987-至今，原油候选因子前置数据源（可选）",
    "DGS10": "10Y 国债收益率(%)，1962-至今，H-065 归因控制量（利率驱动检验）",
    "BAMLH0A0HYM2": "高收益公司债 OAS(%)，2023-10 起（FRED 该 id 于 ICE 数据迁移后重新发布，官方 observation_start=2023-10-16，非 1996 起），H-065 双口径主口径跨资产所需",
    "BAA10Y": "穆迪 Baa 公司债收益率(%)，1986-至今，HY 债成本更长历史代理（H-065 数据依赖，2026-10-16 Windows 指定）",
}


def read_fred_key():
    """读本地 FRED API key：环境变量 FRED_API_KEY 优先，其次 Data/fred_key 文件。
    🔴 key 只存本地（Data/ 不入库、不随 fg-sync 回传）。无 key 返回 None。"""
    env = os.environ.get("FRED_API_KEY", "").strip()
    if env:
        return env
    kf = os.path.join(REPO, "Data", "fred_key")
    if os.path.exists(kf):
        k = open(kf, encoding="utf-8").read().strip()
        if k:
            return k
    return None


def fetch_series(sid, debug=False):
    """下载 FRED 序列。有本地 key 走官方 API（全历史，observation_start=1776）；
    无 key 走免 key CSV 直连（直连失败自动走代理）。返回 (lines, source)。"""
    key = read_fred_key()
    if key:
        url = API_URL % (sid, key)
        try:
            raw = urllib.request.urlopen(url, timeout=25).read().decode("utf-8")
            obs = (json.loads(raw) or {}).get("observations", []) or []
            lines = ["observation_date,%s" % sid] + [
                "%s,%s" % (o.get("date"), o.get("value"))
                for o in obs
                if o.get("value", ".") not in (".", "", None)
            ]
            if debug:
                print(f"[fred] {sid} 走 api-key：{len(lines)-1} 行，"
                      f"首行 {lines[1]}，尾行 {lines[-1]}")
            return lines, "api-key"
        except Exception as e:
            if debug:
                print(f"[fred] {sid} api-key 失败: {e}")
            raise SystemExit(f"FRED {sid} 下载失败（key 通道不可达）")
    url = BASE % sid
    for label, opener in (
        ("direct", urllib.request.build_opener()),
        ("proxy", urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))),
    ):
        try:
            resp = opener.open(url, timeout=20)
            raw = resp.read().decode("utf-8")
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            if len(lines) < 2 or not lines[1].split(",")[1]:
                raise ValueError("空数据")
            if debug:
                print(f"[fred] {sid} 走 {label}：{len(lines)-1} 行，"
                      f"尾行 {lines[-1]}")
            return lines, label
        except Exception as e:
            if debug:
                print(f"[fred] {sid} {label} 失败: {e}")
    raise SystemExit(f"FRED {sid} 下载失败（直连+代理均不可达）")


def merge_csv(sid, lines):
    """增量合并：header + 按 observation_date 幂等（同日期后行覆盖）。"""
    out = os.path.join(RAW, f"fred_{sid}.csv")
    fresh = {}
    for l in lines[1:]:
        d, v = l.split(",")[0], l.split(",")[1]
        if v not in (".", ""):
            fresh[d] = v
    if os.path.exists(out):
        old = open(out, encoding="utf-8").read().strip().splitlines()
        for l in old[1:]:
            d, v = l.split(",")[0], l.split(",")[1]
            if v not in (".", ""):
                fresh.setdefault(d, v)
    with open(out, "w", encoding="utf-8") as f:
        f.write("observation_date,%s\n" % sid)
        for d in sorted(fresh):
            f.write(f"{d},{fresh[d]}\n")
    return len(fresh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="DFF,T10Y2Y")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    os.makedirs(RAW, exist_ok=True)
    for sid in [s.strip() for s in args.series.split(",") if s.strip()]:
        if sid not in SERIES:
            raise SystemExit(f"未知系列 {sid}（可用：{list(SERIES)}）")
        lines, src = fetch_series(sid, args.debug)
        n = merge_csv(sid, lines)
        print(f"✅ fred_{sid}.csv：{n} 个观测日（来源 {src}，{SERIES[sid]}）")


if __name__ == "__main__":
    main()
