# -*- coding: utf-8 -*-
"""加密双轨回测与组合评估（设计文档 §8.1–8.4）。

**双轨的定位（必须在所有输出中保持）**：
  - 合成轨：验证**策略逻辑**（五档/趋势过滤/弹药档位在完整加密周期中的行为）
  - 真实轨：验证**产品损耗**与合成质量门

任何基于合成轨的收益数字都必须带 `track="synthetic"` 标签，禁止与真实轨混淆。
"""
import os

import numpy as np
import pandas as pd

from fg_system import config
from fg_system.backtest.runner import performance_metrics

TRACK_SYNTHETIC = "synthetic"
TRACK_REAL = "real"


def _price_series(prices, symbol):
    return (prices[prices["symbol"] == symbol]
            .set_index("date")["close"].sort_index())


def track_metrics(prices, symbol, track=TRACK_SYNTHETIC):
    """单标的买入持有的指标（作为该轨的基准）。"""
    s = _price_series(prices, symbol)
    if s.empty:
        return {"track": track, "symbol": symbol, "annual_return": float("nan"),
                "max_drawdown": float("nan")}
    m = performance_metrics(s.pct_change().dropna())
    m["track"] = track
    m["symbol"] = symbol
    return m


def evaluate_symbol(prices, symbol, track=TRACK_SYNTHETIC):
    """评估单个加密标的。返回结果字典（含 track 标签）。"""
    return {
        "symbol": symbol,
        "track": track,
        "buy_and_hold": track_metrics(prices, symbol, track),
    }


def cross_market_correlation(us_close, crypto_close, min_points=60):
    """两市场日收益相关性（设计文档 §12 风险 8）。"""
    joined = pd.concat(
        [us_close.pct_change().rename("us"), crypto_close.pct_change().rename("cr")],
        axis=1).dropna()
    if len(joined) < min_points:
        return float("nan")
    return float(joined["us"].corr(joined["cr"]))


def crisis_correlation(us_close, crypto_close, threshold=0.7, window=60):
    """危机期（滚动窗口内两市场同时下跌）的相关性 + 告警。

    取「两市场滚动收益都为负」的区间计算相关性——这是统一资金池最危险的场景：
    一个市场崩盘会同时拖累另一个的仓位。
    """
    joined = pd.concat(
        [us_close.pct_change().rename("us"), crypto_close.pct_change().rename("cr")],
        axis=1).dropna()
    if len(joined) < window:
        return {"correlation": float("nan"), "warning": False,
                "reason": "样本不足 %d 个交易日" % window}

    us_roll = joined["us"].rolling(window).sum()
    cr_roll = joined["cr"].rolling(window).sum()
    mask = (us_roll < 0) & (cr_roll < 0)
    subset = joined[mask]
    if len(subset) < 30:
        return {"correlation": float("nan"), "warning": False,
                "reason": "两市场同时下跌的区间不足 30 天，无法评估"}

    corr = float(subset["us"].corr(subset["cr"]))
    warn = corr > threshold
    return {
        "correlation": corr,
        "warning": warn,
        "reason": ("危机期相关性 %.2f > %.2f，统一资金池存在隐性集中风险，"
                   "需重新评估（§12 风险 8）" % (corr, threshold)) if warn
        else "危机期相关性 %.2f，在可接受范围" % corr,
    }


def layer_contribution(prices):
    """加密三层的收益贡献（设计文档 §8.4）。"""
    rows = []
    for layer, symbols in config.CRYPTO_SYMBOLS.items():
        for sym in symbols:
            s = _price_series(prices, sym)
            if s.empty:
                continue
            m = performance_metrics(s.pct_change().dropna())
            rows.append({
                "layer": layer, "symbol": sym,
                "annual_return": m["annual_return"],
                "max_drawdown": m["max_drawdown"],
                "cap": config.CRYPTO_LAYER_CAP[layer],
            })
    if not rows:
        return pd.DataFrame(columns=["layer", "symbol", "annual_return",
                                     "max_drawdown", "cap"])
    return pd.DataFrame(rows)


def report(synthetic_path=None, real_path=None):
    """生成加密双轨评估报告（设计文档 §8.4）。"""
    synthetic_path = synthetic_path or config.SYNTHETIC_PATH
    real_path = real_path or config.CRYPTO_PRICES_PATH

    out = {"synthetic": [], "real": []}

    if os.path.exists(synthetic_path):
        syn = pd.read_csv(synthetic_path, dtype={"symbol": str}, parse_dates=["date"])
        out["synthetic"] = [evaluate_symbol(syn, s, TRACK_SYNTHETIC)
                            for s in config.CRYPTO_FLAT_SYMBOLS
                            if not _price_series(syn, s).empty]

    if os.path.exists(real_path):
        real = pd.read_csv(real_path, dtype={"symbol": str}, parse_dates=["date"])
        out["real"] = [evaluate_symbol(real, s, TRACK_REAL)
                       for s in config.CRYPTO_FLAT_SYMBOLS
                       if not _price_series(real, s).empty]
        out["layer_contribution"] = layer_contribution(real)

    if os.path.exists(config.CRYPTO_UNDERLYING_PATH):
        out["btc_close"] = pd.read_csv(
            config.CRYPTO_UNDERLYING_PATH, parse_dates=["date"]
        ).set_index("date")["close"].sort_index()

    return out


# ---------------------------------------------------------------- v2.5 组合级口径
def portfolio_backtest(prices_long, target_position, weights, fg_index=None):
    """加密**组合级**策略回测（第 4B.7 条 / 第 12.8 条）。

    把加密各标的按权重合成篮子，再对篮子跑与大盘**同一套** `FgStrategy`。

    **为什么必须合成单篮子**（v2.3 的教训）：`FgStrategy` 的执行约束
    （`REBALANCE_THRESHOLD` 10pp、`MAX_SINGLE_ADJUST` 30pp）是**绝对值**。
    若把各标的拆成独立 sleeve 各自跑回测，每条 sleeve 的目标只有组合的
    几分之一，**低于 10pp 阈值 ⇒ 策略几乎不交易** ⇒ 结果被执行假象主导
    （实测曾算出比任何单标的都差的回撤）。

    `target_position` 必须是**加密 sleeve 的目标仓位**（加密核心仓 + **加密自己的**
    弹药，见 `pipeline.run_portfolio` 的 `ammo_crypto`），**不是**全组合目标——
    否则会把大盘的仓位算到加密头上。

    返回策略日收益序列（index 与 target_position 对齐）；无有效数据时返回 None。
    """
    from fg_system import pipeline
    from fg_system.backtest import runner

    wide = pipeline.long_to_wide(prices_long)
    idx = target_position.index
    # **只保留该轨实际存在的标的，并对权重重新归一化**（v2.8，第 12.23 条）。
    # 真实轨（`crypto_prices.csv`）没有「BTC 现货杠杆」这个产品——它是用户的
    # **实盘仓位**，不是可下载的 ETF，故 BTC 只存在于合成轨。
    # 硬性要求全部标的会 KeyError（实测），而真实轨的用途只是「验证合成轨是否可信」，
    # 只能验证存在的部分，故丢弃 + 归一化是正确行为，不是降级。
    symbols = [s for s in weights.index if (s, "close") in wide.columns]
    if not symbols:
        return None
    w_sum = float(weights.reindex(symbols).sum())
    if w_sum <= 0:
        return None
    w = pd.DataFrame(
        np.tile((weights.reindex(symbols) / w_sum).to_numpy(), (len(idx), 1)),
        index=idx, columns=symbols)
    px = pipeline.basket_price_series(
        pipeline.weighted_basket_returns(wide, w)).reindex(idx)

    f = pd.DataFrame({
        "target_position": target_position,
        "fg_index": (fg_index.reindex(idx) if fg_index is not None else 0.0),
        "zone": 2.0,
        "volume": 0.0,
    })
    for col in ("open", "high", "low", "close"):
        f[col] = px
    f = f.dropna(subset=["target_position", "close"])
    if f.empty:
        return None
    _, returns = runner.run_single(f, "CRYPTO_BASKET")
    return returns


def print_report(out, us_close=None):
    """把双轨报告打印成人可读格式（供 CLI 与验收报告使用）。"""
    for track in (TRACK_SYNTHETIC, TRACK_REAL):
        label = "合成轨（仅验证策略逻辑，不代表真实预期）" if track == TRACK_SYNTHETIC \
            else "真实轨（用于产品损耗校验）"
        print("=== %s ===" % label)
        for e in out.get(track) or []:
            m = e["buy_and_hold"]
            print("  %-6s 年化 %+8.2f%%   最大回撤 %+8.2f%%" % (
                e["symbol"], m["annual_return"] * 100, m["max_drawdown"] * 100))
        print()

    lc = out.get("layer_contribution")
    if lc is not None and not lc.empty:
        print("=== 加密三层贡献（真实轨）===")
        for _, r in lc.iterrows():
            print("  %-16s %-6s 年化 %+8.2f%%  回撤 %+8.2f%%  层上限 %.0f%%" % (
                r["layer"], r["symbol"], r["annual_return"] * 100,
                r["max_drawdown"] * 100, r["cap"] * 100))
        print()

    btc = out.get("btc_close")
    if btc is not None and us_close is not None:
        print("=== 跨市场相关性（设计文档 §12 风险 8）===")
        print("  全区间相关性: %.3f" % cross_market_correlation(us_close, btc))
        cc = crisis_correlation(us_close, btc)
        print("  危机期相关性: %.3f" % cc["correlation"])
        print("  判定: %s" % cc["reason"])
