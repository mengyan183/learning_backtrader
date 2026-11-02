#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F-012 的 N 扫描 + F-020「独立极恐定义」候选 ✓（2026-11-02）。

【为什么需要 F-020】
  F-008 已 rejected ✗ 三条理由之一就是**循环论证**（`zone` 由 `fg_index` 分档，
  而 `fg_index` 是六因子合成 ✗）。但它的事件研究显示 20/40 日有**真实超额**
  （+1.33pp / +2.96pp）✓ ⇒ 值得用**独立于 fg_index** 的定义重做 ✓

【F-020 候选】
  A. `VIX > 40`（经典恐慌线）
  B. `P/C > 1.2`（CBOE 总 Put/Call，恐慌抛售）
  C. A 或 B（任一触发）
  D. A 且 B（同时触发，更严）

用法：
  .venv/bin/python scripts/eval_f020.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

from fg_system.factors import protocol as fproto   # noqa: E402
from fg_system.factors import report as frep      # noqa: E402

DATA = REPO / "Data"
HORIZONS = frep.HORIZONS_DAILY
WINDOW = frep.WINDOW


def _close(fname, col="close"):
    d = pd.read_csv(DATA / "raw" / fname, parse_dates=["date"])
    s = d.set_index("date")[col].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def event_table(flag, spy, label):
    """事件研究表 ✓（极恐日后 vs 全样本基线）。"""
    print("\n### %s 事件研究" % label)
    n_ev = int(flag.sum())
    print("触发 %d 天（占 %.1f%%）" % (n_ev, 100.0 * n_ev / max(len(flag), 1)))
    print("| horizon | 触发后均值 | 全样本均值 | 差 | 触发后正占比 | 判读 |")
    print("|---|---|---|---|---|---|")
    for h in HORIZONS:
        fwd = frep.forward_return(spy, h)
        both = pd.concat([flag.rename("f"), fwd.rename("r")], axis=1).dropna()
        ev, base = both[both["f"] > 0]["r"], both["r"]
        if len(ev) < 10:
            print("| %d | — | — | — | — | ✗ 触发太少 |" % h)
            continue
        diff = (ev.mean() - base.mean()) * 100
        pos = (ev > 0).mean() * 100
        ok = diff > 0 and pos >= 60
        print("| %d | %+.2f%% | %+.2f%% | %+.2fpp | %.0f%% | %s |"
              % (h, ev.mean() * 100, base.mean() * 100, diff, pos,
                 "✓ 有超额" if ok else "✗ 无"))
    return n_ev


def main(argv=None):
    spy = frep.close_series(frep.load_prices(DATA), "SPY")

    # ---------- F-012 的 N 扫描 ----------
    vix, vix3m = _close("vix.csv"), _close("vix3m.csv")
    term = (vix / vix3m).dropna()
    print("# F-012 N 扫描（term = vix/vix3m 的 N 日变化率）")
    print("| N | h5 ICIR | h10 | h20 | h40 | h40 n_eff | 判读 |")
    print("|---|---|---|---|---|---|---|")
    best = None
    for n in (3, 5, 10, 20, 40):
        sig = term.pct_change(n).dropna().reindex(spy.index).dropna()
        if len(sig) < 300:
            continue
        rep = fproto.screen_report(
            sig, spy, factor_id="F-012_N%d" % n, target="SPY", direction="正向",
            horizons=HORIZONS, window=WINDOW, n_buckets=5,
            fee=fproto.DEFAULT_FEE)
        ic = rep.get("ic") or {}
        try:
            ac1, n_eff = fproto.ic_autocorr(sig, frep.forward_return(spy, 40),
                                            window=WINDOW)
        except Exception:                   # noqa: BLE001
            ac1, n_eff = None, None
        h40 = (ic.get(40) or {}).get("rank_icir")
        judge = "—"
        if h40 is not None and n_eff:
            # ICIR 高且 n_eff 够（>15）才算「相对可信」✓
            judge = ("✓ 相对可信" if abs(h40) >= 0.5 and n_eff >= 15
                     else "⚠️ n_eff 偏低")
            if best is None or n_eff > best[1]:
                best = (n, n_eff, h40)
        print("| %d | %s | %s | %s | %s | %s | %s |"
              % (n, frep.fmt((ic.get(5) or {}).get("rank_icir")),
                 frep.fmt((ic.get(10) or {}).get("rank_icir")),
                 frep.fmt((ic.get(20) or {}).get("rank_icir")),
                 frep.fmt(h40),
                 "—" if n_eff is None else "%.0f" % n_eff, judge))
    if best:
        print("\n⇒ **建议 N=%d**（h40 ICIR %+.3f，n_eff %.0f 最大 ✓）"
              % (best[0], best[2], best[1]))

    # ---------- F-020 候选 ----------
    print("\n\n# F-020 独立极恐定义（候选）")
    print("⚠️ 与 F-008 的区别：**不用 `fg_index`** ✗ 而是直接用 VIX / P/C 原始数据 ✓")
    vix_lvl = vix.reindex(spy.index)
    try:
        pc = _close("putcall.csv", "total_ratio")
    except Exception as e:                  # noqa: BLE001
        print("[warn] putcall 读不到（%s）⇒ 只测 VIX 候选" % e)
        pc = None

    cands = [("A. VIX > 40", (vix_lvl > 40).astype(float))]
    if pc is not None:
        pc_lvl = pc.reindex(spy.index)
        cands += [
            ("B. P/C > 1.2", (pc_lvl > 1.2).astype(float)),
            ("C. VIX>40 或 P/C>1.2",
             ((vix_lvl > 40) | (pc_lvl > 1.2)).astype(float)),
            ("D. VIX>40 且 P/C>1.2",
             ((vix_lvl > 40) & (pc_lvl > 1.2)).astype(float)),
        ]
    for label, flag in cands:
        flag = flag.dropna()
        event_table(flag, spy, label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
