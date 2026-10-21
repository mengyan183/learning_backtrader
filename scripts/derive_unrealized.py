#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 `positions.csv` 派生未实现盈亏（逐标的 / 逐日 / 审计 `accounts.csv`）。

【为什么有这个脚本】
11 条假说依赖**浮亏** ✗（`H-011/016/017/018/022/038/040` + `H-001/006/008/009`），
但 `accounts.csv` 的 `unrealized_pnl` 来自富途 `unrealized_pl` ✗ —— 部分 FutuOpenD
版本**没有该字段** ⇒ 静默写 0.0 ✗；且**逐标的**浮亏从来没算过 ✗。

`positions.csv` 有 `qty/price/cost` ✓ ⇒ `unrealized = qty × (price − cost)` ✓ 可完全自算 ✓。

【用法】
    py -3.10 scripts/derive_unrealized.py                    # 最后一日逐标的
    py -3.10 scripts/derive_unrealized.py --date 2026-10-20  # 指定日
    py -3.10 scripts/derive_unrealized.py --daily            # 逐日汇总
    py -3.10 scripts/derive_unrealized.py --audit            # 与 accounts.csv 对账 ✗
    py -3.10 scripts/derive_unrealized.py --json             # 机器可读
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd                                        # noqa: E402

from fg_system import config                               # noqa: E402
from fg_system.data import derived                         # noqa: E402


def _load(name):
    p = os.path.join(config.DATA_DIR, name)
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, dtype={"symbol": str})


def main(argv=None):
    ap = argparse.ArgumentParser(description="派生未实现盈亏（不读 API 字段 ✓）")
    ap.add_argument("--date", default="", help="指定日期 YYYY-MM-DD（默认最后一日）")
    ap.add_argument("--daily", action="store_true", help="逐日汇总")
    ap.add_argument("--audit", action="store_true",
                    help="与 accounts.csv 的 unrealized_pnl 对账（找出可疑行 ✗）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args(argv)

    pos = _load("positions.csv")
    if pos is None or pos.empty:
        sys.exit("❌ Data/positions.csv 不存在或为空 ✗（本机可能是旧快照 ✓）")
    if not derived.available(pos):
        sys.exit("❌ positions.csv 缺少列：%s ✗"
                 % (set(derived.REQUIRED) - set(pos.columns)))

    if args.audit:
        acc = _load("accounts.csv")
        out = derived.audit_accounts(acc, pos)
        if args.json:
            print(json.dumps(out.to_dict("records"), ensure_ascii=False, default=str))
            return 0
        print("%-12s %12s %12s %10s %s" % ("日期", "accounts 报的", "自算", "差", "判定"))
        for _, r in out.iterrows():
            print("%-12s %12.2f %12.2f %10.2f %s"
                  % (r["date"], r["reported"] or 0.0, r["derived"], r["diff"],
                     "✅" if r["ok"] else "🔴 不一致（数据源可疑 ✗）"))
        bad = int((~out["ok"]).sum())
        print("\n不一致 %d / %d 天 %s"
              % (bad, len(out), "✓" if bad == 0 else "✗ ⇒ 这些天的 unrealized_pnl 不可信 ✗"))
        return 0 if bad == 0 else 1

    if args.daily:
        out = derived.daily(pos)
        if args.json:
            print(json.dumps(out.to_dict("records"), ensure_ascii=False, default=str))
            return 0
        print("%-12s %12s %s" % ("日期", "合计浮亏", "标的数"))
        for _, r in out.tail(30).iterrows():
            print("%-12s %12.2f %d" % (r["date"], r["unrealized"], r["n_symbols"]))
        return 0

    date = args.date or None
    out = derived.by_symbol(pos, date)
    if args.json:
        print(json.dumps(out.to_dict("records"), ensure_ascii=False, default=str))
        return 0
    if out.empty:
        sys.exit("❌ 该日无持仓 ✗")
    print("日期 %s（自算 ✓ `qty × (price − cost)`）" % out["date"].iloc[0])
    print("%-8s %10s %10s %10s %12s" % ("标的", "qty", "price", "cost", "未实现盈亏"))
    for _, r in out.iterrows():
        print("%-8s %10s %10.2f %10.2f %12.2f"
              % (r["symbol"], r["qty"], r["price"], r["cost"], r["unrealized"]))
    print("-" * 56)
    print("%-8s %38.2f" % ("合计", out["unrealized"].sum()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
