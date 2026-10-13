#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MT-02（mac-tasks 2026-10-13）：加密侧真实轨损耗反推。

用真实价格序列跑 `leverage.py::decompose`，反推 MSTX/CONL/BITX 的
`product_cost_annual`（产品费率拖累）与 `vol_decay_annual`（波动率拖累），
与 `config.CRYPTO_PRODUCT_COST_RATE`（按构造校准值，**不得当作费率使用**）
形成对照 —— 加密侧作结论必须用真实轨。

口径：
- 底层映射取 `config.CRYPTO_UNDERLYING`（BITX→BTC / MSTX→MSTR / CONL→COIN）
- 杠杆取 `config.CRYPTO_LEVERAGE`
- `leverage.decompose(und_ret, lev_ret, n)`：输入已对齐的日收益序列
- 数据源：`Data/raw/crypto_prices.csv`（真实轨，长表 date,symbol,close）

输出：`evolution/crypto-cost-real.json`
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd  # noqa: E402

from fg_system import config, leverage  # noqa: E402

TARGETS = [("MSTX", "MSTR"), ("CONL", "COIN"), ("BITX", "BTC")]


def main():
    prices = pd.read_csv(os.path.join(config.RAW_DIR, "crypto_prices.csv"),
                         parse_dates=["date"])
    out = {"available": True, "symbols": {}}
    for lev, und in TARGETS:
        lev_s = (prices[prices["symbol"] == lev]
                 .set_index("date")["close"].sort_index())
        und_s = (prices[prices["symbol"] == und]
                 .set_index("date")["close"].sort_index())
        if lev_s.empty or und_s.empty:
            out["symbols"][lev] = {"available": False}
            continue
        und_ret = und_s.pct_change().dropna()
        lev_ret = lev_s.pct_change().dropna()
        n = config.CRYPTO_LEVERAGE.get(lev, 2)
        dec = leverage.decompose(und_ret, lev_ret, n=n)
        out["symbols"][lev] = {
            "available": True,
            "n": n,
            "underlying": und,
            "range": [str(lev_s.index.min().date()), str(lev_s.index.max().date())],
            "n_days": len(lev_ret),
            **{k: round(float(v), 4) for k, v in dec.items()},
            "config_product_cost_rate": config.CRYPTO_PRODUCT_COST_RATE.get(lev),
        }
        d = out["symbols"][lev]
        print("%-5s σ=%.2f 波动率拖累=%.2f%% 产品损耗=%.2f%% 总损耗=%.2f%% "
              "(config 校准 %.1f%%)" % (
                  lev, d["sigma"], d["vol_decay_annual"] * 100,
                  d["product_cost_annual"] * 100, d["total_annual"] * 100,
                  d["config_product_cost_rate"] * 100
                  if d["config_product_cost_rate"] else float("nan")))
    out_path = os.path.join(os.path.dirname(__file__), "..",
                            "evolution", "crypto-cost-real.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("✅ 已写入 %s" % out_path)


if __name__ == "__main__":
    main()
