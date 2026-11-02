#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F-012（波动率期限结构变化率）与 F-008（极度恐惧标记）重测 ✓（2026-11-02）。

【为什么要重测】
  F-012 上次（2026-10-10）结论是「40 日 ICIR -0.67 过线但近窗衰减 -0.25」
  F-008 上次只做了粗事件研究（zone==0 共 102 日）
  ⇒ 那时**还没有 IC 自相关诊断** ✗ —— 衰减/过线都可能是假象 ✗
  ⇒ 现在用 `protocol.ic_autocorr` 看真实可信度 ✓

【F-012 定义】`term = vix3m/vix`，取其 **N 日滚动变化率** ✓
  ⚠️ 与 `fg_system/factors/term.py` 的 `TermStructureFactor` **不同** ✗
     那个是「比值的 756 日分位取反」（进合成权重），本脚本测的是「变化率」✓
  N 未知 ⇒ 扫 5/20 两档 ✓

【F-008 定义】`features.zone == 0` 的二进制标记 ✗
  🔴 **方法论警告：循环论证** ✗ —— `zone` 是 `fg_index` 的分档，
     而 `fg_index` 本身由六因子合成 ⇒ 用系统自己的输出当输入 ✗
     ⇒ 即使 IC 好也**不能采纳** ✗ 只能作为「系统内部一致性」的观察 ✓

用法：
  .venv/bin/python scripts/eval_f012_f008.py
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


def _vix_pair():
    """`vix` / `vix3m` 交集 ✓。"""
    v = pd.read_csv(DATA / "raw" / "vix.csv", parse_dates=["date"])
    v3 = pd.read_csv(DATA / "raw" / "vix3m.csv", parse_dates=["date"])
    a = (v.set_index("date")["close"].astype(float)
         .pipe(lambda s: s[~s.index.duplicated(keep="last")]).sort_index())
    b = (v3.set_index("date")["close"].astype(float)
         .pipe(lambda s: s[~s.index.duplicated(keep="last")]).sort_index())
    return a, b


def main(argv=None):
    spy = frep.close_series(frep.load_prices(DATA), "SPY")
    vix, vix3m = _vix_pair()
    term = (vix / vix3m).dropna()
    print("# F-012 / F-008 重测（2026-11-02）")
    print("term = vix/vix3m，%d 天：%s → %s\n"
          % (len(term), term.index[0].date(), term.index[-1].date()))

    # ---------- F-012：滚动变化率，扫 N=5 / 20 ----------
    for n in (5, 20):
        sig = term.pct_change(n).dropna()
        j = sig.reindex(spy.index).dropna()
        if len(j) < 300:
            print("## F-012（N=%d）—— ✗ 样本 %d 太少" % (n, len(j)))
            continue
        rep = fproto.screen_report(
            j, spy, factor_id="F-012_termchg%d" % n, target="SPY",
            direction="正向", horizons=HORIZONS, window=WINDOW,
            n_buckets=5, fee=fproto.DEFAULT_FEE)
        print(frep.report_block(
            rep, "F-012 波动率结构变化率（N=%d 日，正向）" % n,
            HORIZONS, sig=j, close=spy))
        print()

    # ---------- F-008：zone==0 二进制 ----------
    fp = DATA / "features.csv"
    if not fp.exists():
        print("## F-008 —— ✗ 缺 features.csv")
        return 0
    ft = pd.read_csv(fp, parse_dates=["date"]).set_index("date")
    if "zone" not in ft.columns:
        print("## F-008 —— ✗ features 里没有 zone 列")
        return 0
    flag = (ft["zone"] == 0).astype(float)
    flag = flag[flag.index >= term.index[0]]
    n_flag = int(flag.sum())
    print("## F-008 极度恐惧标记（zone==0）")
    print("极恐日 %d 天（占 %.1f%%）" % (n_flag, 100.0 * n_flag / max(len(flag), 1)))
    print("⚠️ **循环论证警告**：`zone` 由 `fg_index` 分档而来，"
          "而 `fg_index` 是六因子合成 ⇒ 用系统输出当输入 ✗ "
          "⇒ 即使 IC 好也**不能采纳** ✗ 仅作内部一致性观察 ✓\n")

    j = flag.reindex(spy.index).dropna()
    if len(j) < 300:
        print("✗ 样本太少（%d）" % len(j))
        return 0
    rep = fproto.screen_report(
        j, spy, factor_id="F-008_extreme", target="SPY", direction="逆向",
        horizons=HORIZONS, window=WINDOW, n_buckets=2,
        fee=fproto.DEFAULT_FEE)
    print(frep.report_block(rep, "F-008 极度恐惧标记（逆向）",
                            HORIZONS, sig=j, close=spy))

    # 事件研究：极恐日后 vs 全样本基线 ✓
    print("\n## F-008 事件研究（极恐日后 vs 全样本）")
    print("| horizon | 极恐后均值 | 全样本均值 | 差 | 极恐后正占比 |")
    print("|---|---|---|---|---|")
    for h in HORIZONS:
        fwd = frep.forward_return(spy, h)
        both = pd.concat([flag.rename("f"), fwd.rename("r")], axis=1).dropna()
        ev = both[both["f"] > 0]["r"]
        base = both["r"]
        if len(ev) < 10:
            print("| %d | — | — | — | — |" % h)
            continue
        print("| %d | %+.2f%% | %+.2f%% | %+.2fpp | %.0f%% |"
              % (h, ev.mean() * 100, base.mean() * 100,
                 (ev.mean() - base.mean()) * 100,
                 (ev > 0).mean() * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
