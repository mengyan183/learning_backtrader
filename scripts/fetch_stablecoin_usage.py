# -*- coding: utf-8 -*-
"""B-10 / H-034 稳定币「使用效率」数据链路（免 key）。

指标（口径写明，2026-10-10 定案）：
- usage_efficiency = USDC 现货市场成交量 / 流通市值（CoinGecko total_volumes / market_caps）
- 代理口径：CEX 现货成交额近似「链上使用活跃度」（免费无 key 最接近 H-034
  「链上月交易量 / USDC 流通量」的可复现代理；流通量侧用 DefiLlama 交叉校验）
- 30 日滚动均值平滑月度化 → usage_30d（对齐 H-034「链上月交易量」的月度语义）

数据源：
- 主源 CoinGecko /coins/usd-coin/market_chart（365 天，免费档，需代理 7890）
- 校验源 DefiLlama stablecoins.llama.fi（当前流通量，直连）

用法：
  .venv/bin/python scripts/fetch_stablecoin_usage.py [--days 365]
"""
import argparse
import csv
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DATA_DIR = REPO / "Data" / "raw"
PROXY = "http://127.0.0.1:7890"
CG_URL = ("https://api.coingecko.com/api/v3/coins/usd-coin/"
          "market_chart?vs_currency=usd&days={days}")
DL_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=true"


def fetch(url: str, proxy: bool = False, timeout: int = 30) -> str:
    """下载文本；proxy=True 走本地代理 7890（海外端点）。"""
    handler = urllib.request.ProxyHandler(
        {"http": PROXY, "https": PROXY}) if proxy else urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers={"User-Agent": "fg-b10/0.1"})
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def fetch_cg(days: int) -> dict:
    """CoinGecko 优先直连，失败回退代理 7890。"""
    url = CG_URL.format(days=days)
    try:
        return json.loads(fetch(url, proxy=False))
    except Exception:
        return json.loads(fetch(url, proxy=True))


def build_usage(rows: list) -> list:
    """rows=[(ts_ms, mcap, volume)] → 日频 usage_ratio + 30 日滚动均值。

    usage_ratio_t = volume_t / mcap_t（当日成交量 / 流通市值）
    usage_30d_t   = 近 30 日 usage_ratio 均值（月度化，对齐 H-034）
    """
    recs = []
    for ts, mcap, vol in rows:
        if not mcap or mcap <= 0:
            continue
        ratio = vol / mcap if vol else 0.0
        recs.append((ts, mcap, vol, ratio))
    out = []
    for i, (ts, mcap, vol, ratio) in enumerate(recs):
        window = [r[3] for r in recs[max(0, i - 29): i + 1]]
        usage_30d = sum(window) / len(window)
        out.append((ts, mcap, vol, ratio, usage_30d))
    return out


def cross_check_dl(cg_mcap: float) -> str:
    """DefiLlama USDC 流通量交叉校验（直连；失败返回说明不阻塞）。"""
    try:
        d = json.loads(fetch(DL_URL, proxy=False))
        usdc = next((c for c in d["peggedAssets"] if c.get("symbol") == "USDC"), None)
        dl = usdc["circulating"]["peggedUSD"] if usdc else None
        if dl:
            diff = (cg_mcap - dl) / dl * 100
            return ("DefiLlama 流通量 %.2fB vs CoinGecko 市值 %.2fB，偏差 %.2f%%"
                    % (dl / 1e9, cg_mcap / 1e9, diff))
        return "DefiLlama 未取到 USDC 流通量"
    except Exception as e:
        return "DefiLlama 校验失败（%s），不阻塞" % type(e).__name__


def main():
    p = argparse.ArgumentParser(description="稳定币使用效率数据链路（B-10/H-034）")
    p.add_argument("--days", type=int, default=365)
    args = p.parse_args()

    g = fetch_cg(args.days)
    prices = g.get("prices", [])
    mcaps = g.get("market_caps", [])
    vols = g.get("total_volumes", [])
    if not (prices and mcaps and vols):
        print("CoinGecko 返回为空（网络或限频），请检查代理 7890 后重试")
        return 2

    # 三序列按时间戳对齐（同长度，ts 一致）
    rows = []
    for (ts, _), (_ts, mcap), (_vts, vol) in zip(prices, mcaps, vols):
        rows.append((ts, mcap, vol))

    out = build_usage(rows)
    # 同日去重（CoinGecko 时间戳跨 UTC 日界会产生同日两条）：保留最后一条
    seen = {}
    for rec in out:
        iso = __import__("datetime").datetime.utcfromtimestamp(rec[0] / 1000).date().isoformat()
        seen[iso] = rec
    dedup = [(__import__("datetime").datetime.utcfromtimestamp(rec[0] / 1000).date().isoformat(), rec[1], rec[2], rec[3], rec[4])
             for rec in seen.values()]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / "stablecoin_usage.csv"
    with open(dest, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "mcap", "volume", "usage_ratio", "usage_30d"])
        for iso, mcap, vol, ratio, u30 in dedup:
            w.writerow([iso, "%.2f" % mcap, "%.2f" % vol,
                        "%.6f" % ratio, "%.6f" % u30])

    last = out[-1]
    print("稳定币使用效率已落盘：%s（%d 日）" % (dest, len(out)))
    print("最新 %s：mcap %.2fB / volume %.2fB / ratio %.6f / 30d %.6f" % (
        __import__("datetime").datetime.utcfromtimestamp(last[0] / 1000).date().isoformat(),
        last[1] / 1e9, last[2] / 1e9, last[3], last[4]))
    print("交叉校验：", cross_check_dl(last[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
