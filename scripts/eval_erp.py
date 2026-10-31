#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2_ERP 股权风险溢价因子 IC/IR/分层单调性评测（只评测、不进合成权重）。

口径（与 `scripts/eval_baa10y.py` 一致，不新设阈值）：
  - 信号 = `erp.erp_pct()`（**120 个月 = 10 年**滚动分位 ✓）
    ⚠️ 月度序列的窗口单位是**行数** ✗ —— 别传 2520（会全 NaN ✗）
  - 方向 = **正向**：ERP 高 = 股票相对债券便宜 = 看多 ✓
  - 对齐：`merge_asof(backward, on=available_date)`，禁 ffill ✓
  - 目标 SPY close；horizons = 5/10/20/40；IC 滚动窗 window=60
  - 门槛：|rank_ICIR| ≥ 0.5 且 n ≥ 60 且近窗（120 IC 值）无衰减
  - **评测起点 1962**（2026-10-31 用户裁定）✓ —— PE 1871 起、
    DGS10 1962 起 ⇒ 交集从 1962 开始，样本 660 个有效分位点 ✓
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
HORIZONS = (5, 10, 20, 40)
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH", help="把完整报告写到 JSON")
    ap.add_argument("--window", type=int, default=ferp.ERP_WINDOW,
                    help="分位窗口（**月**，默认 %d）" % ferp.ERP_WINDOW)
    args = ap.parse_args(argv)

    spy = _spy_close()
    sig = ferp.erp_pct(target_index=spy.index, window=args.window).dropna()
    if START:
        sig = sig[sig.index >= pd.Timestamp(START)]
    if len(sig) == 0:
        print("✗ 无有效信号 —— 检查 PE/CAPE/DGS10 数据与窗口 ✗")
        return 2

    rep = fproto.screen_report(
        sig, spy, factor_id="C2_ERP", target="SPY", direction="正向",
        horizons=HORIZONS, window=WINDOW, n_buckets=5,
        fee=fproto.DEFAULT_FEE)

    print("# C2_ERP 股权风险溢价因子评测（%d 月窗口 · 起点 %s）"
          % (args.window, START))
    print("样本：%s → %s，n_days=%s"
          % (rep["sample_start"], rep["sample_end"], rep["n_days"]))
    # 🔴 `verdict` 的字段是 `status` / `detail` / `best_horizon` / `passed` ✗
    # （不是 `passed` / `reason` —— 2026-10-31 实测打成 `[] —— None` ✗）
    v = rep.get("verdict") or {}
    print("判定：%s —— %s"
          % (v.get("status") or "—", v.get("detail") or "—"))
    if v.get("passed"):
        print("  达标 horizon：%s" % v["passed"])
    print()

    print("| horizon | rank_ic_mean | rank_ICIR | pearson_ICIR | n | 近窗ICIR "
          "| 分层mono | top-bottom |")
    print("|---|---|---|---|---|---|---|---|")
    for h in HORIZONS:
        ic = (rep.get("ic") or {}).get(h) or {}
        rc = (rep.get("recent") or {}).get(h) or {}
        ly = (rep.get("layers") or {}).get(h) or {}
        ls = (rep.get("long_short") or {}).get(h) or {}
        print("| %d | %s | %s | %s | %s | %s | %s | %s |"
              % (h, _fmt(ic.get("rank_ic_mean")), _fmt(ic.get("rank_icir")),
                 _fmt(ic.get("pearson_icir")), ic.get("n") or 0,
                 _fmt(rc.get("rank_icir")),
                 _fmt(ly.get("monotonicity"), ".3f"),
                 _fmt(ls.get("top_bottom"), "+.2f", 100.0) + "%"))

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
        p.write_text(json.dumps({"report": rep, "window": args.window,
                                 "start": START}, ensure_ascii=False,
                                indent=2, default=str), encoding="utf-8")
        print("\n[已写 %s]" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
