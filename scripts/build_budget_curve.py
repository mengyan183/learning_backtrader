#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B1：生成「回撤预算 → 仓位上限」曲线产物（离线）。

产物：`evolution/drawdown_budget_curve.json`

**数据源**：真实组合日序列 `evolution/baseline.json::portfolio.daily`
（`strategy_ret` / `strategy_nav`，`WEIGHTING=inv_vol`、真实轨、`shift(1)` 防前视；
主线 `3a78dff`(MT-07) 交付）。
⚠️ **纸面矩阵数据源已弃用** ✗ —— 首版曾用第 12.7 条 30 格矩阵的**纸面回撤常量**
（`cvar95=-0.49945` ✗），与真实序列**差一个数量级** ⇒ 改用真实序列 ✓。

**纪律（规划 v2.0 §方向 B「B1」+ 第 12.7 条）**：
  - 曲线**只回答「余量还剩多少」**（回撤 / CVaR 尾部指标），
    **不回答「更好的组合是什么」**；
  - **禁止输出** Calmar / 年化 / Sortino / Sharpe / 年化波动 等「效率」列；
  - 产物带 `OOS_WARNING`；**禁止**作为 `evolve_propose` 输入；
  - **口径自证**：`max_drawdown` 应与 `portfolio.strategy.full.max_drawdown`
    （-0.387651）一致。
  - 守卫测试：`tests/test_budget_curve_no_efficiency_cols.py`。

用法：
  py -3.10 scripts/build_budget_curve.py [--out evolution/drawdown_budget_curve.json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fg_system import risk_budget


def main():
    ap = argparse.ArgumentParser(description="B1 回撤预算 → 仓位上限曲线")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(__file__), "..", "evolution", "drawdown_budget_curve.json"))
    args = ap.parse_args()

    curve = risk_budget.build_curve()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(curve, fh, ensure_ascii=False, indent=1, default=str)

    sel = curve["selected"]
    print("✅ 回撤预算曲线已写入 %s" % args.out)
    print("   数据源：%s（%d 点）" % (curve["source"], curve["daily_points"]))
    print("   真实组合 max_drawdown %.6f（口径自证：应与 full.max_drawdown -0.387651 一致）"
          % curve["max_drawdown"])
    print("   预算 -%.0f%% | 当前 CORE_CAP=%.2f AMMO_CAP=%.2f ⇒ 余量 %.2fpp"
          % (curve["budget"] * 100, sel["core_cap"], sel["ammo_cap"],
             sel["margin_pp"]))
    print("   尾部（%d 个真实回撤事件）：CVaR95 %.6f / CVaR99 %.6f"
          % (len(curve["grid"]), curve["tail"]["cvar95"], curve["tail"]["cvar99"]))
    print("   ⚠️ %s" % curve["OOS_WARNING"])


if __name__ == "__main__":
    main()
