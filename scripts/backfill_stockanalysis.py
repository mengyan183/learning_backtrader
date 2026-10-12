#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stockanalysis.com 备用源补数工具（Nasdaq 数据滞后时的救援通道）。

背景（2026-10-13 数据停更事件）：
- Nasdaq API 历史数据在 2026-10-13 早上仍未发布 10-12（哥伦布日美股正常开市，
  多方核验 + CBOE vix3m 已有 10-12）；fetch.update_prices() 因此 0 新增。
- stockanalysis.com 免费 API 国内直连可用、无 key、数据当日更新，与本地
  10-09 历史对齐验证一致（YINN 25.27/2295284 全字段吻合）。

用法：
    python scripts/backfill_stockanalysis.py --dry-run   # 预览将补哪些行
    python scripts/backfill_stockanalysis.py             # 实际补缺（幂等）

语义：对 config.FETCH_SYMBOLS 每个标的，请求 history 后只取【本地缺失日期】
的行（本地 max(date) 之后），与 prices.csv 幂等合并。不覆盖已有数据。
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config

SA_API = "https://stockanalysis.com/api/symbol/s/{symbol}/history?range=30D&period=Daily"
PRICE_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume"]


def fetch_symbol(symbol, retries=3):
    url = SA_API.format(symbol=symbol)
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://stockanalysis.com/",
    }
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            last = exc
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{symbol} 备用源请求失败: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只预览不写盘")
    args = ap.parse_args()

    path = os.path.join(config.RAW_DIR, "prices.csv")
    symbols = config.FETCH_SYMBOLS
    import pandas as pd

    old = pd.DataFrame()
    if os.path.exists(path):
        old = pd.read_csv(path, dtype={"symbol": str}, parse_dates=["date"])
    else:
        print("prices.csv 不存在，先跑 fetch.update_prices() 初始化")
        return 2

    total_new = 0
    frames = []
    for sym in symbols:
        sub = old[old["symbol"] == sym] if not old.empty else pd.DataFrame()
        last_date = sub["date"].max() if not sub.empty else None
        data = fetch_symbol(sym)
        rows = data.get("data") or []
        added = 0
        for r in rows:
            d = pd.to_datetime(r["t"])
            if last_date is None or d > last_date:
                frames.append({
                    "date": d, "symbol": sym,
                    "open": float(r["o"]), "high": float(r["h"]),
                    "low": float(r["l"]), "close": float(r["c"]),
                    "volume": float(r.get("v") or 0),
                })
                added += 1
        if added:
            print(f"  {sym}: +{added} 行（最新 {rows[0]['t'] if rows else '-'}）")
        total_new += added
        time.sleep(0.3)

    if not frames:
        print("无缺失行可补（各标的数据均已最新）")
        return 0

    new = pd.DataFrame(frames)
    merged = pd.concat([old, new], ignore_index=True) if not old.empty else new
    merged = (merged.drop_duplicates(subset=["symbol", "date"], keep="last")
              .sort_values(["symbol", "date"]).reset_index(drop=True))
    if args.dry_run:
        print(f"[dry-run] 将新增 {total_new} 行（未写盘）")
        return 0
    merged.to_csv(path, index=False, encoding="utf-8")
    print(f"✅ 已补 {total_new} 行写入 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
