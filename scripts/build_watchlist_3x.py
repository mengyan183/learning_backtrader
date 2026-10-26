#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MT-66：生成「美股 3× 做多 ETF 关注列表」`Data/raw/watchlist_3x.csv`。

【清单来源（不手工列 ✗）】
`Data/raw/shoutu_etf_universe.csv`（守猪待兔官网 ETF 全资产页抓取 ✓，本地缓存 ✓）
最新交易日 `category=美股杠杆` 且 `name` 含「三倍」⇒ 3× 做多 ✓（两倍/四倍/反向
不在内 ✗）。

【底层归属（方案 B，纯本地 ✗ 不联网 ✓）】
1. `config.SIGNAL_UNDERLYING_MAP` 已登记 ✓；
2. `auto_resolve` 本地推断缓存 `Data/underlying_map_auto.csv` ✓；
3. 都没有 ⇒ `underlying=未知` 且**不给贪恐分** ✗（任务② ✓）。

【纪律】
- 只读本地 CSV，**禁止现场联网抓数** ✗（任务⑤ ✓）；
- 幂等，可每日重跑刷新清单与官网现价 ✓。

用法：
    .venv/bin/python scripts/build_watchlist_3x.py
"""
import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd                                        # noqa: E402
from fg_system import config                               # noqa: E402

RAW = os.path.join(config.DATA_DIR, "raw")
UNIVERSE = os.path.join(RAW, "shoutu_etf_universe.csv")
WATCHLIST = os.path.join(RAW, "watchlist_3x.csv")
AUTO_CACHE = os.path.join(config.DATA_DIR, "underlying_map_auto.csv")

#: 落盘列 ✓（任务① `symbol,name,underlying,source`；附 price / universe_fg 供展示 ✓）
COLS = ["symbol", "name", "underlying", "source", "price", "universe_fg"]


def _load_auto_cache():
    if not os.path.exists(AUTO_CACHE):
        return {}
    try:
        d = pd.read_csv(AUTO_CACHE, dtype={"symbol": str, "underlying": str})
    except (OSError, ValueError):
        return {}
    return {str(r["symbol"]).strip().upper(): str(r["underlying"]).strip()
            for _, r in d.iterrows()}


def build():
    """从本地 universe 生成关注列表 DataFrame ✓。"""
    uni = pd.read_csv(UNIVERSE, dtype={"code": str, "name": str})
    last = uni["date"].max()
    day = uni[uni["date"] == last]
    lev = day[day["category"] == "美股杠杆"].copy()
    lev = lev[lev["name"].astype(str).str.contains("三倍", na=False)]

    cache = _load_auto_cache()
    rows = []
    for _, r in lev.sort_values("code").iterrows():
        sym = str(r["code"]).split(".")[-1].strip().upper()
        registered = config.SIGNAL_UNDERLYING_MAP.get(sym)
        cached = cache.get(sym)
        if registered:
            underlying, source = registered, "registered"
        elif cached:
            underlying, source = cached, "infer_cache"
        else:
            underlying, source = "未知", "universe"
        rows.append({
            "symbol": sym,
            "name": str(r["name"]),
            "underlying": underlying,
            "source": source,
            "price": r.get("price"),
            "universe_fg": r.get("fg_index"),
        })
    out = pd.DataFrame(rows, columns=COLS)
    out["_as_of"] = last
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    out = build()
    as_of = out["_as_of"].iloc[0] if len(out) else None
    out.drop(columns=["_as_of"]).to_csv(WATCHLIST, index=False, encoding="utf-8")
    if not args.quiet:
        n_reg = int((out["source"] == "registered").sum())
        n_unk = int((out["underlying"] == "未知").sum())
        print("关注列表已写 %s（universe 截至 %s，共 %d 个 3× 做多 ✓）"
              % (WATCHLIST, as_of, len(out)))
        print("  已登记底层 %d / 本地推断 %d / 底层未知 %d"
              % (n_reg, int((out["source"] == "infer_cache").sum()), n_unk))
    return 0


if __name__ == "__main__":
    sys.exit(main())
