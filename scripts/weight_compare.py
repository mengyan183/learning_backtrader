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


def _portfolio(feats, prices, oos_start):
    """用**同一份 prices + 同一个 OOS 起点**跑组合回测 ✓（不写任何文件）。

    🔴 为什么不能直接拿 `portfolio_backtest.py` 的历史报告对比 ✗：
       旧基线（2026-10-11）的数据窗口只到 10-11，而今天跑的数据窗口到 11-19
       ⇒ **多出的 5 周恰好是暴跌段** ⇒ B0（买入持有）的年化从 75.45% 掉到
         28.09%（B0 与权重无关，是纯市场效应）✗
       ⇒ 拿「旧基线 37.66% vs 今天 11.81%」说「权重改坏了」是**错的归因** ✗
       ⇒ 必须同一数据窗口、同一 OOS 起点，只换权重 ✓

    ⚠️ 需要 `backtrader`（仅 Mac 有）⇒ 失败时返回 {"error": ...}，不中断统计部分 ✓
    """
    try:
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import portfolio_backtest as pb
    except Exception as exc:               # noqa: BLE001
        return {"error": "无法加载回测引擎：%s" % exc}
    try:
        return pb.build_portfolio(feats, prices, oos_start=oos_start)
    except Exception as exc:               # noqa: BLE001
        return {"error": "回测失败：%s" % exc}


def _show_bt(name, bt):
    if "error" in bt:
        print("\n=== [%s权重] 组合回测 —— %s ===" % (name, bt["error"]))
        return
    m = bt["metrics"]
    p, b = m["portfolio"], m["buyhold"]
    print("\n=== [%s权重] 组合回测（OOS 自 %s）===" % (name, bt["oos_start"]))
    for tag, key in (("OOS", "oos"), ("IS", "is")):
        pm, bm = p[key], b[key]
        print("  %-4s 年化 %7.2f%% | 回撤 %7.2f%% | Sharpe %5.2f | Calmar %5.2f"
              " || B0 年化 %7.2f%%"
              % (tag, pm["annual_return"] * 100, pm["max_drawdown"] * 100,
                 pm["sharpe"], pm["calmar"], bm["annual_return"] * 100))


def main():
    import argparse

    ap = argparse.ArgumentParser(description="新旧权重的信号 / 回测对比")
    ap.add_argument("--backtest", action="store_true",
                    help="同时跑组合回测 A/B（需 backtrader，仅 Mac 可用）")
    args = ap.parse_args()

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

    rows, outs = [], {}
    for name, w in (("旧", OLD), ("新", new)):
        out = _run_with(w)
        outs[name] = out
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

    if args.backtest:
        print("\n" + "=" * 62)
        print("组合回测 A/B（**同一份 prices、同一个 OOS 起点**，只换权重）")
        print("=" * 62)
        prices = pd.read_csv(os.path.join(REPO, "Data", "raw", "prices.csv"),
                             parse_dates=["date"])
        oos = _oos_start()
        bts = {}
        for name in ("旧", "新"):
            bts[name] = _portfolio(outs[name], prices, oos)
            _show_bt(name, bts[name])
        a, b = bts["旧"], bts["新"]
        if "error" not in a and "error" not in b:
            pa, pb_ = a["metrics"]["portfolio"]["oos"], b["metrics"]["portfolio"]["oos"]
            print("\n=== 回测差异（新 − 旧，同为 OOS）===")
            print("  年化     %+7.2f pp（%.2f%% → %.2f%%）"
                  % ((pb_["annual_return"] - pa["annual_return"]) * 100,
                     pa["annual_return"] * 100, pb_["annual_return"] * 100))
            print("  最大回撤 %+7.2f pp（%.2f%% → %.2f%%）"
                  % ((pb_["max_drawdown"] - pa["max_drawdown"]) * 100,
                     pa["max_drawdown"] * 100, pb_["max_drawdown"] * 100))
            print("  Sharpe   %+7.2f（%.2f → %.2f）"
                  % (pb_["sharpe"] - pa["sharpe"], pa["sharpe"], pb_["sharpe"]))
    return 0


def _oos_start():
    """OOS 起点：**从回测脚本取**，不在本脚本里另写一份 ✗（口径唯一来源）。"""
    try:
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import portfolio_backtest as pb
        return pb.OOS_START
    except Exception:                      # noqa: BLE001
        return "2024-10-04"


if __name__ == "__main__":
    sys.exit(main())
