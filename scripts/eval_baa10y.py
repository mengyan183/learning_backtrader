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
#: 正交化后至少要剩这么多天才值得评测 ✓（screen 要求每个 horizon n≥60，
#: 再留点余量给滚动 IC 窗）✗
MIN_ORTH = 250


def _fmt(v, spec="+.3f", scale=1.0):
    """`None` ⇒ `—` ✓。

    🔴 2026-10-29 Mac 实测：样本不足时 `screen_report` 把 `ic` 各字段给 **None** ✗，
    直接 `{v:+.3f}` 会 `TypeError: unsupported format string passed to NoneType` ✗
    ⇒ 整条评测崩掉、结果只剩一行「样本不足」✗。
    """
    return "—" if v is None else format(v * scale, spec)


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
        n_orth, n_raw = int(z.notna().sum()), int(raw.notna().sum())
        print("# 正交化：剔除 %s（滚动 β 用 t-1 窗口，无前视 ✓）" % col)
        print("  残差非空 %d / 原序列非空 %d" % (n_orth, n_raw))
        if n_orth < MIN_ORTH:
            # 🔴 2026-10-29 Mac 实测：`fed` 列与 baa10y 只重叠十几个点 ✗
            # ⇒ 残差只剩 16 天，评测毫无意义 ✗ ⇒ **明确拒绝**，别产出假结论 ✓
            print("✗ 残差只剩 %d 天（< %d）⇒ **正交化不可行** ✗\n"
                  "  最可能原因：`%s` 列本身有效样本太少（两列交集 + 756 天滚动窗 ✗）\n"
                  "  ⇒ 换一个长历史列（vix/term/breadth/price 都有 1500+ 天），\n"
                  "    或不做正交化、直接看原始相关性 ✓\n" % (n_orth, MIN_ORTH, col))
            return 2
        print()

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
            f"| {h} | {_fmt(ic.get('rank_ic_mean'))} | {_fmt(ic.get('rank_icir'))} | "
            f"{_fmt(ic.get('pearson_icir'))} | {ic.get('n')} | "
            f"{_fmt(rec.get('icir'))} | "
            f"{_fmt(lay.get('monotonic_spearman'), '.3f')} | "
            f"{_fmt(lay.get('top_minus_bottom'), '+.2f', 100)}% |")

    # 与现有情绪/宏观因子的相关性（正交性取证，Spearman，z 非空区间）
    # 正交化后这里应该看到目标列的相关系数**掉到 0 附近** ✓（正交化是否生效的活证据）
    # 🔴 2026-10-29：**必须打印每列的 n** ✗ —— 之前只打相关系数，
    # `fed` 只有十几个点也算出 +0.604 ✗ ⇒ 差点据此判定「与 fed 高度重复」✗。
    if feat is not None:
        jz = z.dropna()
        cmp = feat.reindex(jz.index)
        print("\n## 与现有因子 Spearman 相关（正交性取证）")
        for col in ("vix", "putcall", "fg_index", "term", "breadth", "fed", "price"):
            if col not in cmp.columns:
                continue
            pair = pd.concat([jz.rename("z"), cmp[col].rename("x")],
                             axis=1).dropna()
            if len(pair) < 2:
                print(f"- baa10y_z ~ {col}: 样本不足（n={len(pair)}）")
                continue
            r = pair["z"].corr(pair["x"], method="spearman")
            warn = "" if len(pair) >= MIN_ORTH else \
                "  ⚠️ n=%d 太少，此相关系数不可信" % len(pair)
            print(f"- baa10y_z ~ {col}: {r:+.3f}（n={len(pair)}）{warn}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\n[已写 {args.json}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
