#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MT-65：用 `yfinance` 建公司行动清单（合股/拆股 splits + 派息 dividends）。

【为什么】
富途 OpenAPI **没有**公司行动/分红/拆股接口（只有价格数量的成交流水 ✓），
快照反推（`derive_trades.py`）会把合股/派息造成的**名义数量变化**误判成卖出 ✗
⇒ 需要一份公司行动清单，供 `merge_trades.py --audit` 把这些**非交易**项从
「疑似券商漏单」待查里区分出来 ✓。

【输出（Data/raw/）】
- `splits.csv`：`symbol,date,ratio,source,verified`
    * 保留既有 `manual` / `verified=1` 行（人工已核实，**绝不覆盖** ✓）
    * yfinance 新抓行标 `source=yfinance, verified=0`（未人工核实 ✗ ⇒ merge 只**提示**，
      不自动豁免 ✓）
- `dividends.csv`：`symbol,date,amount`（yfinance，仅留档，不参与豁免判定 ✓）

【容错纪律】
- 走本地代理 7890；遇 Yahoo 429 限流 ⇒ 退避重试一次，仍失败**跳过该标的** ✗，
  不中断其它标的、不删既有清单 ✓。
- 网络全失败 ⇒ 保留原文件、打印汇总、退出码 0（数据侧补全，不阻断每日链 ✓）。

用法：
    .venv/bin/python scripts/fetch_corporate_actions.py            # 抓取并合并写盘
    .venv/bin/python scripts/fetch_corporate_actions.py --quiet    # 只打印汇总
"""
import argparse
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd                                        # noqa: E402
import requests                                            # noqa: E402

from fg_system import config                               # noqa: E402

RAW_DIR = os.path.join(config.DATA_DIR, "raw")
SPLITS_CSV = os.path.join(RAW_DIR, "splits.csv")
DIVIDENDS_CSV = os.path.join(RAW_DIR, "dividends.csv")
PROXY = "http://127.0.0.1:7890"
#: 抓取标的 = 生产 SYMBOLS + 底层补抓清单（MT-65 ① 明确这两个 ✓）
TARGET_SYMBOLS = sorted({s.upper() for s in
                         list(config.SYMBOLS) + list(config.UNDERLYING_FETCH_SYMBOLS)})


def _session():
    sess = requests.Session()
    sess.proxies = {"http": PROXY, "https": PROXY}
    return sess


def _fetch_one(symbol, sess, retries=3):
    """抓单个标的的 splits / dividends；限流指数退避重试；失败返回 (None, None) ✓。

    MT-69 轻加固：偶发网络/抖动最多重试 3 次，退避按 5s→10s→20s 指数拉长；
    注意 IP 整体被 Yahoo 429 限流时重试无效（仍跳过该标的 ✗），本加固只为
    偶发抖动与「限流恢复后自动补全」服务，不替代备用源 ✓。
    """
    import yfinance as yf
    backoff = [5, 10, 20]
    for attempt in range(retries + 1):
        try:
            tk = yf.Ticker(symbol, session=sess)
            sp = tk.splits
            dv = tk.dividends
            splits = []
            if sp is not None and len(sp):
                for dt, ratio in sp.items():
                    splits.append({"symbol": symbol,
                                   "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                                   "ratio": round(float(ratio), 6),
                                   "source": "yfinance", "verified": 0})
            divs = []
            if dv is not None and len(dv):
                for dt, amount in dv.items():
                    divs.append({"symbol": symbol,
                                "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                                "amount": round(float(amount), 6)})
            return splits, divs
        except Exception as e:  # 限流/网络/解析 ✗
            if attempt < retries:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
                continue
            if not _quiet:
                print("  ⚠️ %s 抓取失败（跳过，保留原清单）：%s"
                      % (symbol, type(e).__name__))
            return None, None
    return None, None


def _load_existing(path, cols):
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, dtype=str)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def main(argv=None):
    global _quiet
    ap = argparse.ArgumentParser(description="yfinance 公司行动清单（splits/dividends）")
    ap.add_argument("--quiet", action="store_true", help="只打印汇总")
    ap.add_argument("--sleep", type=float, default=1.5,
                    help="标的间间隔秒数（默认 1.5，温和限速降低 Yahoo 429 ✓）")
    args = ap.parse_args(argv)
    _quiet = args.quiet

    os.makedirs(RAW_DIR, exist_ok=True)
    sess = _session()

    old_splits = _load_existing(SPLITS_CSV,
                                ["symbol", "date", "ratio", "source", "verified"])
    old_divs = _load_existing(DIVIDENDS_CSV, ["symbol", "date", "amount"])

    new_splits, new_divs = [], []
    ok, skipped = 0, 0
    for sym in TARGET_SYMBOLS:
        sp, dv = _fetch_one(sym, sess)
        if sp is None and dv is None:
            skipped += 1
            continue
        ok += 1
        new_splits.extend(sp or [])
        new_divs.extend(dv or [])
        time.sleep(args.sleep)  # 温和限速，降低 Yahoo 429 ✓

    # ---- splits：保留 manual/verified=1，yfinance 行按 (symbol,date,ratio) 去重 ✓ ----
    if new_splits:
        add = pd.DataFrame(new_splits)
        keep = old_splits[old_splits["source"] != "yfinance"]  # 非 yfinance 全保留 ✓
        merged = pd.concat([keep, add], ignore_index=True)
        merged["ratio"] = pd.to_numeric(merged["ratio"], errors="coerce")
        merged = merged.drop_duplicates(
            subset=["symbol", "date", "ratio"], keep="first")
        merged = merged.sort_values(["symbol", "date"]).reset_index(drop=True)
        merged.to_csv(SPLITS_CSV, index=False, encoding="utf-8")
    else:
        merged = old_splits

    # ---- dividends：按 (symbol,date,amount) 去重合并 ✓ ----
    if new_divs:
        add = pd.DataFrame(new_divs)
        merged_d = pd.concat([old_divs, add], ignore_index=True)
        merged_d["amount"] = pd.to_numeric(merged_d["amount"], errors="coerce")
        merged_d = merged_d.drop_duplicates(
            subset=["symbol", "date", "amount"], keep="first")
        merged_d = merged_d.sort_values(["symbol", "date"]).reset_index(drop=True)
        merged_d.to_csv(DIVIDENDS_CSV, index=False, encoding="utf-8")

    n_sp = 0 if merged is None else len(merged)
    print("公司行动清单：抓取成功 %d / 跳过 %d（目标 %d）"
          % (ok, skipped, len(TARGET_SYMBOLS)))
    print("  splits.csv 现有 %d 行（manual/verified=1 已保留 ✓）" % n_sp)
    if os.path.exists(DIVIDENDS_CSV):
        print("  dividends.csv 现有 %d 行" % len(pd.read_csv(DIVIDENDS_CSV)))
    return 0


_quiet = False

if __name__ == "__main__":
    sys.exit(main())
