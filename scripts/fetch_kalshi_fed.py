#!/usr/bin/env python3
"""Kalshi KXFED 利率决议概率抓取（FOMC 加息/降息概率第二源）。

数据源：Kalshi Trade API v2（https://external-api.kalshi.com/trade-api/v2）
- 公开市场数据免 key（trading 才需要签名）；国内直连不可达，必须走代理 7890
- KXFED 系列按 FOMC 会议分事件（event_ticker 如 KXFED-26OCT），每个目标利率
  档位一张二元合约：YES = "会议后目标利率上限 ≥ strike%"
- 概率取 yes 买/卖中间价；档位差 → hold / hike / ease（口径与 CME FedWatch 对齐）

流程：
1. 翻页拉取全部 status=open 的 KXFED 合约（cursor 分页）
2. 取 close_time 最早的未来事件作为"下一次会议"
3. 当前上限 c = 使 P(≥s) ≥ 0.90 的最大档位 s
   → ease = 1 - P(≥c)；hike = P(≥c+0.25)；hold = P(≥c) - P(≥c+0.25)
4. 追加写 Data/raw/kalshi_fed.csv（同一天幂等，覆盖当日行）

用法:
  .venv/bin/python scripts/fetch_kalshi_fed.py          # 抓取并写 CSV
  .venv/bin/python scripts/fetch_kalshi_fed.py --debug   # 打印解析明细
  .venv/bin/python scripts/fetch_kalshi_fed.py --dry-run # 只解析不写文件

输出: Data/raw/kalshi_fed.csv（追加行，同一天幂等）
  date | meeting | ease_pct | hold_pct | hike_pct | src
实测（2026-10-14）：KXFED-26OCT 加息 21.0% ≈ CME FedWatch 22.7%（差 1.7pp）
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
RAW = REPO / "Data" / "raw"
OUT = RAW / "kalshi_fed.csv"

BASE = "https://external-api.kalshi.com/trade-api/v2"
PROXY = "http://127.0.0.1:7890"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")
P90 = 0.90          # "当前上限"置信阈值：P(≥c) ≥ 0.90
STEP = 0.25         # 联邦基金利率步长


def _fetch(url, proxy=PROXY):
    """GET 一个 Kalshi 端点（走代理），返回 JSON dict；失败抛异常。"""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    with opener.open(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_kxfed_markets(proxy=PROXY):
    """翻页拉取全部开放 KXFED 合约列表。"""
    markets, cursor = [], None
    while True:
        url = "%s/markets?series_ticker=KXFED&status=open&limit=200" % BASE
        if cursor:
            url += "&cursor=%s" % cursor
        data = _fetch(url, proxy)
        markets += data.get("markets", [])
        cursor = data.get("cursor")
        if not cursor:
            break
    return markets


def parse_kxfed(markets, debug=False):
    """从合约列表解析下一次会议的概率。

    返回 dict(date, meeting, ease_pct, hold_pct, hike_pct) 或 None（数据不足）。
    """
    # 按事件分组
    events = {}
    for m in markets:
        events.setdefault(m.get("event_ticker"), []).append(m)

    # 下一次会议 = close_time 最早者（Kalshi 只开放未来事件）
    best = None
    for ticker, ms in events.items():
        closes = [m.get("close_time") or m.get("expected_expiration_time")
                  for m in ms]
        closes = [c for c in closes if c]
        if not closes:
            continue
        close = min(closes)
        if best is None or close < best[1]:
            best = (ticker, close, ms)
    if best is None:
        return None
    ticker, close, ms = best

    # P(≥s) = yes 买/卖中间价（缺价时回退 last_price）
    probs = {}
    for m in ms:
        strike = m.get("floor_strike")
        if strike is None:
            continue
        s = float(strike)
        bid, ask = m.get("yes_bid_dollars"), m.get("yes_ask_dollars")
        if bid is not None and ask is not None and bid != "" and ask != "":
            mid = (float(bid) + float(ask)) / 2.0
        else:
            mid = float(m.get("last_price_dollars") or 0.0)
        probs[s] = mid

    strikes = sorted(probs)
    if len(strikes) < 2:
        if debug:
            print("[kalshi] %s: 有效档位不足(%d)" % (ticker, len(strikes)))
        return None

    # 当前上限 c = P(≥c) ≥ 0.90 的最大档位
    c = None
    for s in strikes:
        if probs[s] >= P90:
            c = s
        else:
            break
    if c is None:
        if debug:
            print("[kalshi] %s: 无 P≥%.2f 的档位，无法确定当前上限" % (ticker, P90))
        return None

    p_at_c = probs.get(c, 0.0)
    p_above = probs.get(round(c + STEP, 4), 0.0)
    ease = max(0.0, 1.0 - p_at_c)
    hike = max(0.0, min(1.0, p_above))
    hold = max(0.0, min(1.0, p_at_c - p_above))
    total = ease + hold + hike
    if total <= 0 or total > 1.001:
        if debug:
            print("[kalshi] %s: 概率和异常(%.3f)" % (ticker, total))
        return None

    meeting = close[:10]  # YYYY-MM-DD（UTC）
    out = {
        "date": dt.date.today().isoformat(),
        "meeting": meeting,
        "ease_pct": round(ease * 100, 1),
        "hold_pct": round(hold * 100, 1),
        "hike_pct": round(hike * 100, 1),
        "src": "kalshi-kxfed",
    }
    if debug:
        print("[kalshi] 事件=%s 会议=%s 当前上限=%.2f%%" % (ticker, meeting, c))
        for s in strikes:
            print("[kalshi]   P(上限≥%.2f) = %.4f" % (s, probs[s]))
        print("[kalshi] ease=%.1f%% hold=%.1f%% hike=%.1f%%" %
              (out["ease_pct"], out["hold_pct"], out["hike_pct"]))
    return out


def append_csv(row, out=OUT):
    """追加一行，同一天幂等（覆盖当日已有行）。"""
    RAW.mkdir(parents=True, exist_ok=True)
    header = "date,meeting,ease_pct,hold_pct,hike_pct,src\n"
    lines = []
    if out.exists():
        lines = out.read_text(encoding="utf-8").splitlines()
    # 去掉表头与同日旧行
    kept = [ln for ln in lines if ln and not ln.startswith("date,")
            and not ln.startswith(row["date"] + ",")]
    with open(out, "w", encoding="utf-8") as f:
        f.write(header)
        if kept:
            f.write("\n".join(kept) + "\n")
        f.write("%(date)s,%(meeting)s,%(ease_pct)s,%(hold_pct)s,"
                "%(hike_pct)s,%(src)s\n" % row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        markets = fetch_kxfed_markets()
    except Exception as e:  # 网络/解析失败：仅告警，不覆盖旧数据
        print("[kalshi] 抓取失败: %s" % e)
        return 2
    row = parse_kxfed(markets, debug=args.debug)
    if row is None:
        print("[kalshi] 数据不足，未写入（保留旧数据）")
        return 2
    if not args.dry_run:
        append_csv(row)
        print("[kalshi] 已写入 %s: %s meeting=%s ease=%.1f hold=%.1f hike=%.1f"
              % (OUT, row["date"], row["meeting"], row["ease_pct"],
                 row["hold_pct"], row["hike_pct"]))
    else:
        print("[kalshi] dry-run: %s" % row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
