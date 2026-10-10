# -*- coding: utf-8 -*-
"""临时数据下载与可行性验证脚本（设计阶段用）。

数据源（2026-09-21 实测可用）：
  - Nasdaq 官方 historical API  → 9 个 ETF 的日线（拆股已复权口径）
  - CBOE cdn                    → VIX / VIX3M 历史
  - CBOE Put/Call CSV           → 仅到 2019-10，已停更（见输出报告）

用法：python tmp_fetch_data.py
"""
import csv
import io
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROXY = os.environ.get("FG_PROXY", "http://10.30.6.49:9090")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data", "raw")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

ETFS = ["TQQQ", "SOXL", "UPRO", "QQQ", "SOXX", "SMH", "SPY", "RSP", "IWM"]
LEVERAGED = {"TQQQ": "QQQ", "SOXL": "SOXX", "UPRO": "SPY"}

CBOE_FILES = {
    "vix.csv": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
    "vix3m.csv": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv",
    "putcall_total.csv": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv",
    "putcall_equity.csv": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv",
}


def opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handlers = [urllib.request.HTTPSHandler(context=ctx)]
    # FG_PROXY 显式设为空字符串（如 Mac 本地直连）时跳过代理，避免公司代理不可达挂死
    if PROXY:
        handlers.insert(0, urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    return urllib.request.build_opener(*handlers)


OP = opener()


def get_bytes(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with OP.open(req, timeout=35) as r:
                return r.read()
        except Exception as exc:
            if i == retries - 1:
                raise
            time.sleep(2)
    return b""


# ---------------------------------------------------------------- Nasdaq
def fetch_nasdaq(symbol):
    url = (
        "https://api.nasdaq.com/api/quote/%s/historical"
        "?assetclass=etf&fromdate=2010-01-01&limit=9999" % urllib.parse.quote(symbol)
    )
    data = json.loads(get_bytes(url).decode("utf-8"))
    rows = ((data.get("data") or {}).get("tradesTable") or {}).get("rows") or []
    if not rows:
        return None
    recs = []
    for r in rows:
        try:
            recs.append(
                {
                    "date": pd.to_datetime(r["date"], format="%m/%d/%Y"),
                    "open": float(r["open"].replace(",", "")),
                    "high": float(r["high"].replace(",", "")),
                    "low": float(r["low"].replace(",", "")),
                    "close": float(r["close"].replace(",", "").replace("$", "")),
                    "volume": float(r["volume"].replace(",", "") or 0),
                }
            )
        except (ValueError, KeyError, AttributeError):
            continue
    df = pd.DataFrame(recs).sort_values("date").reset_index(drop=True)
    return df


# ---------------------------------------------------------------- CBOE
def fetch_cboe_csv(url):
    raw = get_bytes(url).decode("utf-8", errors="replace")
    lines = [l for l in raw.splitlines() if l.strip()]
    # 跳过免责声明等非数据行
    start = 0
    for i, l in enumerate(lines):
        if l.upper().startswith("DATE,") or l.split(",")[0].strip().upper() == "DATE":
            start = i
            break
    return list(csv.reader(io.StringIO("\n".join(lines[start:]))))


def parse_cboe_index(url):
    rows = fetch_cboe_csv(url)
    if not rows:
        return None
    hdr = [h.strip().lower() for h in rows[0]]
    out = []
    for r in rows[1:]:
        if len(r) < len(hdr):
            continue
        try:
            rec = {"date": pd.to_datetime(r[0].strip(), format="%m/%d/%Y")}
            for k, v in zip(hdr[1:], r[1:]):
                rec[k] = float(v)
            out.append(rec)
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(out).sort_values("date").reset_index(drop=True)


def parse_putcall(url):
    """CBOE Put/Call 文件格式：注释行 + 数据行 DATE,CALLS,PUTS,TOTAL,RATIO"""
    rows = fetch_cboe_csv(url)
    out = []
    for r in rows:
        if len(r) < 5:
            continue
        try:
            out.append(
                {
                    "date": pd.to_datetime(r[0].strip(), format="%m/%d/%Y"),
                    "calls": float(r[1]),
                    "puts": float(r[2]),
                    "total": float(r[3]),
                    "put_call_ratio": float(r[4]),
                }
            )
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(out).sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------- 分析
def health_check(prices):
    print("\n=== 数据健康检查 ===")
    print("%-7s %6s %-12s %-12s %9s %-12s" % ("symbol", "rows", "start", "end", "max|chg|", "date"))
    for sym in sorted(prices["symbol"].unique()):
        s = prices[prices["symbol"] == sym].sort_values("date")
        chg = s["close"].pct_change()
        if chg.notna().any():
            idx = chg.abs().idxmax()
            print(
                "%-7s %6d %-12s %-12s %8.2f%% %-12s"
                % (
                    sym,
                    len(s),
                    s["date"].min().strftime("%Y-%m-%d"),
                    s["date"].max().strftime("%Y-%m-%d"),
                    abs(chg.loc[idx]) * 100,
                    s["date"].loc[idx].strftime("%Y-%m-%d"),
                )
            )

    print("\n=== 异常跳变（|单日| > 40%，杠杆 ETF 必属异常）===")
    hits = 0
    for sym in sorted(prices["symbol"].unique()):
        s = prices[prices["symbol"] == sym].sort_values("date").reset_index(drop=True)
        chg = s["close"].pct_change()
        for i in chg[chg.abs() > 0.40].index:
            print("  %-6s %s %+8.2f%%" % (sym, s["date"].loc[i].strftime("%Y-%m-%d"), chg.loc[i] * 100))
            hits += 1
    print("  无异常跳变，全部标的通过" if hits == 0 else "  共 %d 处，需人工核对" % hits)


def decay_analysis(prices):
    """杠杆 ETF 损耗分析：实际收益 vs 标的指数 N 倍理论收益。"""
    print("\n=== 杠杆 ETF 损耗分析（vs 标的 3 倍理论收益）===")
    print("%-6s %-6s %6s %12s %12s %12s %10s" % ("lever", "under", "years", "杠杆ETF累计", "3倍理论", "损耗(pp)", "年化损耗"))
    rows = []
    for lev, und in LEVERAGED.items():
        a = prices[prices["symbol"] == lev].sort_values("date").set_index("date")["close"]
        b = prices[prices["symbol"] == und].sort_values("date").set_index("date")["close"]
        j = pd.concat([a.rename("lev"), b.rename("und")], axis=1).dropna()
        if len(j) < 200:
            continue
        lev_cum = j["lev"].iloc[-1] / j["lev"].iloc[0] - 1
        und_ret = j["und"].pct_change().dropna()
        theo = float((1 + 3 * und_ret).prod() - 1)  # 每日 3 倍再平衡的理论收益
        years = len(j) / 252.0
        gap = (lev_cum - theo) * 100
        ann = ((1 + lev_cum) ** (1 / years) - 1 - ((1 + theo) ** (1 / years) - 1)) * 100
        rows.append((lev, und, years, lev_cum, theo, gap, ann))
        print(
            "%-6s %-6s %6.2f %11.1f%% %11.1f%% %11.1f %9.2f%%"
            % (lev, und, years, lev_cum * 100, theo * 100, gap, ann)
        )

    print("\n=== 波动率 vs 损耗（按年度）===")
    print("%-6s %6s %12s %12s %12s" % ("lever", "year", "标的年化波动", "杠杆ETF收益", "3倍理论收益"))
    for lev, und in LEVERAGED.items():
        a = prices[prices["symbol"] == lev].sort_values("date").set_index("date")["close"]
        b = prices[prices["symbol"] == und].sort_values("date").set_index("date")["close"]
        j = pd.concat([a.rename("lev"), b.rename("und")], axis=1).dropna()
        for y, g in j.groupby(j.index.year):
            if len(g) < 100:
                continue
            lev_ret = g["lev"].iloc[-1] / g["lev"].iloc[0] - 1
            r = g["und"].pct_change().dropna()
            theo = float((1 + 3 * r).prod() - 1)
            vol = float(r.std() * np.sqrt(252))
            print(
                "%-6s %6d %11.1f%% %11.1f%% %11.1f%%"
                % (lev, y, vol * 100, lev_ret * 100, theo * 100)
            )


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("=== 下载 Nasdaq ETF 日线 ===")
    frames = []
    for sym in ETFS:
        try:
            df = fetch_nasdaq(sym)
            if df is None or df.empty:
                print("  %-6s 无数据" % sym)
                continue
            df.insert(1, "symbol", sym)
            frames.append(df)
            print(
                "  %-6s %5d 行  %s -> %s"
                % (sym, len(df), df["date"].min().strftime("%Y-%m-%d"), df["date"].max().strftime("%Y-%m-%d"))
            )
        except Exception as exc:
            print("  %-6s 失败 %s" % (sym, str(exc)[:70]))
        time.sleep(1)

    if not frames:
        print("未取得任何 ETF 数据，终止")
        return
    prices = pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"])
    prices.to_csv(os.path.join(OUT_DIR, "prices.csv"), index=False, encoding="utf-8")
    print("  -> prices.csv  %d 行" % len(prices))

    print("\n=== 下载 CBOE 指数与 Put/Call ===")
    for fname, url in CBOE_FILES.items():
        try:
            if fname.startswith("vix"):
                df = parse_cboe_index(url)
            else:
                df = parse_putcall(url)
            if df is None or df.empty:
                print("  %-20s 无数据" % fname)
                continue
            df.to_csv(os.path.join(OUT_DIR, fname), index=False, encoding="utf-8")
            print(
                "  %-20s %5d 行  %s -> %s"
                % (fname, len(df), df["date"].min().strftime("%Y-%m-%d"), df["date"].max().strftime("%Y-%m-%d"))
            )
        except Exception as exc:
            print("  %-20s 失败 %s" % (fname, str(exc)[:70]))

    health_check(prices)
    decay_analysis(prices)

    print("\n=== 数据源可用性小结 ===")
    print("  Nasdaq 官方 API      : 9 个 ETF 可用，10 年日线，拆股已复权口径")
    print("  CBOE VIX/VIX3M       : 可用（1990/2009 起）")
    print("  CBOE Put/Call        : 文件止于 2019-10，已停更 —— 需替代方案")
    print("  yfinance             : 公司代理出口 IP 被 Yahoo 持续限流，不可用")
    print("  东财/新浪/腾讯/Stooq : 分别 502 / 403 / 数据截断 / anti-bot，均不可用")


if __name__ == "__main__":
    main()
