# -*- coding: utf-8 -*-
"""对比「旧权重 vs 新权重」下的**信号差异**（第 12.47 条的验证工具）。

为什么不用 `portfolio_backtest.py`：
  那个脚本回答的是「组合收益/回撤多少」，混入了标的选择、等权构造、成本模型
  ⇒ 权重改动的影响被其他因素稀释 ✗
  而本次改动只改 `fg_index` 的合成权重 ⇒ **直接比信号**才看得清 ✓

本脚本只算（**不写任何文件**，`pipeline.run(write=False)`）：
  · `fg_index` 分布：均值 / 标准差 / P10 / P90 / min / max
  · 五档占比（极度恐惧~极度贪婪）
  · `target_position` 均值 + **换手**（Σ|Δtarget|，衡量调仓频率变化）
  · 与 SPY 未来 20 日收益的 IC / ICIR（**已按重叠折算**，第 12.48 条）

用法：
    python scripts/weight_compare.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system import config, pipeline  # noqa: E402
from fg_system.factors.eval import evaluate  # noqa: E402

#: 第 12.47 条之前的权重（v2.7 六因子）
OLD = {"vix": 0.270, "term": 0.135, "price": 0.225,
       "breadth": 0.135, "fed": 0.135, "putcall": 0.100}

ZONE_EDGES = [0, 20, 40, 60, 80, 100]
ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


def _run_with(weights):
    """临时换权重跑一遍 pipeline ✓ —— 不写文件、跑完恢复原值。"""
    backup = dict(config.WEIGHTS)
    config.WEIGHTS.clear()
    config.WEIGHTS.update(weights)
    try:
        return pipeline.run(write=False)
    finally:
        config.WEIGHTS.clear()
        config.WEIGHTS.update(backup)


def _stats(name, out, spy):
    fg = out["fg_index"].dropna()
    tgt = out["target_position"].dropna()
    z = pd.cut(fg, bins=ZONE_EDGES, labels=ZONE_NAMES, include_lowest=True)
    shares = (z.value_counts(normalize=True).reindex(ZONE_NAMES) * 100)
    st = {
        "name": name,
        "n": int(len(fg)),
        "mean": round(float(fg.mean()), 2),
        "std": round(float(fg.std()), 2),
        "p10": round(float(fg.quantile(0.10)), 1),
        "p90": round(float(fg.quantile(0.90)), 1),
        "min": round(float(fg.min()), 1),
        "max": round(float(fg.max()), 1),
        "target_mean": round(float(tgt.mean()) * 100, 2),
        # 换手 = 目标仓位逐日变动绝对值之和（pp）⇒ 衡量调仓频率 ✓
        "turnover_pp": round(float(tgt.diff().abs().sum()) * 100, 1),
        "zones": {k: round(float(v), 1) for k, v in shares.items()},
    }
    if spy is not None:
        ev = evaluate(fg, spy, horizons=(20,), window=60)
        s = ev[20]["stats"]
        if s:
            st["ic"] = round(s["ic_mean"], 3)
            st["icir_adj"] = round(s["icir"], 2)
            st["icir_raw"] = round(s["icir_raw"], 2)
    return st


def main():
    new = dict(config.WEIGHTS)
    print("旧权重:", OLD)
    print("新权重:", new)
    print("波动率族: %.1f%% → %.1f%%"
          % ((OLD["vix"] + OLD["term"]) * 100,
             (new["vix"] + new["term"]) * 100))

    wide = pipeline.load_wide()
    spy = (wide[("SPY", "close")].astype(float)
           if ("SPY", "close") in wide.columns else None)
    if spy is None:
        print("⚠️ 取不到 SPY 收盘价 ⇒ 跳过 IC 计算")

    rows = []
    for name, w in (("旧", OLD), ("新", new)):
        out = _run_with(w)
        st = _stats(name, out, spy)
        rows.append(st)
        print("\n=== [%s权重] ===" % name)
        for k in ("n", "mean", "std", "p10", "p90", "min", "max",
                  "target_mean", "turnover_pp", "ic", "icir_adj", "icir_raw"):
            if k in st:
                print("  %-12s %s" % (k, st[k]))
        print("  五档占比     %s" % st["zones"])

    o, n = rows[0], rows[1]
    print("\n=== 差异（新 − 旧）===")
    print("  fg_index 均值   %+.2f" % (n["mean"] - o["mean"]))
    print("  fg_index 标准差 %+.2f" % (n["std"] - o["std"]))
    print("  target 均值     %+.2f pp" % (n["target_mean"] - o["target_mean"]))
    print("  换手            %+.1f pp（%.1f → %.1f）"
          % (n["turnover_pp"] - o["turnover_pp"],
             o["turnover_pp"], n["turnover_pp"]))
    for z in ZONE_NAMES:
        d = n["zones"][z] - o["zones"][z]
        print("  %-6s 占比    %+.1f pp（%.1f%% → %.1f%%）"
              % (z, d, o["zones"][z], n["zones"][z]))
    if "ic" in o and "ic" in n:
        print("  IC              %+.3f（%.3f → %.3f）"
              % (n["ic"] - o["ic"], o["ic"], n["ic"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
