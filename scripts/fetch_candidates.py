#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**一次性**批量抓「底层候选池」的日线，写进 `Data/raw/prices.csv`。

【为什么单独一个脚本】
`query_symbol_fg.py --auto` 要用候选池做 β 回归 ✓ —— 但**现场抓 48 个 ETF 要 1~2 分钟** ✗
⇒ 放进查询请求里不可接受 ✗（页面会超时 ✓）。

⇒ 拆成两段 ✓：
- **本脚本**（一次性 / 偶尔跑 ✓）：把候选池全部抓齐 ✓，之后查询**只读本地** ✓（秒级 ✓）；
- `query_symbol_fg.py --auto`：只抓**目标标的**（1 个 ✓ ~2s ✓）+ 用本地候选推断 ✓。

【用法】
    py -3.10 scripts/fetch_candidates.py            # 抓全部缺的
    py -3.10 scripts/fetch_candidates.py EWY EWJ    # 只抓指定
    py -3.10 scripts/fetch_candidates.py --check    # 只报告哪些缺，不抓
"""
import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd                                    # noqa: E402

from fg_system import config                           # noqa: E402
from fg_system.data import fetch as fetch_mod          # noqa: E402
from fg_system.factors import underlying_infer as ui   # noqa: E402

#: 目标行数：滚动窗口 756 + 动量 60 ✓（少于它算不出个股分 ✗）
MIN_ROWS = int(config.RANK_WINDOW) + 60


def _load_prices():
    p = os.path.join(config.RAW_DIR, "prices.csv")
    if not os.path.exists(p):
        return pd.DataFrame(columns=["symbol", "date", "open", "high",
                                     "low", "close", "volume"])
    return pd.read_csv(p, dtype={"symbol": str}, parse_dates=["date"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="批量抓底层候选池日线")
    ap.add_argument("symbols", nargs="*", help="只抓这些（默认：候选池全部）")
    ap.add_argument("--check", action="store_true", help="只报告缺口，不抓")
    ap.add_argument("--limit", type=int, default=MIN_ROWS + 50,
                    help="每标的抓多少行（默认 %d）" % (MIN_ROWS + 50))
    args = ap.parse_args(argv)

    cands = ui.load_candidates()
    if not cands:
        sys.exit("❌ 候选池为空（%s）" % ui.CANDIDATES_CSV)
    targets = [s.upper() for s in (args.symbols or list(cands))]

    cur = _load_prices()
    have = cur.groupby("symbol").size().to_dict() if not cur.empty else {}
    gaps = {s: have.get(s, 0) for s in targets}

    print("%-8s %-8s %s" % ("标的", "现有行数", "状态"))
    for s, n in gaps.items():
        flag = "✅ 够" if n >= MIN_ROWS else ("🟡 偏少" if n else "🔴 无")
        print("%-8s %-8d %s" % (s, n, flag))

    missing = [s for s, n in gaps.items() if n < MIN_ROWS]
    if args.check:
        print("\n--check：缺 %d 个（%s）" % (len(missing), ", ".join(missing) or "无"))
        return 0
    if not missing:
        print("\n✅ 全部已够 %d 行，无需抓取" % MIN_ROWS)
        return 0

    print("\n开始抓取 %d 个（每个约 1~2s ✓）…" % len(missing))
    added, failed = {}, []
    for s in missing:
        try:
            df = fetch_mod.fetch_symbol(s, limit=args.limit)
        except (RuntimeError, OSError, ValueError) as exc:
            print("  ❌ %-8s %s" % (s, exc))
            failed.append(s)
            continue
        if df is None or df.empty:
            print("  ⚠️ %-8s 返回空表（限流或该标的无数据 ✗）" % s)
            failed.append(s)
            continue
        cur = pd.concat([cur, df], ignore_index=True)
        added[s] = len(df)
        print("  ✅ %-8s +%d 行" % (s, len(df)))

    if added:
        cur = cur.drop_duplicates(subset=["symbol", "date"], keep="last")
        cur = cur.sort_values(["symbol", "date"])
        cur.to_csv(os.path.join(config.RAW_DIR, "prices.csv"), index=False)
        print("\n✅ 已写回 prices.csv：%d 个标的，共 %d 行"
              % (len(added), sum(added.values())))
    if failed:
        print("⚠️ 失败 %d 个：%s" % (len(failed), ", ".join(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
