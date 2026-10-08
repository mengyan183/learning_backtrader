#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-6 合并 Put-Call 双层数据 → Data/raw/putcall.csv（标准因子输入）。

层 1（基底，2006-11-01 ~ 2019-10-04）：CBOE 官方批量 CSV（cdn.cboe.com）
  - Data/raw/putcall/{totalpc,indexpc,equitypc,etppc,spxpc,vixpc}.csv
  - 每文件列：DATE, CALL(S), PUT(S), TOTAL, P/C Ratio
层 2（近期，2020-01-02 起）：scripts/fetch_putcall.py 逐日抓取
  - Data/raw/putcall_daily.csv（6 档比率 + 成交量 + 持仓）

输出 Data/raw/putcall.csv：date, total_ratio, index_ratio, equity_ratio, etp_ratio, vix_ratio,
      spx_ratio（2006-2019 部分仅基底含的档位有值；近期 6 档全量）

用法：.venv/bin/python scripts/build_putcall.py
"""
import glob
import os

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PC_DIR = os.path.join(REPO, "Data", "raw", "putcall")
DAILY = os.path.join(REPO, "Data", "raw", "putcall_daily.csv")
OUT = os.path.join(REPO, "Data", "raw", "putcall.csv")

FILE_MAP = {
    "totalpc.csv": "total_ratio",
    "indexpc.csv": "index_ratio",
    "equitypc.csv": "equity_ratio",
    "etppc.csv": "etp_ratio",
    "spxpc.csv": "spx_ratio",
    "vixpc.csv": "vix_ratio",
}


def load_base():
    frames = []
    for fname, col in FILE_MAP.items():
        path = os.path.join(PC_DIR, fname)
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path, skiprows=2, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(path, skiprows=2, encoding="latin-1")
        # 找 P/C Ratio 列（名称可能带空格）
        ratio_col = [c for c in df.columns if "P/C" in c or "P/C Ratio" in c]
        if not ratio_col:
            continue
        df = df[["DATE", ratio_col[0]]].rename(columns={ratio_col[0]: col})
        df["date"] = pd.to_datetime(df["DATE"], errors="coerce")
        df = df.dropna(subset=["date", col])
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        frames.append(df[["date", col]])
    if not frames:
        return pd.DataFrame()
    base = frames[0]
    for f in frames[1:]:
        base = base.merge(f, on="date", how="outer")
    return base.sort_values("date")


def main():
    base = load_base()
    print("基底（官方 CSV）：%d 条，%s → %s" % (
        len(base), base["date"].min() if len(base) else "-", base["date"].max() if len(base) else "-"))

    if glob.glob(os.path.join(REPO, "Data", "raw", "putcall_daily*.csv")):
        daily_frames = []
        for f in sorted(glob.glob(os.path.join(REPO, "Data", "raw", "putcall_daily*.csv"))):
            d = pd.read_csv(f, parse_dates=["date"])
            d["date"] = d["date"].dt.strftime("%Y-%m-%d")
            cols = ["date", "total_ratio", "index_ratio", "equity_ratio", "etp_ratio",
                    "vix_ratio", "spx_ratio"]
            daily_frames.append(d[cols])
        daily = pd.concat(daily_frames, ignore_index=True)
        daily = daily.drop_duplicates(subset=["date"], keep="last").sort_values("date")
        print("近期（逐日页面）：%d 条，%s → %s" % (
            len(daily), daily["date"].min(), daily["date"].max()))
        merged = pd.concat([base, daily], ignore_index=True) if len(base) else daily
    else:
        merged = base

    merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    merged.to_csv(OUT, index=False)
    print("合并 → %s：共 %d 条（%s → %s）" % (OUT, len(merged), merged["date"].min(), merged["date"].max()))
    print("total_ratio 非空：%d 条" % merged["total_ratio"].notna().sum())


if __name__ == "__main__":
    main()
