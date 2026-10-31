#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2_ERP 股权风险溢价因子 IC/IR/分层单调性评测（只评测、不进合成权重）。

口径（与 `scripts/eval_baa10y.py` 一致，不新设阈值）：
  - 信号 = `erp.erp_pct()`（**120 个月 = 10 年**滚动分位 ✓）
    ⚠️ 月度序列的窗口单位是**行数** ✗ —— 别传 2520（会全 NaN ✗）
  - 方向 = **正向**：ERP 高 = 股票相对债券便宜 = 看多 ✓
  - 对齐：`merge_asof(backward, on=available_date)`，禁 ffill ✓
  - 目标 SPY close；IC 滚动窗 window=60
  - 门槛：|rank_ICIR| ≥ 0.5 且 n ≥ 60 且近窗（120 IC 值）无衰减
  - **评测起点 1962**（2026-10-31 用户裁定）✓ —— PE 1871 起、
    DGS10 1962 起 ⇒ 交集从 1962 开始
  - **两套 horizon 都跑**（2026-10-31 用户裁定）：
      日频 5/10/20/40（现有标准）+ 月频 60/120/240（慢变量对照）✓
    ⚠️ 月频结果**只作对照** ✗ —— 现有采纳流程是日频的，
       月频过了也不代表能进 VARIANTS ✓
  - 只读取证：不改策略、不进白名单、不进合成权重

用法：
  .venv/bin/python scripts/eval_erp.py
  .venv/bin/python scripts/eval_erp.py --json evolution/erp-eval.json
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fg_system.factors import erp as ferp        # noqa: E402
from fg_system.factors import protocol as fproto  # noqa: E402

DATA = REPO / "Data"
#: 日频（现有唯一标准 ✓）
HORIZONS_DAILY = (5, 10, 20, 40)
#: 月频（慢变量对照 ✓，**不作为采纳依据** ✗）
HORIZONS_MONTHLY = (60, 120, 240)
WINDOW = 60
#: 评测起点（用户裁定：1962 —— DGS10 起点，样本量最大 ✓）
START = "1962-01-01"


def _fmt(v, spec="+.3f", scale=1.0):
    """`None` ⇒ `—` ✓（样本不足时 screen_report 会返回 None ✗）。"""
    return "—" if v is None else format(v * scale, spec)


def _spy_close():
    p = pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])
    s = p[p.symbol == "SPY"].set_index("date")["close"].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def _corr_table(sig, feat):
    """与现有因子的 Spearman 相关（正交性取证）✓，**带 n** ✗ 不带 n 不可信。"""
    out = []
    for col in ("vix", "term", "putcall", "breadth", "price", "fed",
                "baa10y_pct"):
        if col not in feat.columns:
            continue
        other = pd.to_numeric(feat[col], errors="coerce")
        pair = pd.concat([sig.rename("s"), other.rename("o")], axis=1).dropna()
        if len(pair) < 30:
            out.append((col, None, len(pair)))
            continue
        out.append((col, pair["s"].corr(pair["o"], method="spearman"),
                    len(pair)))
    return out


def _print_report(rep, label, horizons):
    print("\n## %s（%s）" % (label, "/".join(str(h) for h in horizons)))
    v = rep.get("verdict") or {}
    print("判定：%s —— %s"
          % (v.get("status") or "—", v.get("detail") or "—"))
    if v.get("passed"):
        print("  达标 horizon：%s" % v["passed"])
    print("| horizon | rank_ic_mean | rank_ICIR | pearson_ICIR | n |")
    print("|---|---|---|---|---|")
    for h in horizons:
        ic = (rep.get("ic") or {}).get(h) or {}
        print("| %d | %s | %s | %s | %s |"
              % (h, _fmt(ic.get("rank_ic_mean")), _fmt(ic.get("rank_icir")),
                 _fmt(ic.get("pearson_icir")), ic.get("n") or 0))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH", help="把完整报告写到 JSON")
    ap.add_argument("--window", type=int, default=ferp.ERP_WINDOW,
                    help="分位窗口（**月**，默认 %d）" % ferp.ERP_WINDOW)
    ap.add_argument("--target", default="SPY", help="目标标的（默认 SPY）")
    args = ap.parse_args(argv)

    spy = _spy_close()
    sig = ferp.erp_pct(target_index=spy.index, window=args.window).dropna()
    if START:
        sig = sig[sig.index >= pd.Timestamp(START)]
    if len(sig) == 0:
        print("✗ 无有效信号 —— 检查 PE/CAPE/DGS10 数据与窗口 ✗")
        return 2

    print("# C2_ERP 股权风险溢价因子评测（%d 月窗口 · 起点 %s · 目标 %s）"
          % (args.window, START, args.target))
    print("信号 %d 天：%s → %s"
          % (len(sig), sig.index[0].date(), sig.index[-1].date()))

    # 两套 horizon 各跑一次 ✓ —— screen_report 的 horizons 参数化 ✓
    rep_d = fproto.screen_report(
        sig, spy, factor_id="C2_ERP", target=args.target, direction="正向",
        horizons=HORIZONS_DAILY, window=WINDOW, n_buckets=5,
        fee=fproto.DEFAULT_FEE)
    rep_m = fproto.screen_report(
        sig, spy, factor_id="C2_ERP", target=args.target, direction="正向",
        horizons=HORIZONS_MONTHLY, window=WINDOW, n_buckets=5,
        fee=fproto.DEFAULT_FEE)

    print("样本：%s → %s，n_days=%s"
          % (rep_d["sample_start"], rep_d["sample_end"], rep_d["n_days"]))

    _print_report(rep_d, "日频（现有唯一标准 ✓）", HORIZONS_DAILY)
    _print_report(rep_m, "月频（**仅对照**，不作采纳依据 ✗）", HORIZONS_MONTHLY)

    # CAPE 分歧分布（回答「阈值该定多少」✓）
    div = ferp.cape_divergence(window=args.window).dropna()
    if len(div):
        print("\n## CAPE 分歧分布（阈值按此定 ✓）")
        print("| P50 | P75 | P90 | P95 | max | 最新 |")
        print("|---|---|---|---|---|---|")
        print("| %.1f | %.1f | %.1f | %.1f | %.1f | %.1f |"
              % (div.quantile(.5), div.quantile(.75), div.quantile(.9),
                 div.quantile(.95), div.max(), div.iloc[-1]))
        print("⇒ 建议阈值 = **P90 = %.1f**（当前初值 %.0f）"
              % (div.quantile(.9), ferp.CAPE_DIV_THRESHOLD))

    feat_p = DATA / "features.csv"
    if feat_p.exists():
        feat = pd.read_csv(feat_p, parse_dates=["date"]).set_index("date")
        print("\n## 与现有因子 Spearman 相关（正交性取证）")
        for col, rho, n in _corr_table(sig, feat):
            note = ""
            if rho is not None and abs(rho) > 0.5 and n >= 250:
                note = "  ⚠️ 高相关，需正交化"
            elif n < 250:
                note = "  ⚠️ n=%d 太少，此系数不可信" % n
            print("- erp ~ %s: %s（n=%d）%s"
                  % (col, "—" if rho is None else "%+.3f" % rho, n, note))

    if args.json:
        p = Path(args.json)
        if not p.is_absolute():
            p = REPO / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "window": args.window, "start": START, "target": args.target,
            "daily": rep_d, "monthly": rep_m,
            "cape_div": {
                "p50": float(div.quantile(.5)) if len(div) else None,
                "p90": float(div.quantile(.9)) if len(div) else None,
                "latest": float(div.iloc[-1]) if len(div) else None,
            },
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("\n[已写 %s]" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
