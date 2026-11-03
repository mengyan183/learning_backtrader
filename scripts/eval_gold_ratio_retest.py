#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F-021 重测 ✓（2026-11-03 用户裁定）。

【为什么要重测】
  首检 IC 太强（GDX 40 日 rank_ic_mean **-0.533**）✗ 而 n_eff 仅 3~16 ✗
  ⇒ 这正是 **F-008 的翻版** ✗ —— 那次 ICIR 1.5，但事件研究直接推翻 ✗
  ⇒ 必须补四项交叉验证 ✓

【四项】

  ① **事件研究** —— 比值分位 > 0.8（金矿股相对最强）后
     5/10/20/40 日收益 vs 全样本基线 ✓
     ⇒ 若「之后跌」才算支持「逆向」结论 ✓

  ② **正交性** —— `gold_ratio_pct` 与 `GDX` 自身 120 日动量的相关性
     ⇒ 若 > 0.7 则本因子≈「GDX 动量」✗ 无独立信息 ✗
     ⇒ 再算「残差 IC」：把动量回归掉后信号还剩多少预测力 ✓

  ③ **分段** —— 前半 / 后半分别看 IC
     ⇒ 若只有一段强 ⇒ 是某段行情贡献 ✗ 不可复制 ✗

  ④ **水平 vs 变化率** —— `pct`（水平分位）vs `pct.diff()`（变化率）
     ⇒ 哪个更强 ✓

用法：
  .venv/bin/python scripts/eval_gold_ratio_retest.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

from fg_system.factors import gold_ratio as fgr     # noqa: E402
from fg_system.factors import protocol as fproto    # noqa: E402
from fg_system.factors import report as frep       # noqa: E402

DATA = REPO / "Data"
HORIZONS = frep.HORIZONS_DAILY
WINDOW = frep.WINDOW
TARGETS = ("GDX", "GDXU")


def _icir(sig, close, h):
    """单 horizon 的 rank_ICIR + mean ✓（复用 protocol）。"""
    rep = fproto.screen_report(
        sig, close, factor_id="tmp", target="tmp", direction="正向",
        horizons=(h,), window=WINDOW, n_buckets=5, fee=fproto.DEFAULT_FEE)
    ic = (rep.get("ic") or {}).get(h) or {}
    return ic.get("rank_icir"), ic.get("rank_ic_mean")


def _event(sig, close, label):
    """① 事件研究：信号 > 0.8 后的前瞻收益 vs 基线 ✓。"""
    flag = (sig > 0.8).astype(float)
    n_ev = int(flag.sum())
    print("\n### ① 事件研究 —— %s（触发 %d 天，占 %.1f%%）"
          % (label, n_ev, 100.0 * n_ev / max(len(flag), 1)))
    if n_ev < 15:
        print("✗ 触发太少（<15）⇒ 事件研究无意义 ✗")
        return
    print("| horizon | 触发后均值 | 全样本均值 | 差 | 触发后正占比 | 支持「逆向」? |")
    print("|---|---|---|---|---|---|")
    for h in HORIZONS:
        fwd = frep.forward_return(close, h)
        both = pd.concat([flag.rename("f"), fwd.rename("r")],
                         axis=1).dropna()
        ev, base = both[both["f"] > 0]["r"], both["r"]
        if len(ev) < 10:
            print("| %d | — | — | — | — | ✗ 太少 |" % h)
            continue
        diff = (ev.mean() - base.mean()) * 100
        pos = (ev > 0).mean() * 100
        ok = "✓ 是（跌）" if diff < 0 else "✗ 否（涨）"
        print("| %d | %+.2f%% | %+.2f%% | %+.2fpp | %.0f%% | %s |"
              % (h, ev.mean() * 100, base.mean() * 100, diff, pos, ok))


def _orthogonal(sig, close, label):
    """② 正交性：与 GDX 120 日动量的相关性 + 残差 IC ✓。"""
    mom = close.pct_change(120)
    both = pd.concat([sig.rename("s"), mom.rename("m")], axis=1).dropna()
    if len(both) < 100:
        print("\n### ② 正交性 —— %s：样本不足 ✗" % label)
        return
    rho = both["s"].corr(both["m"], method="spearman")
    print("\n### ② 正交性 —— %s（vs %s 自身 120 日动量）" % (label, label))
    print("Spearman 相关：**%+.3f**" % rho)
    if abs(rho) > 0.7:
        print("⇒ ✗ **高度共线** —— 本因子可能只是「动量」的另一种写法 ✗")
    else:
        print("⇒ ✓ 相关性 < 0.7，有独立信息 ✓")

    # 残差 IC：把动量回归掉，看信号残差是否还有预测力 ✓
    try:
        x = both["m"].values.astype(float)
        y = both["s"].values.astype(float)
        beta = np.polyfit(x, y, 1)
        resid = pd.Series(y - np.polyval(beta, x), index=both.index)
        for h in (20, 40):
            i1, m1 = _icir(resid, close.reindex(resid.index), h)
            print("  残差 IC（h=%d）：ICIR %s，mean %s"
                  % (h, frep.fmt(i1), frep.fmt(m1)))
        print("  ⚠️ 残差 IC 若明显弱于原 IC ⇒ 增量主要来自动量 ✗")
    except Exception as e:                  # noqa: BLE001
        print("  残差计算失败：%s" % e)


def _split(sig, close, label):
    """③ 分段：前半 / 后半 ✓。"""
    mid = len(sig) // 2
    print("\n### ③ 分段 —— %s" % label)
    print("| 段 | 区间 | h20 ICIR | h40 ICIR |")
    print("|---|---|---|---|")
    for tag, sl in (("前半", slice(0, mid)), ("后半", slice(mid, None))):
        s2 = sig.iloc[sl]
        c2 = close.reindex(s2.index)
        i20, _ = _icir(s2, c2, 20)
        i40, _ = _icir(s2, c2, 40)
        print("| %s | %s→%s | %s | %s |"
              % (tag, s2.index[0].date(), s2.index[-1].date(),
                 frep.fmt(i20), frep.fmt(i40)))
    print("⚠️ 若两段**符号相反或强度差很大** ⇒ 结论不可复制 ✗")


def _level_vs_change(sig, close, label):
    """④ 水平 vs 变化率 ✓。"""
    chg = sig.diff()
    print("\n### ④ 水平 vs 变化率 —— %s" % label)
    print("| 口径 | h20 ICIR | h20 mean | h40 ICIR | h40 mean |")
    print("|---|---|---|---|---|")
    for tag, s in (("水平（分位）", sig), ("变化率（diff）", chg)):
        s2 = s.dropna()
        c2 = close.reindex(s2.index)
        i20, m20 = _icir(s2, c2, 20)
        i40, m40 = _icir(s2, c2, 40)
        print("| %s | %s | %s | %s | %s |"
              % (tag, frep.fmt(i20), frep.fmt(m20),
                 frep.fmt(i40), frep.fmt(m40)))


def main(argv=None):
    prices = frep.load_prices(DATA)
    sig_all = fgr.gold_ratio_pct(prices).dropna()
    if sig_all.empty:
        print("✗ 无 GDX/GLD 数据")
        return 2

    print("# F-021 重测（GDX/GLD 相对强度）")
    print("信号 %d 天：%s → %s\n"
          % (len(sig_all), sig_all.index[0].date(), sig_all.index[-1].date()))

    for tgt in TARGETS:
        close = frep.close_series(prices, tgt)
        sig = sig_all.reindex(close.index).dropna()
        close2 = close.reindex(sig.index).dropna()
        sig = sig.reindex(close2.index)
        if len(sig) < 300:
            print("\n## %s —— 样本 %d 太少，跳过" % (tgt, len(sig)))
            continue
        print("\n\n## 目标 %s（%d 天：%s → %s）"
              % (tgt, len(sig), sig.index[0].date(), sig.index[-1].date()))
        _event(sig, close2, tgt)
        _orthogonal(sig, close2, tgt)
        _split(sig, close2, tgt)
        _level_vs_change(sig, close2, tgt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
