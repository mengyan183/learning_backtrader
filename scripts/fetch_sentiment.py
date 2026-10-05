#!/usr/bin/env python3
"""情绪子信号数据接入（E1）：VIX 情绪代理 + 加密资金费率

数据源（可用性已探明，2026-10）：
- CBOE VIX 历史 CSV（cdn.cboe.com，1990 起全历史，国内直连可用）→ 同步 Data/raw/vix_history.csv
- OKX 资金费率（www.okx.com，国内直连 307/超时，走本地代理 7890）→ Data/raw/funding_rate.csv
- Put-Call 比率：CBOE 需订阅端点，暂用 VIX 水平/变化率作为期权情绪代理（记入 docs/roadmap.md）
- 新闻情绪：免费源需 API key，暂缓

产物：Data/raw/sentiment.csv（date, vix, vix_chg, funding_btc, funding_eth）
用法：.venv/bin/python scripts/fetch_sentiment.py
"""
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data"
RAW = DATA / "raw"
PROXY = "http://127.0.0.1:7890"

VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
OKX_URLS = {
    "funding_btc": "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
    "funding_eth": "https://www.okx.com/api/v5/public/funding-rate?instId=ETH-USDT-SWAP",
}


def fetch(url: str, proxy: bool = False, timeout: int = 15) -> str:
    """下载文本；proxy=True 走本地代理（海外端点）。"""
    handler = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}) if proxy else urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def sync_vix():
    """CBOE VIX 全历史 → vix_history.csv（并打印最新值）。"""
    import pandas as pd
    text = fetch(VIX_URL)
    df = pd.read_csv(__import__("io").StringIO(text))
    df["date"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y").dt.date
    df = df[["date", "CLOSE"]].rename(columns={"CLOSE": "vix"}).dropna().sort_values("date")
    df.to_csv(RAW / "vix_history.csv", index=False)
    print(f"VIX 同步: {df['date'].min()} → {df['date'].max()}，{len(df)} 行，最新 {df['vix'].iloc[-1]:.2f}")


def sync_funding(proxy: bool = True):
    """OKX 最新资金费率（8h 周期×3=日频近似）。代理不通则跳过并提示。"""
    import json
    import pandas as pd
    rows = {}
    ok = False
    for col, url in OKX_URLS.items():
        try:
            body = json.loads(fetch(url, proxy=proxy))
            if body.get("code") == "0" and body["data"]:
                rows[col] = float(body["data"][0]["fundingRate"]) * 100  # 转 %
                ok = True
        except Exception as e:
            print(f"  {col}: 失败 {type(e).__name__}: {e}")
    if not ok:
        print("资金费率获取失败：若为网络原因，检查本地代理 7890 是否运行")
        return
    today = pd.Timestamp.today().date()
    hist = pd.read_csv(RAW / "funding_rate.csv", parse_dates=["date"]) if (RAW / "funding_rate.csv").exists() else pd.DataFrame(columns=["date", "funding_btc", "funding_eth"])
    for col in ("funding_btc", "funding_eth"):
        hist.loc[hist["date"].astype(str) == str(today), col] = rows.get(col)
    new = pd.DataFrame({"date": [pd.Timestamp(today)], **{c: [rows.get(c)] for c in rows}})
    hist = pd.concat([hist, new]).drop_duplicates(subset=["date"], keep="last").sort_values("date")
    hist.to_csv(RAW / "funding_rate.csv", index=False)
    print(f"资金费率更新: {today} BTC {rows.get('funding_btc')}% ETH {rows.get('funding_eth')}%")


def build_sentiment():
    """合并 vix_history + funding_rate → Data/raw/sentiment.csv（日频）"""
    import pandas as pd
    vix = pd.read_csv(RAW / "vix_history.csv", parse_dates=["date"])
    vix["vix_chg"] = vix["vix"].pct_change() * 100
    fr = pd.read_csv(RAW / "funding_rate.csv", parse_dates=["date"]) if (RAW / "funding_rate.csv").exists() else None
    out = vix
    if fr is not None:
        out = out.merge(fr, on="date", how="left")
    out.to_csv(RAW / "sentiment.csv", index=False)
    print(f"sentiment.csv: {len(out)} 行 ({out['date'].min().date()} → {out['date'].max().date()})")


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    sync_vix()
    sync_funding()
    build_sentiment()
