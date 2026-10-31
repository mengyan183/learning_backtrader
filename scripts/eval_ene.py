#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C5_ENE 包络通道因子评测 —— **三变体对照**（2026-10-31）。

回答一个具体问题（用户 2026-10-31 提出）：

> 「ENE(10,10,9) 在**正股**上用过，**杠杆 ETF 上偏差有点大**」

| 变体 | 信号载体 | 包络 | 作用 |
|---|---|---|---|
| **C5a** | **正股** | ENE(10,10,9) 固定% | 主变体 ✓ |
| C5b | 杠杆 ETF | ENE(10,10,9) 固定% | 反证「偏差大」✗ |
| C5c | 杠杆 ETF | MA10 ± 2×ATR20 | 对照（自适应） |

判读：
  - C5b 最差、C5c 接近 C5a ⇒ **参数问题**（ATR 包络能救）
  - C5b / C5c 都差、只有 C5a 好 ⇒ **载体问题**（必须在正股上算）

口径与 `eval_baa10y.py` / `eval_erp.py` 一致：
  - 方向 = **逆向**（`pos` 高 = 超买 ⇒ 未来收益低）
  - horizons = 5/10/20/40；IC 滚动窗 window=60
  - 门槛：|rank_ICIR| ≥ 0.5 且 n ≥ 60 且近窗无衰减
  - 只读取证：不改策略、不进白名单、不进合成权重

用法：
  .venv/bin/python scripts/eval_ene.py
  .venv/bin/python scripts/eval_ene.py --json evolution/ene-eval.json
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fg_system.factors import ene as fene          # noqa: E402
from fg_system.factors import protocol as fproto    # noqa: E402

DATA = REPO / "Data"
HORIZONS = (5, 10, 20, 40)
WINDOW = 60

#: 评测组合：`(交易标的, 变体 mode, 说明)` ✓
COMBOS = (
    ("SPY", "self_ene", "C5b · SPY 自身 ENE（宽基基准）"),
    ("SPY", "self_keltner", "C5c · SPY 自身 Keltner"),
    ("YINN", "underlying", "C5a · FXI 信号 → 交易 YINN"),
    ("YINN", "self_ene", "C5b · YINN 自身 ENE"),
    ("YINN", "self_keltner", "C5c · YINN 自身 Keltner"),
    ("GDXU", "underlying", "C5a · GDX 信号 → 交易 GDXU"),
    ("GDXU", "self_ene", "C5b · GDXU 自身 ENE"),
)


def _fmt(v, spec="+.3f"):
    return "—" if v is None else format(v, spec)


def _load_prices():
    p = pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])
    return p


def _close(prices, sym):
    return fene.close_series(prices, sym)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH", help="把完整报告写到 JSON")
    args = ap.parse_args(argv)

    prices = _load_prices()
    out = {}
    print("# C5_ENE 三变体对照评测（ENE 10/10/9 vs Keltner 2×ATR20）")

    for sym, mode, label in COMBOS:
        target = _close(prices, sym)
        if target.empty:
            print("\n## %s —— ✗ 无价格数据，跳过" % label)
            continue
        sig = fene.signal_for(prices, sym, mode=mode)
        if sig is None or sig.empty:
            print("\n## %s —— ✗ 无信号（缺正股数据？），跳过" % label)
            continue
        # 只保留有信号的日子 ✓
        sig = sig.dropna()
        target = target.reindex(sig.index).dropna()
        sig = sig.reindex(target.index)
        if len(sig) < 300:
            print("\n## %s —— ✗ 样本 %d 天太少，跳过" % (label, len(sig)))
            continue

        rep = fproto.screen_report(
            sig, target, factor_id="C5_%s_%s" % (sym, mode), target=sym,
            direction="逆向", horizons=HORIZONS, window=WINDOW, n_buckets=5,
            fee=fproto.DEFAULT_FEE)
        v = rep.get("verdict") or {}
        out[label] = rep

        print("\n## %s" % label)
        print("样本 %s → %s（%d 天）"
              % (rep["sample_start"], rep["sample_end"], rep["n_days"]))
        print("判定：%s" % (v.get("status") or "—"))
        print("| h | rank_ic_mean | rank_ICIR | n |")
        print("|---|---|---|---|")
        for h in HORIZONS:
            ic = (rep.get("ic") or {}).get(h) or {}
            print("| %d | %s | %s | %s |"
                  % (h, _fmt(ic.get("rank_ic_mean")),
                     _fmt(ic.get("rank_icir")), ic.get("n") or 0))

    if args.json:
        p = Path(args.json)
        if not p.is_absolute():
            p = REPO / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2,
                                default=str), encoding="utf-8")
        print("\n[已写 %s]" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
