#!/usr/bin/env python3
"""MT-76 ④：C1_BAA10Y 信用利差因子 IC/IR/分层单调性评测（只评测、不进合成权重）。

口径（与 scripts/factor_screen.py / evolution/factors.md 一致，不新设阈值）：
  - 信号 = credit_spread.baa10y_zscore（756 日滚动分位，窗口走 config.RANK_WINDOW）
  - 对齐：merge_asof(backward, on=available_date)，禁 ffill（lookahead 已由 ③ 测试守住）
  - 目标 SPY close（Data/raw/prices.csv）；horizons = 5/10/20/40；IC 滚动窗 window=60
  - 门槛：|rank_ICIR| ≥ 0.5 且 n ≥ 60 且近窗（120 IC 值）无衰减（|近窗 ICIR| ≥ 全窗×0.5）
  - 只读取证：不改策略、不进白名单、不进合成权重；入库仍需回测裁判+人工审批。

用法：
  .venv/bin/python scripts/eval_baa10y.py            # stdout 摘要
  .venv/bin/python scripts/eval_baa10y.py --json evolution/baa10y-eval.json
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fg_system.factors import base as fbase  # noqa: E402
from fg_system.factors import protocol as fproto  # noqa: E402
from fg_system.factors import credit_spread as cs  # noqa: E402

DATA = REPO / "Data"
HORIZONS = (5, 10, 20, 40)
WINDOW = 60
AVAIL_CSV = "Data/raw/fred_baa10y_avail.csv"


def _spy_close() -> pd.Series:
    p = pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])
    s = p[p.symbol == "SPY"].set_index("date")["close"].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH", help="把完整报告写到 JSON")
    ap.add_argument("--lag-days", type=int, default=0, help="额外保守滞后（默认0）")
    ap.add_argument("--orthogonalize", metavar="COL", default=None,
                    help="先剔除 features.csv 该列（如 fed）再评测 ✓ 滚动 β、shift(1) 无前视")
    args = ap.parse_args(argv)

    spy = _spy_close()
    df = cs.load(str(REPO / AVAIL_CSV))
    z = cs.baa10y_zscore(df, spy.index, lag_days=args.lag_days)

    feat_path = REPO / "Data" / "features.csv"
    feat = (pd.read_csv(feat_path, parse_dates=["date"]).set_index("date")
            if feat_path.exists() else None)

    fid = "C1_BAA10Y"
    if args.orthogonalize:
        col = args.orthogonalize
        if feat is None or col not in feat.columns:
            print("✗ features.csv 里没有列 %r ⇒ 无法正交化" % col)
            return 2
        raw = z
        z = fbase.orthogonalize(raw, feat[col])
        fid += "|orth:" + col
        print("# 正交化：剔除 %s（滚动 β 用 t-1 窗口，无前视 ✓）" % col)
        print("  残差非空 %d / 原序列非空 %d\n"
              % (int(z.notna().sum()), int(raw.notna().sum())))

    rep = fproto.screen_report(
        z, spy, factor_id=fid, target="SPY", direction="逆向",
        horizons=HORIZONS, window=WINDOW, n_buckets=5, fee=fproto.DEFAULT_FEE)

    print("# C1_BAA10Y 信用利差因子评测（MT-76 ④）" + ("  [正交化]" if args.orthogonalize else ""))
    print(f"样本：{rep['sample_start']} → {rep['sample_end']}，n_days={rep['n_days']}")
    print(f"判定：{rep['verdict']['status']} —— {rep['verdict']['detail']}")
    print()
    print("| horizon | rank_ic_mean | rank_ICIR | pearson_ICIR | n | 近窗ICIR | 分层mono | top-bottom |")
    print("|---|---|---|---|---|---|---|---|")
    for h in HORIZONS:
        ic = rep["ic"][h]
        rec = rep["recent"].get(h) or {}
        lay = rep["layers"].get(h, {})
        print(
            f"| {h} | {ic['rank_ic_mean']:+.3f} | {ic['rank_icir']:+.3f} | "
            f"{ic['pearson_icir']:+.3f} | {ic['n']} | "
            f"{rec.get('icir', float('nan')):+.3f} | "
            f"{lay.get('monotonic_spearman', float('nan')):.3f} | "
            f"{lay.get('top_minus_bottom', float('nan'))*100:+.2f}% |")

    # 与现有情绪/宏观因子的相关性（正交性取证，Spearman，z 非空区间）
    # 正交化后这里应该看到目标列的相关系数**掉到 0 附近** ✓（正交化是否生效的活证据）
    if feat is not None:
        jz = z.dropna()
        cmp = feat.reindex(jz.index)
        print("\n## 与现有因子 Spearman 相关（正交性取证）")
        for col in ("vix", "putcall", "fg_index", "term", "breadth", "fed", "price"):
            if col in cmp.columns:
                r = jz.corr(cmp[col], method="spearman")
                print(f"- baa10y_z ~ {col}: {r:+.3f}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\n[已写 {args.json}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
