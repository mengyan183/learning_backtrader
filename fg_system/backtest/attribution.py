# -*- coding: utf-8 -*-
"""趋势过滤贡献度归因（设计文档 §8.4）。

目的：量化 v2 核心改动（趋势过滤）的实际价值。设计文档 §12 风险 7 明确：
**若贡献度接近零，说明修正无效，应回到验收报告的选项 A（降低核心仓上限），
而不是继续调趋势过滤的参数。**

做法：把 features 的 target_position 在「趋势过滤生效」处还原为未打折值，
得到一条「不带趋势过滤」的对照仓位序列，两条路径都按同一价格序列算收益。
"""
import pandas as pd

from fg_system import config


def without_trend(features):
    """构造「关闭趋势过滤」的对照 features。

    在 trend_blocked=True 处，把 target_position 除以 TREND_FILTER_FACTOR
    还原为未打折值（上限 1.0）。
    """
    out = features.copy()
    if "trend_blocked" not in out.columns:
        return out
    blocked = out["trend_blocked"].fillna(False).astype(bool)
    restored = out["target_position"] / config.TREND_FILTER_FACTOR
    out.loc[blocked, "target_position"] = restored[blocked].clip(upper=1.0)
    return out


def _path_return(targets, prices):
    """按目标仓位持有，计算累计收益。

    简化口径：以「目标仓位 × 标的日收益」累乘。这里不引入 backtrader——
    归因的目的是**比较两条路径的差异**，不是模拟真实撮合；用同一套简化口径
    比较才公平（撮合成本在两条路径上相同，会在差分中抵消）。
    """
    ret = prices.pct_change().fillna(0.0)
    pos = targets.shift(1).fillna(0.0)     # T 日仓位在 T 日生效需再 shift
    strat_ret = pos * ret
    return float((1.0 + strat_ret).prod() - 1.0)


def contribution_table(features, prices):
    """趋势过滤贡献度表。返回单行 DataFrame。"""
    with_trend = features["target_position"]
    without = without_trend(features)["target_position"]
    prices = prices.reindex(features.index)

    r_with = _path_return(with_trend, prices)
    r_without = _path_return(without, prices)

    blocked = features["trend_blocked"].fillna(False).astype(bool)
    return pd.DataFrame([{
        "with_trend_return": r_with,
        "without_trend_return": r_without,
        "return_delta": r_with - r_without,
        "blocked_days": int(blocked.sum()),
        "blocked_ratio": float(blocked.mean()) if len(blocked) else 0.0,
    }])


def max_drawdown_table(features, prices):
    """两条路径的最大回撤对比（回撤优先目标的核心指标）。"""
    prices = prices.reindex(features.index)

    def _mdd(targets):
        ret = prices.pct_change().fillna(0.0)
        pos = targets.shift(1).fillna(0.0)
        cum = (1.0 + pos * ret).cumprod()
        return float((cum / cum.cummax() - 1.0).min())

    with_trend = _mdd(features["target_position"])
    without = _mdd(without_trend(features)["target_position"])
    return pd.DataFrame([{
        "with_trend_mdd": with_trend,
        "without_trend_mdd": without,
        "mdd_delta": with_trend - without,   # 正值 = 趋势过滤降低了回撤
    }])


def verdict(table, min_delta=0.02):
    """判定趋势过滤是否有效（设计文档 §12 风险 7）。

    min_delta 是「有效」的最低累计收益改善（默认 2 个百分点）。
    低于此值 → effective=False，并给出应回退到「降低核心仓上限」的建议。
    """
    delta = float(table["return_delta"].iloc[0])
    blocked_days = int(table["blocked_days"].iloc[0])
    effective = abs(delta) >= min_delta and blocked_days > 0
    if blocked_days == 0:
        reason = "趋势过滤从未触发（blocked_days=0），本次回测无法评估其价值"
    elif not effective:
        reason = ("趋势过滤贡献度 %.2f%% < 阈值 %.2f%%，修正无效 → "
                  "应回到验收报告选项 A（降低核心仓上限），不要继续调趋势参数"
                  % (delta * 100, min_delta * 100))
    else:
        reason = "趋势过滤贡献度 %.2f%%，有效" % (delta * 100)
    return {"effective": effective, "delta": delta,
            "blocked_days": blocked_days, "reason": reason}


def full_report(features, prices):
    """合并收益与回撤两张表，供验收报告直接引用。"""
    ret = contribution_table(features, prices)
    dd = max_drawdown_table(features, prices)
    out = pd.concat([ret, dd], axis=1)
    v = verdict(ret)
    out["effective"] = v["effective"]
    out["reason"] = v["reason"]
    return out
