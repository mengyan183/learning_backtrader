#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓 S&P 500 估值序列（月度历史）→ `Data/raw/sp500_pe.csv` / `sp500_cape.csv`。

【为什么需要】
C2「ERP 估值锚」= `1/PE − 10Y` 分位，用来回答「现在贵不贵」✗。
但 **FRED 没有 PE 系列** ✗（只有 10Y / DGS10），仓库里也没有任何 PE 历史 ✗
⇒ 必须先解决数据源 ✓。

【选型（2026-10-30）】

| 源 | 历史深度 | 结论 |
|---|---|---|
| **multpl.com**（S&P500 PE / Shiller CAPE） | **1871 起** | ✅ 选它 |
| Shiller `ie_data.xls` | 1871 起 | 需 xlrd + 多 sheet 解析 ✗ 绕 |
| FRED | 无 PE 系列 | ✗ |
| yfinance `^GSPC.info` | 仅当前值 | ✗ 无历史 |
| 富途 `pe_ttm_ratio` | 个股快照 | 只能逐日自建，攒 2~3 年才有分位意义 ✗ |

【频率：**月度，不插值到日频**（2026-10-30 决策）】
PE / CAPE 是**慢变量**（月度更新、由季报驱动）✗ ⇒ 日频插值不产生新信息 ✗，
只会把阶梯变成斜线、制造「同一个月内分位平滑上升」的假信号 ✗。
⇒ 存**月度**序列，并在文件里带 `available_date`（= 月末 + 1 个月，保守）✓
   —— 下游按 `available_date` 对齐，避免「用当月 PE 算当月信号」的前视偏差 ✗。

⚠️ 页面抓取**天然脆弱** ✗ —— multpl 改版即失效 ✓。
本脚本因此**只做一件事**：解析失败就**明确报错**（不静默产出空文件 ✗），
并在 stdout 打印实际拿到的行数与首末日期，便于一眼判断是否退化 ✓。

【用法】
    python scripts/fetch_pe_ratio.py                  # 默认抓 PE + CAPE
    python scripts/fetch_pe_ratio.py --series pe      # 只抓 PE
    python scripts/fetch_pe_ratio.py --dry-run
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402

#: 序列定义：`key -> (候选 URL 列表, 输出文件名)` ✓
#: 🔴 2026-10-30 实测：`/shiller-pe-cape-ratio/table/by-month` **404** ✗
#: ⇒ 改成**候选列表**，按顺序试到第一个能通的 ✓（页面路径靠猜不可靠 ✗）
SERIES = {
    "pe": (["https://www.multpl.com/s-p-500-pe-ratio/table/by-month"],
           "sp500_pe.csv"),
    "cape": (["https://www.multpl.com/shiller-pe/table/by-month",
              "https://www.multpl.com/shiller-pe-cape-ratio/table/by-month"],
             "sp500_cape.csv"),
}
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


def parse_multpl(html, value_col="value"):
    """解析 multpl 的 by-month 表 ⇒ `DataFrame[date, <value_col>, available_date]` ✓。

    ⚠️ 只认「两列：日期 + 数值」且 ≥100 行的表 ✗ —— 页面结构变了就抛错，
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
            "未能从 multpl 页面解析出估值月度表 —— 页面结构可能已变 ✗"
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
        df = pd.DataFrame({"date": d, value_col: v}).dropna()
        if len(df) < 100:
            continue
        if best is None or len(df) > len(best):
            best = df
    if best is None:
        raise RuntimeError(
            "未能从 multpl 页面解析出估值月度表 —— 页面结构可能已变 ✗"
            "（拿到 %d 张表，全部不满足「≥2 列且 ≥100 行」）" % len(tables))
    best = best.sort_values("date").reset_index(drop=True)
    # 🔴 前视偏差防护 ✓：月度值通常在**月末之后**才发布 ⇒
    # 保守地把可用日设为「下个月的同一天」（`DateOffset(months=1)`）✓
    best["available_date"] = best["date"] + pd.DateOffset(months=1)
    return best


def fetch_one(key, dry_run=False, url=None):
    """抓一条序列并落盘 ✓，返回 `(DataFrame, 输出路径)`。

    候选 URL **按顺序试** ✓ —— 第一个通了就用它 ✓（页面路径靠猜不可靠 ✗）；
    全部失败 ⇒ 抛错并带上每个 URL 的失败原因 ✓（不静默 ✗）。
    """
    urls, fname = SERIES[key]
    urls = [url] if url else list(urls)
    out = os.path.join(config.RAW_DIR, fname)
    html, last_err, used = None, None, None
    for u in urls:
        print("抓取 %s：%s（代理=%s）" % (key.upper(), u, PROXY or "直连"))
        try:
            html = _get(u)
            used = u
            break
        except Exception as exc:               # noqa: BLE001 —— 逐个试 ✓
            last_err = "%s → %s: %s" % (u, type(exc).__name__, exc)
            print("  ✗ 失败：%s" % last_err)
    if html is None:
        raise RuntimeError("所有候选 URL 都失败 ✗\n  " + "\n  ".join(
            [last_err or "未知"]))
    print("  页面 %d 字符（来源 %s）" % (len(html), used))

    df = parse_multpl(html, value_col=key)
    print("  解析出 %d 行：%s → %s"
          % (len(df), df["date"].iloc[0].date(), df["date"].iloc[-1].date()))
    print("  最新 %s = %.2f（数据日 %s，可用日 %s）"
          % (key.upper(), df[key].iloc[-1], df["date"].iloc[-1].date(),
             df["available_date"].iloc[-1].date()))

    if not dry_run:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        df.to_csv(out, index=False, encoding="utf-8")
        print("  已写入：%s" % out)
    return df, out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    ap.add_argument("--series", default="both",
                    choices=["pe", "cape", "both"], help="抓哪条序列（默认两条）")
    ap.add_argument("--url", default=None, help="覆盖页面 URL（调试用）")
    args = ap.parse_args(argv)

    keys = ["pe", "cape"] if args.series == "both" else [args.series]
    for k in keys:
        fetch_one(k, dry_run=args.dry_run, url=args.url)
    if args.dry_run:
        print("（--dry-run：未写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
