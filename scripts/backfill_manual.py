#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backfill_manual：把富途流水里 manual 账本缺失的成交，幂等回填进 trade_log.csv。

MT-72④（用户 2026-10-26 拍板 2A：全量含期权回填、期权纳入账本 ✓）：
- 权威源 `Data/trade_log_futu.csv`（券商 history_deal_list_query ✓）
- 目标 `Data/trade_log.csv`（手工账本；futu 拿不到的 OKX/BTC 系保留不动 ✓）
- 回填行 `reason=backfill` ✓，**逐笔保留**（不聚合分批 ✓），**不覆盖**已有行 ✓

幂等：按 `date|SYMBOL|action` 去重，manual 已有的 key 跳过 ⇒ 重复跑不会重复写 ✓。
默认 dry-run 只打印将补多少笔；`--write` 才落盘。**不写任何其它文件** ✓。

用法：
    .venv/bin/python scripts/backfill_manual.py            # dry-run 预览
    .venv/bin/python scripts/backfill_manual.py --write     # 落盘回填
"""
import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from fg_system import config  # noqa: E402

FUTU = "trade_log_futu.csv"
MANUAL = "trade_log.csv"
MANUAL_COLS = ["date", "symbol", "action", "quantity", "price", "reason"]


def _read(name):
    p = os.path.join(config.DATA_DIR, name)
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, dtype=str)


def _key(df):
    return (pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d") + "|"
            + df["symbol"].astype(str).str.upper() + "|"
            + df["action"].astype(str).str.lower())


def plan(futu, manual):
    """返回待回填行（futu 有、manual 无的 key）✓，逐笔保留 ✓。"""
    mkeys = set(_key(manual)) if manual is not None and not manual.empty else set()
    f = futu.copy()
    f["date"] = pd.to_datetime(f["date"]).dt.strftime("%Y-%m-%d")
    f["symbol"] = f["symbol"].astype(str).str.upper()
    f["action"] = f["action"].astype(str).str.lower()
    f["_k"] = _key(f)
    add = f[~f["_k"].isin(mkeys)].copy()
    add["reason"] = "backfill"
    return add[MANUAL_COLS].reset_index(drop=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="富途流水回填手工账本（幂等，默认 dry-run）")
    ap.add_argument("--write", action="store_true", help="落盘写回 trade_log.csv（否则只预览）")
    args = ap.parse_args(argv)

    futu = _read(FUTU)
    manual = _read(MANUAL)
    if futu is None or futu.empty:
        sys.exit("❌ %s 不存在或为空 ✗（先跑 fetch_trades_futu.py）" % FUTU)

    add = plan(futu, manual)
    print("futu %d 笔 ｜ manual %d 笔" % (len(futu), 0 if manual is None else len(manual)))
    print("待回填 %d 笔（manual 已有 key 跳过 ✓）" % len(add))
    if not add.empty:
        print("  方向分布: %s" % dict(add["action"].value_counts()))
        print(add[["date", "symbol", "action", "quantity", "price"]]
              .to_string(index=False))

    if not args.write:
        print("\n（dry-run，未写盘；加 --write 落盘）")
        return 0

    base = manual.copy() if manual is not None and not manual.empty else \
        pd.DataFrame(columns=MANUAL_COLS)
    merged = pd.concat([base[MANUAL_COLS], add], ignore_index=True)
    merged["_d"] = pd.to_datetime(merged["date"])
    merged = merged.sort_values(["_d", "symbol"]).drop(columns=["_d"])
    out = os.path.join(config.DATA_DIR, MANUAL)
    merged.to_csv(out, index=False, encoding="utf-8")
    print("\n✅ 已写 %s：manual %d + 回填 %d = %d 行"
          % (out, len(base), len(add), len(merged)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
