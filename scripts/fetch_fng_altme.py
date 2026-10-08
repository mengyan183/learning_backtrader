# -*- coding: utf-8 -*-
"""市场级 Fear&Greed 交叉校验源抓取（alternative.me，lookintobitcoin 同源）。

背景（Q1，2026-10-08）：
    Financial_freedom 仓库沉淀发现 lookintobitcoin.com 是 BTC 情绪全模型聚合站，
    但其官方 API 需订阅（api.lookintobitcoin.com/metrics 仅对订阅者开放）。
    lookintobitcoin 的 Fear&Greed 图数据源 = alternative.me 官方公开 API（免费、
    无需 key），因此以 alternative.me 作为「市场级恐慌贪婪」交叉校验源：
    - 主链：守猪待兔（fe.szdt.tech，个股级贪恐视图）
    - 校验：本文件抓取的市场级 FNG（BTC 市场整体情绪）

产出：Data/raw/fng_altme.csv（长表：date, value, value_classification）
    date 用 UTC 日期归一化（alternative.me 时间戳为 UTC 午夜，抓取时取当日）。

用法：
    .venv/bin/python scripts/fetch_fng_altme.py             # 追加当日
    .venv/bin/python scripts/fetch_fng_altme.py --limit 30  # 回补最近 N 天
退出码：0=成功；1=网络/解析失败（不改每日链 RC，遵循 putcall/news 块约定）。
"""
import argparse
import csv
import datetime
import os
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "Data", "raw", "fng_altme.csv")
API = "https://api.alternative.me/fng/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def fetch(limit):
    url = "%s?limit=%d" % (API, limit)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8")


def parse(body):
    import json
    d = json.loads(body)
    rows = []
    for row in d.get("data", []):
        ts = int(row.get("timestamp", 0))
        day = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
        rows.append([day, row.get("value", ""), row.get("value_classification", "")])
    return rows


def load_existing_dates():
    if not os.path.exists(OUT):
        return set()
    with open(OUT, newline="", encoding="utf-8") as f:
        return {r[0] for r in csv.reader(f) if r and r[0].startswith("20")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1,
                    help="抓取最近 N 条（默认 1=当日）")
    args = ap.parse_args()

    try:
        body = fetch(args.limit)
        rows = parse(body)
    except Exception as e:
        print("⚠️ fng_altme 抓取失败: %s" % e, file=sys.stderr)
        return 1

    if not rows:
        print("⚠️ fng_altme 返回空数据", file=sys.stderr)
        return 1

    existing = load_existing_dates()
    new_rows = [r for r in rows if r[0] not in existing]
    if not new_rows:
        print("fng_altme: 无新数据（最新 %s 已在库）" % rows[0][0])
        return 0

    header = ["date", "value", "value_classification"]
    write_header = not os.path.exists(OUT) or os.path.getsize(OUT) == 0
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(header)
        w.writerows(new_rows)
    print("fng_altme: 追加 %d 条（最新 %s = %s）→ %s" % (
        len(new_rows), new_rows[-1][0], new_rows[-1][1], OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
