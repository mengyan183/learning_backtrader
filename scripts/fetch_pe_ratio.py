#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓 S&P 500 市盈率（月度历史）→ `Data/raw/sp500_pe.csv`（C2 ERP 估值锚用）。

【为什么需要】
C2「ERP 估值锚」= `1/PE − 10Y` 分位，用来回答「现在贵不贵」✗。
但 **FRED 没有 PE 系列** ✗（只有 10Y / DGS10），仓库里也没有任何 PE 历史 ✗
⇒ 必须先解决数据源 ✓。

【选型（2026-10-30）】

| 源 | 历史深度 | 结论 |
|---|---|---|
| **multpl.com** S&P500 PE（月度表） | **1871 起** | ✅ 选它 |
| Shiller `ie_data.xls` | 1871 起 | 需 xlrd + 多 sheet 解析 ✗ 绕 |
| FRED | 无 PE 系列 | ✗ |
| yfinance `^GSPC.info` | 仅当前值 | ✗ 无历史 |
| 富途 `pe_ttm_ratio` | 个股快照 | 只能逐日自建，攒 2~3 年才有分位意义 ✗ |

⚠️ 页面抓取**天然脆弱** ✗ —— multpl 改版即失效 ✓。
本脚本因此**只做一件事**：解析失败就**明确报错**（不静默产出空文件 ✗），
并在 stdout 打印实际拿到的行数与首末日期，便于一眼判断是否退化 ✓。

【用法】
    python scripts/fetch_pe_ratio.py
    python scripts/fetch_pe_ratio.py --dry-run
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402

URL = "https://www.multpl.com/s-p-500-pe-ratio/table/by-month"
OUT = os.path.join(config.RAW_DIR, "sp500_pe.csv")
#: 抓取走本地代理（Mac 上 Clash 7890）✓ —— 空串 = 直连 ✓
PROXY = os.environ.get("FG_LLM_PROXY", "http://127.0.0.1:7890")


def _get(url):
    """取网页（可选走代理）✓ —— 只做 GET，不改全局状态 ✓。"""
    import urllib.request
    handlers = []
    if PROXY:
        handlers.append(urllib.request.ProxyHandler(
            {"http": PROXY, "https": PROXY}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; fg-system/1.0)"})
    with opener.open(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_multpl(html):
    """解析 multpl 的 by-month 表 ⇒ `DataFrame[date, pe]` ✓。

    ⚠️ 只认「两列：日期 + 数值」的表 ✗ —— 页面结构变了就抛错，
    不猜、不返回空表（空表会被下游当成「没有估值数据」而静默跳过 ✗）。
    """
    import io
    try:
        # 需要 lxml / html5lib ✓；用 StringIO 避免 pandas 的 FutureWarning ✓
        tables = pd.read_html(io.StringIO(html))
    except ValueError as exc:
        # 页面里**一张表都没有** ⇒ read_html 直接抛 ValueError ✗
        # ⇒ 必须转成我们自己的错误文案 ✓（否则调用方只会看到
        #   "No tables found"，不知道是页面改版 ✗）
        raise RuntimeError(
            "未能从 multpl 页面解析出 PE 月度表 —— 页面结构可能已变 ✗"
            "（read_html 报：%s）" % exc)
    best = None
    for t in tables:
        if t.shape[1] < 2 or len(t) < 100:      # 月度序列至少上百行 ✓
            continue
        cols = [str(c) for c in t.columns]
        t = t.copy()
        t.columns = cols
        dcol = next((c for c in cols if "date" in c.lower()), cols[0])
        vcol = next((c for c in cols if c != dcol), cols[1])
        d = pd.to_datetime(t[dcol], errors="coerce")
        v = pd.to_numeric(
            t[vcol].astype(str).str.replace(",", "", regex=False)
            .str.extract(r"([-+]?\d*\.?\d+)", expand=False),
            errors="coerce")
        df = pd.DataFrame({"date": d, "pe": v}).dropna()
        if len(df) < 100:
            continue
        if best is None or len(df) > len(best):
            best = df
    if best is None:
        raise RuntimeError(
            "未能从 multpl 页面解析出 PE 月度表 —— 页面结构可能已变 ✗"
            "（拿到 %d 张表，全部不满足「≥2 列且 ≥100 行」）" % len(tables))
    return best.sort_values("date").reset_index(drop=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    ap.add_argument("--url", default=URL)
    args = ap.parse_args(argv)

    print("抓取：%s（代理=%s）" % (args.url, PROXY or "直连"))
    html = _get(args.url)
    print("  页面 %d 字符" % len(html))

    df = parse_multpl(html)
    print("  解析出 %d 行：%s → %s"
          % (len(df), df["date"].iloc[0].date(), df["date"].iloc[-1].date()))
    print("  最新 PE = %.2f（%s）"
          % (df["pe"].iloc[-1], df["date"].iloc[-1].date()))

    if args.dry_run:
        print("（--dry-run：未写入）")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8")
    print("已写入：%s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
