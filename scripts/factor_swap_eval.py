# -*- coding: utf-8 -*-
"""评估「替换 `term`」的候选因子（第 12.55 条的设计支撑工具）。

背景：三档 A/B 证明「降 vol 权重 = 线性降收益」⇒ 40.5% 的集中度是策略的
收益来源，不能靠调权重解决 ✗ 真正的方向是**把 `term` 换成非波动率因子** ✓

候选（均为**已建但未进 WEIGHTS** 的模块）：
  · `credit_spread` —— BAA10Y 信用利差（融资条件，领先指标）
  · `erp`           —— 股权风险溢价（1/PE − 10Y，估值维度）

本脚本**只量不判**，输出三个硬指标：

  ① 数据可用性：起止日期 / 行数 / 缺失率
  ② **正交性**：候选与现有五因子（vix/price/breadth/fed/putcall）的
     Spearman 相关 —— 与 `vix` 的 |ρ| 越低越能解决共线性 ✓
  ③ **单因子 IC**：候选分数与 SPY 未来 20 日收益的 IC / ICIR（**已折算**）

用法：
    python scripts/factor_swap_eval.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system import index as index_mod  # noqa: E402
from fg_system import pipeline  # noqa: E402
from fg_system.factors.eval import evaluate  # noqa: E402

EXISTING = ("vix", "term", "price", "breadth", "fed", "putcall")


def _candidate_series(wide):
    """返回 {名字: (分数序列 0~100, 说明)}；取不到的记 `None` ✓。"""
    idx = wide.index
    out = {}

    try:
        from fg_system.factors import credit_spread as cs
        s = cs.baa10y_score(target_index=idx)
        out["credit_spread"] = (s.astype(float), "BAA10Y 信用利差（高=贪婪）")
    except Exception as exc:               # noqa: BLE001
        out["credit_spread"] = (None, "取不到：%s" % exc)

    try:
        from fg_system.factors import erp
        s = erp.erp_pct(target_index=idx)
        out["erp"] = (s.astype(float) * 100.0, "ERP 分位×100（高=便宜=贪婪）")
    except Exception as exc:               # noqa: BLE001
        out["erp"] = (None, "取不到：%s" % exc)

    return out


def _availability(s, idx):
    """覆盖情况：首末日期 / 非空数 / 相对指数索引的缺失率。"""
    if s is None:
        return None
    v = s.dropna()
    if not len(v):
        return {"rows": 0, "note": "全空"}
    return {
        "rows": int(len(v)),
        "start": str(v.index.min().date()),
        "end": str(v.index.max().date()),
        "missing_pct": round((1 - len(v) / len(idx)) * 100, 1),
    }


def _corr_table(cands, scores):
    """候选 vs 现有六因子的 Spearman 相关 ✓（绝对值越低越正交）。"""
    rows = []
    for name, (s, _desc) in cands.items():
        if s is None:
            continue
        row = {"factor": name}
        for f in EXISTING:
            if f not in scores.columns:
                continue
            both = pd.concat([s.rename("a"), scores[f].rename("b")],
                             axis=1).dropna()
            # ⚠️ 不用 `corr(method="spearman")` ✗ —— 它会 import scipy，
            #    本机（Python 3.14）上那个 import 慢到触发超时 ✗
            #    「先 rank 再 Pearson」在数学上等价，且只走 pandas 的 Cython ✓
            row[f] = (round(float(both["a"].rank().corr(both["b"].rank())), 2)
                      if len(both) > 30 else None)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    wide = pipeline.load_wide()
    idx = wide.index
    scores = index_mod.factor_scores(wide)
    spy = (wide[("SPY", "close")].astype(float)
           if ("SPY", "close") in wide.columns else None)

    print("指数区间: %s → %s（%d 交易日）"
          % (idx.min().date(), idx.max().date(), len(idx)))
    print("现有因子: %s" % list(scores.columns))

    cands = _candidate_series(wide)

    print("\n" + "=" * 62)
    print("① 数据可用性")
    print("=" * 62)
    for name, (s, desc) in cands.items():
        av = _availability(s, idx)
        print("  %-14s %s" % (name, av if av else desc))

    print("\n" + "=" * 62)
    print("② 正交性（Spearman ρ，与 vix 越接近 0 越好）")
    print("=" * 62)
    tbl = _corr_table(cands, scores)
    if len(tbl):
        print(tbl.to_string(index=False))
        print("\n  ⚠️ 判据：与 `vix` 的 |ρ| < 0.50 才算「解决共线性」✗")
        print("     现有 term 与 vix 的 ρ 也列在下表，作为对照 ✓")
        both = pd.concat([scores["term"].rename("a"),
                          scores["vix"].rename("b")], axis=1).dropna()
        print("     对照：term ↔ vix  ρ = %.2f"
              % both["a"].rank().corr(both["b"].rank()))
    else:
        print("  （候选全部取不到，无法计算）")

    print("\n" + "=" * 62)
    print("③ 单因子 IC（SPY 未来 20 日，ICIR 已按重叠折算）")
    print("=" * 62)
    if spy is None:
        print("  ⚠️ 取不到 SPY 收盘价 ⇒ 跳过")
    else:
        pool = list(cands.items())
        if "term" in scores.columns:
            pool.append(("term(对照)", (scores["term"], "")))
        for name, (s, _d) in pool:
            if s is None:
                print("  %-14s 数据缺失" % name)
                continue
            ev = evaluate(s.dropna(), spy, horizons=(20,), window=60)
            st = ev[20]["stats"]
            if not st:
                print("  %-14s 样本不足" % name)
                continue
            print("  %-14s IC %+.3f | ICIR %+.2f（原始 %+.2f，重叠×%d）"
                  " | 正值比 %.1f%% | n=%d"
                  % (name, st["ic_mean"], st["icir"], st["icir_raw"],
                     st["overlap"], st["ic_positive_ratio"] * 100, st["n"]))
        print("\n  ⚠️ 判据：|IC| ≥ 0.10 且方向为**负**（贪恐指数是逆向指标）✗")

    print("\n" + "=" * 62)
    print("预注册判据（第 12.55 条，达标才进入回测阶段）")
    print("=" * 62)
    print("  · 与 vix 的 |ρ| < 0.50")
    print("  · 单因子 |IC| ≥ 0.10 且为负")
    print("  · 覆盖 ≥ 5 年、缺失率 < 10%")
    print("  · 三条全过 ⇒ 才做「替换 term」的 A/B 组合回测 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
