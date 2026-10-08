#!/usr/bin/env python3
"""Put-Call 期权情绪抓取（B-6 免 key）：CBOE 按日 Market Statistics JSON → Data/raw/putcall_daily_*.csv

数据源（2026-10 已探明，国内直连、免 key、单请求 <1s）：
  https://cdn.cboe.com/data/us/options/market_statistics/daily/{YYYY-MM-DD}_daily_options
  非交易日/未发布返回 403/404（跳过）；JSON 含 ratios（六档 P/C 比率）+ 各产品 VOLUME。

与 scripts/build_putcall.py 的契约：输出 putcall_daily_*.csv
  date, total_ratio, index_ratio, equity_ratio, etp_ratio, vix_ratio, spx_ratio,
  call_vol, put_vol, call_oi, put_oi, note
（build 只消费前 7 列；OI 该端点不提供，留空；note 标记数据源）
build_putcall.py 合并基底（2006-2019 官方批量 CSV）+ 近期逐日 → Data/raw/putcall.csv（7 列全量）
再经 scripts/fetch_sentiment.py build_sentiment() 并入 sentiment.csv（putcall_total/putcall_equity/putcall_vix）。

用法：
  .venv/bin/python scripts/fetch_putcall.py --days 30     # 增量补最近 30 个交易日
  .venv/bin/python scripts/fetch_putcall.py --out Data/raw/putcall_daily_latest.csv
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_sentiment import RAW, fetch  # noqa: E402  复用直连 fetch 与 RAW 路径

BASE = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{d}_daily_options"
DEFAULT_OUT = RAW / "putcall_daily_latest.csv"

RATIO_KEYS = {
    "total_ratio": "TOTAL PUT/CALL RATIO",
    "index_ratio": "INDEX PUT/CALL RATIO",
    "equity_ratio": "EQUITY PUT/CALL RATIO",
    "etp_ratio": "EXCHANGE TRADED PRODUCTS PUT/CALL RATIO",
    "vix_ratio": "CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO",
    "spx_ratio": "SPX + SPXW PUT/CALL RATIO",
}


def fetch_day(d: date):
    """拉单日 JSON；非交易日/解析失败返回 None。"""
    try:
        text = fetch(BASE.format(d=d.isoformat()))
    except Exception:
        return None
    try:
        body = json.loads(text)
    except Exception:
        return None
    if not isinstance(body, dict) or "ratios" not in body:
        return None
    return body


def parse_row(d: date, body: dict) -> dict | None:
    """提取六档 P/C 比率 + 全市场成交量；比率缺失返回 None。"""
    ratios = {r.get("name"): r.get("value") for r in body.get("ratios", [])}
    row = {"date": d.isoformat()}
    for col, key in RATIO_KEYS.items():
        v = ratios.get(key)
        try:
            row[col] = float(v) if v is not None else ""
        except (TypeError, ValueError):
            row[col] = ""
    # 全市场成交量（SUM OF ALL PRODUCTS → VOLUME 行）
    vol = {"call_vol": "", "put_vol": ""}
    for sec in body.get("SUM OF ALL PRODUCTS", []):
        if sec.get("name") == "VOLUME":
            vol = {"call_vol": sec.get("call", ""), "put_vol": sec.get("put", "")}
    row.update(vol)
    row["call_oi"] = ""
    row["put_oi"] = ""
    row["note"] = "CBOE Daily Market Statistics JSON"
    # 六档全部缺失视为无数据日
    if not any(row[c] != "" for c in RATIO_KEYS):
        return None
    return row


def scan_recent(days: int, existing: set[str], throttle: float = 0.3) -> list[dict]:
    """从昨天往前回退，跳过周末与非交易日，直到收满 days 个新交易日。"""
    rows = []
    cursor = date.today() - timedelta(days=1)
    max_attempts = days * 2 + 15
    attempts = 0
    while len(rows) < days and attempts < max_attempts:
        attempts += 1
        if cursor.weekday() >= 5 or cursor.isoformat() in existing:
            cursor -= timedelta(days=1)
            continue
        body = fetch_day(cursor)
        if body is not None:
            row = parse_row(cursor, body)
            if row is not None:
                rows.append(row)
        cursor -= timedelta(days=1)
        time.sleep(throttle)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="CBOE Put-Call 比率 → Data/raw/putcall_daily_*.csv")
    ap.add_argument("--days", type=int, default=30, help="本次补拉交易天数（默认 30）")
    ap.add_argument("--out", type=str, default=str(DEFAULT_OUT), help="输出 CSV 路径")
    ap.add_argument("--no-build", action="store_true", help="只抓取，不跑 build_putcall + build_sentiment")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    existing = set()
    if out.exists():
        import pandas as pd
        old = pd.read_csv(out)
        existing = set(old["date"].astype(str))
    else:
        old = None

    new_rows = scan_recent(args.days, existing)
    if not new_rows:
        print("没有新数据（输出文件已最新）。")
        if old is not None:
            print(f"{out.name} 现含 {len(old)} 行")
        return

    import pandas as pd
    new = pd.DataFrame(new_rows)
    merged = pd.concat([old, new]).drop_duplicates(subset=["date"], keep="last").sort_values("date")
    merged.to_csv(out, index=False)
    last = merged.iloc[-1]
    print(f"{out.name}: {len(merged)} 行（{merged['date'].min()} → {merged['date'].max()}），本次新增 {len(new)} 行")
    print(f"  最新 {last['date']}: total={last['total_ratio']} equity={last['equity_ratio']} vix={last['vix_ratio']}")

    if not args.no_build:
        import subprocess
        subprocess.run([sys.executable, "scripts/build_putcall.py"], cwd=RAW.parent.parent, check=False)
        from fetch_sentiment import build_sentiment
        build_sentiment()
        print("已重建 putcall.csv 并并入 sentiment.csv")


if __name__ == "__main__":
    main()
