#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F-020 阈值扫描 ✓（2026-11-02 用户要求）。

🔴 **过拟合警告**：在只有 ~215 个触发点的样本上调参 ✗
   很容易调到「历史上最优、未来无效」✗
   ⇒ 判据不是「哪个阈值超额最大」✗
   ⇒ 而是「**超额随阈值单调变化且不剧烈**」✓（稳健性）
      若某个阈值突然冒尖 ⇒ 那是过拟合 ✗ 不要选

用法：
  .venv/bin/python scripts/sweep_f020_threshold.py
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

from fg_system.factors import report as frep      # noqa: E402

DATA = REPO / "Data"
HORIZONS = frep.HORIZONS_DAILY
THRESHOLDS = (1.0, 1.1, 1.2, 1.3, 1.5, 1.8)


def _close(fname, col="close"):
    d = pd.read_csv(DATA / "raw" / fname, parse_dates=["date"])
    s = d.set_index("date")[col].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def main(argv=None):
    spy = frep.close_series(frep.load_prices(DATA), "SPY")
    pc = _close("putcall.csv", "total_ratio").reindex(spy.index)

    print("# F-020 阈值扫描（P/C > thr，事件研究，SPY）")
    print("| thr | 触发天数 | 占比 | 年份数 | 5日 | 10日 | 20日 | 40日 | 40日正占比 |")
    print("|---|---|---|---|---|---|---|---|---|")
    rows = []
    for thr in THRESHOLDS:
        flag = (pc > thr).astype(float)
        f = flag[flag > 0]
        n_ev, n_year = len(f), len(set(f.index.year))
        if n_ev < 15:
            print("| %.1f | %d | %.1f%% | %d | — | — | — | — | ✗ 触发太少 |"
                  % (thr, n_ev, 100.0 * n_ev / max(len(flag), 1), n_year))
            continue
        cells, d40, pos40 = [], None, None
        for h in HORIZONS:
            fwd = frep.forward_return(spy, h)
            both = pd.concat([flag.rename("f"), fwd.rename("r")],
                             axis=1).dropna()
            ev, base = both[both["f"] > 0]["r"], both["r"]
            d = (ev.mean() - base.mean()) * 100
            cells.append("%+.2fpp" % d)
            if h == 40:
                d40, pos40 = d, (ev > 0).mean() * 100
        rows.append((thr, n_ev, n_year, d40, pos40))
        print("| %.1f | %d | %.1f%% | %d | %s | %.0f%% |"
              % (thr, n_ev, 100.0 * n_ev / max(len(flag), 1), n_year,
                 " | ".join(cells), pos40))

    print("\n## 稳健性判读（不是选「超额最大」✗）")
    if len(rows) >= 3:
        d40s = [r[3] for r in rows]
        print("40 日超额区间：%+.2fpp ~ %+.2fpp"
              % (min(d40s), max(d40s)))
        print("| 项 | 值 |")
        print("|---|---|")
        print("| 单调性 | %s |"
              % ("✓ 基本单调" if all(d40s[i] <= d40s[i + 1]
                                    for i in range(len(d40s) - 1))
                 else "⚠️ 非单调（可能有过拟合点）"))
        print("| 离散度（极差/均值） | %.2f |"
              % ((max(d40s) - min(d40s)) / abs(sum(d40s) / len(d40s))
                 if sum(d40s) else 0))
        print("| 年份覆盖 | %d ~ %d 年 |"
              % (min(r[2] for r in rows), max(r[2] for r in rows)))
    print("\n⇒ 建议：选**超额稳定 + 年份覆盖广 + 触发不过于稀疏**的阈值 ✓")
    print("   ⚠️ 若某阈值明显冒尖 ⇒ 那是过拟合 ✗ 不要选它")
    return 0


if __name__ == "__main__":
    sys.exit(main())
