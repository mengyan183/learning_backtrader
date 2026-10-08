#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-2 回测基准恢复：跑基准回测 → evolution/baseline.json（进化阶段②）。

roadmap 验收口径（docs/roadmap.md 第一层「恢复基准」）：
  baseline.json = 年化 / 最大回撤 / Calmar / 逐年 / 分市场归因，IS/OOS 划分。

**纪律**：
  - 只读数据与回测，**不改任何参数**（config.py 参数为"先验值，禁止优化"）。
  - LLM 永不判决：本脚本产出的是"证据文件"，供后续变体/提案对比。
  - IS/OOS 划分口径在 meta 中显式声明（时间序 80/20，可复现，不隐含调参）。

用法：
  .venv/bin/python scripts/evolve_baseline.py [--out evolution/baseline.json]

输出：
  evolution/baseline.json —— 结构化基准绩效（全区间/逐年/IS/OOS/归因/加密轨）。
"""
import argparse
import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fg_system import config, leverage
from fg_system.backtest import attribution, crypto_runner, runner


def _split_is_oos(returns, is_ratio=0.8):
    """时间序 80/20 划分（IS = 前 80%，OOS = 后 20%）。

    口径在 meta 中声明：`method="time_80_20"`。研究通道约定，非参数调优。
    """
    r = pd.Series(returns).dropna().sort_index()
    if r.empty:
        return r, r
    cut = int(len(r) * is_ratio)
    return r.iloc[:cut], r.iloc[cut:]


def _round(x, nd=6):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return x


def _metrics_dict(returns):
    m = runner.performance_metrics(pd.Series(returns).dropna())
    return {k: _round(v) for k, v in m.items()}


def _yearly_dict(returns):
    t = runner.yearly_table(pd.Series(returns).dropna())
    out = {}
    for year, row in t.iterrows():
        out[str(year)] = {k: _round(v) for k, v in row.items()}
    return out


def build_symbol(features_all, prices, symbol):
    """单个标的：策略 vs 买入持有，全区间/逐年/IS/OOS。"""
    f = features_all.copy()
    p = prices[prices["symbol"] == symbol].set_index("date").sort_index()
    f = f.join(p[["open", "high", "low", "close", "volume"]], how="inner")
    strat, returns = runner.run_single(f, symbol)
    bh = p["close"].pct_change().dropna() if len(p) else None

    is_r, oos_r = _split_is_oos(returns)
    out = {
        "strategy": {
            "full": _metrics_dict(returns),
            "yearly": _yearly_dict(returns),
            "is": _metrics_dict(is_r),
            "oos": _metrics_dict(oos_r),
        },
    }
    if bh is not None:
        is_bh, oos_bh = _split_is_oos(bh)
        out["buy_and_hold"] = {
            "full": _metrics_dict(bh),
            "yearly": _yearly_dict(bh),
            "is": _metrics_dict(is_bh),
            "oos": _metrics_dict(oos_bh),
        }
    return out


def build_attribution(features, prices):
    """分市场归因：损耗归因（§11.6）+ 趋势过滤贡献度（§8.4）。

    - `prices`：长表（date,symbol,close），损耗归因直接用。
    - 趋势过滤归因需要 `close` **单列序列** + features 含 `trend_blocked` 列；
      features.csv（信号文件）无 `trend_blocked` ⇒ 如实记录「未评估」，
      不编造 blocked_days（归因只在 run_equity_v2 产出的 features 上有效）。
    """
    out = {}
    loss = leverage.attribution_table(prices)
    if loss is not None and not loss.empty:
        cols = [c for c in loss.columns if c != "date"]
        out["loss"] = [dict(r) for _, r in loss[cols].iterrows()]
    if "trend_blocked" not in features.columns:
        out["trend_filter"] = {
            "evaluated": False,
            "reason": ("features.csv 无 trend_blocked 列（信号文件口径，非 "
                       "run_equity_v2 产物），趋势过滤贡献度无法评估——"
                       "需以 run_equity_v2 产出的 features 重跑才可归因"),
        }
        return out
    close = (prices[prices["symbol"] == config.SYMBOLS[0]]
             .set_index("date")["close"].sort_index())
    trend = attribution.full_report(features, close)
    if trend is not None and not trend.empty:
        out["trend_filter"] = {k: _round(v) for k, v in trend.iloc[0].items()}
    return out


def build_crypto():
    """加密双轨（数据存在时输出摘要；不存在时输出空结构）。"""
    out = {"available": False}
    rep = crypto_runner.report()
    synth, real = rep.get("synthetic") or [], rep.get("real") or []
    if synth or real:
        out["available"] = True
        out["synthetic"] = [{
            "symbol": e["symbol"],
            "buy_and_hold": {k: _round(v) for k, v in e["buy_and_hold"].items()},
        } for e in synth]
        out["real"] = [{
            "symbol": e["symbol"],
            "buy_and_hold": {k: _round(v) for k, v in e["buy_and_hold"].items()},
        } for e in real]
    lc = rep.get("layer_contribution")
    if lc is not None and not lc.empty:
        out["layer_contribution"] = [dict(r) for _, r in lc.iterrows()]
    btc = rep.get("btc_close")
    if btc is not None:
        s = btc.pct_change().dropna()
        out["btc_buy_and_hold"] = _metrics_dict(s)
        us = pd.read_csv(config.RAW_DIR + "/prices.csv",
                         parse_dates=["date"])
        us_close = us[us["symbol"] == "SPY"]["close"]
        if len(us_close):
            us_close = us_close.set_axis(btc.index[:len(us_close)])
            out["crisis_correlation"] = crypto_runner.crisis_correlation(
                us_close, btc)
    return out


def main():
    ap = argparse.ArgumentParser(description="A-2 回测基准恢复")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(__file__), "..", "evolution", "baseline.json"))
    args = ap.parse_args()

    features = pd.read_csv(config.FEATURES_PATH, parse_dates=["date"])
    features_all = features.set_index("date")
    prices = pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"),
                         parse_dates=["date"])

    symbols = {}
    for sym in config.SYMBOLS:
        d = build_symbol(features_all, prices, sym)
        symbols[sym] = d
        print("  %-5s 策略年化 %+7.2f%%  回撤 %+7.2f%%  Calmar %.3f | "
              "买入持有年化 %+7.2f%%  回撤 %+7.2f%%" % (
                  sym,
                  d["strategy"]["full"]["annual_return"] * 100,
                  d["strategy"]["full"]["max_drawdown"] * 100,
                  d["strategy"]["full"]["calmar"],
                  d["buy_and_hold"]["full"]["annual_return"] * 100,
                  d["buy_and_hold"]["full"]["max_drawdown"] * 100))

    # IS/OOS 分割点（以首个标的的收益序列计算，口径全仓一致）
    _, first_returns = runner.run_single(
        features_all.copy().join(
            prices[prices["symbol"] == config.SYMBOLS[0]]
            .set_index("date")[["open", "high", "low", "close", "volume"]],
            how="inner"), config.SYMBOLS[0])
    is_r, oos_r = _split_is_oos(first_returns)
    is_end = is_r.index[-1] if len(is_r) else None
    oos_start = oos_r.index[0] if len(oos_r) else None

    baseline = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "features_path": config.FEATURES_PATH,
            "features_range": [str(features["date"].min().date()),
                               str(features["date"].max().date())],
            "symbols": list(config.SYMBOLS),
            "is_oos": {"method": "time_80_20",
                       "is_end": str(is_end.date()) if is_end is not None else None,
                       "oos_start": (str(oos_start.date())
                                     if oos_start is not None else None)},
            "note": ("基准绩效，只读不改参；LLM 不判案；"
                     "变体必须与此文件对比（evolution-plan 阶段②）"),
        },
        "symbols": symbols,
        "attribution": build_attribution(features_all, prices),
        "crypto": build_crypto(),
    }

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(baseline, fh, ensure_ascii=False, indent=1, default=str)

    # 验收断言：baseline.json 非 pending（每个标的策略 annual_return 必须非 NaN）
    for sym, d in symbols.items():
        ar = d["strategy"]["full"]["annual_return"]
        if ar != ar:  # NaN
            sys.exit("❌ %s 策略年化为 NaN —— baseline 未就绪" % sym)
    print("\n✅ baseline.json 已写入 %s" % out_path)
    print("   IS 截至 %s / OOS 自 %s 起（时间序 80/20）" % (is_end, oos_start))


if __name__ == "__main__":
    main()
