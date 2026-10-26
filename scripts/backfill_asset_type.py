#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给成交流水表**回填** `asset_type` 列（`stock` / `option` ✓）—— 一次性迁移 ✓。

【为什么】

`Data/trade_log` 里混了 **17 笔期权** ✗（`buy_back 9` + `sell_short 8` ✓），
但表里**没有类型列** ✗ ⇒ 下游无法分流 ✗。期权 **1 张 = 100 股** ✗，
混着算会**低估 100 倍** ✗（见 `fg_system/data/asset_type.py` 的说明）。

【行为】

- 默认 **dry-run** ✗：只打印会改多少行，**不写文件** ✗。
- `--write`：**先备份** `<文件>.bak` ✓ 再写回 ✓。
- **幂等** ✓：已有 `asset_type` 列 ⇒ 只做**校验**（打印分类统计 ✓），**不重复加列** ✗。

【只处理这两个源】

`trade_log.csv`（手工 ✓）/ `trade_log_futu.csv`（富途 ✓）。
`trade_log_merged.csv` 由 `merge_trades.py` **自动生成** ✓ ⇒ 不需要回填 ✗。

【用法】

    py -3.10 scripts/backfill_asset_type.py            # dry-run
    py -3.10 scripts/backfill_asset_type.py --write    # 写回（自动备份）
"""
import argparse
import os
import shutil
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd                                        # noqa: E402

from fg_system import config                               # noqa: E402
from fg_system.data import asset_type                      # noqa: E402

TARGETS = ("trade_log.csv", "trade_log_futu.csv")


def process(name, write=False):
    """处理单个文件 ✓；返回 `(行数, 期权数, 是否改动)` ✓。"""
    p = os.path.join(config.DATA_DIR, name)
    if not os.path.exists(p):
        print("  %-24s 不存在 ⇒ 跳过 ✓" % name)
        return 0, 0, False

    df = pd.read_csv(p, dtype={"symbol": str})
    if "symbol" not in df.columns:
        print("  %-24s 无 symbol 列 ⇒ 跳过 ✗" % name)
        return len(df), 0, False

    tagged = asset_type.classify_df(df)
    n_opt = int((tagged["asset_type"] == asset_type.OPTION).sum())

    if "asset_type" in df.columns:
        print("  %-24s 已有 asset_type ✓ ⇒ 只校验：%d 行，其中期权 %d 笔 ✓"
              % (name, len(df), n_opt))
        return len(df), n_opt, False

    print("  %-24s %d 行 ⇒ 将新增 asset_type（期权 %d 笔 ✗）"
          % (name, len(df), n_opt))
    if not write:
        return len(df), n_opt, False

    shutil.copy2(p, p + ".bak")                 # 先备份 ✓
    tagged.to_csv(p, index=False, encoding="utf-8")
    print("  %-24s ✅ 已写回（备份 %s.bak ✓）" % (name, name))
    return len(df), n_opt, True


def main():
    ap = argparse.ArgumentParser(description="回填 trade_log 的 asset_type 列")
    ap.add_argument("--write", action="store_true", help="真正写回（默认 dry-run）")
    args = ap.parse_args()

    print("数据目录：%s" % config.DATA_DIR)
    print("模式：%s" % ("写入 ✓" if args.write else "dry-run ✗（加 --write 才写）"))
    tot = tot_opt = 0
    for name in TARGETS:
        n, o, _ = process(name, write=args.write)
        tot += n
        tot_opt += o

    print("\n合计 %d 行，其中期权 %d 笔 ✗" % (tot, tot_opt))
    if tot_opt:
        print("🔴 期权 1 张 = 100 股 ✗ ⇒ 统计与浮亏**必须按 asset_type 分流** ✗")
    if not args.write and tot_opt:
        print("下一步：加 --write 真正写回（会自动备份 .bak ✓）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
