# -*- coding: utf-8 -*-
"""趋势过滤贡献度归因（设计文档 §8.4）。

目的：量化 v2 核心改动（趋势过滤）的实际价值。设计文档 §12 风险 7 明确：
**若贡献度接近零，说明修正无效，应回到验收报告的选项 A（降低核心仓上限），
而不是继续调趋势过滤的参数。**

做法：构造一条「不带趋势过滤」的对照仓位序列，两条路径都按同一价格序列算收益。

**裁决 B（2026-10-12，WT-22）**：生产入口 `run_equity_v2()` = v1 `run()` + 追加
趋势列，而 v1 的 `target_position = core_position + ammo`（**无 trend 乘法**）
⇒ 趋势折扣**从未乘进** v1 的 target。因此「关闭趋势过滤」的对照就是
**原样返回**（见 `without_trend`）；blocked 行**不再** ÷`TREND_FILTER_FACTOR`
——旧做法会把仓位**翻倍**（实测 0.5→1.0），使归因表与 `verdict()` 失真、
**夸大**趋势过滤的贡献。

⚠️ 由此推论：在 v1 数据上 `contribution_table` 的两条路径**逐行相同** ⇒
`return_delta` / `mdd_delta` 恒为 **0** ⇒ `verdict()` 恒判「贡献度接近零」。
这本身就是「趋势过滤在 v1 仓位口径下未产生任何差异」的**正确结论**，
指向验收报告选项 A（降低核心仓上限）。若将来接入 v2.5 口径（target 真的乘过
`trend`），需在 `without_trend` 处做对应还原并重新校准归因。
"""
import pandas as pd


def without_trend(features):
    """构造「关闭趋势过滤」的对照 features —— **原样返回**。

    ============================================================================
    为什么「原样返回」才是正确对照（裁决 B，2026-10-12 WT-22）
    ============================================================================
    归因的目标是回答「**趋势过滤到底贡献了多少**」，因此对照必须是
    「把趋势过滤关掉之后的同一条仓位序列」。

    早先的实现假设 `target_position` 里**已经乘过** `TREND_FILTER_FACTOR`
    （即被过滤时打过折），于是在 `trend_blocked=True` 处把它 ÷ factor「还原」。
    这个前提**与实际数据不符、从未成立**：

    - 生产调用方是 `pipeline.run_equity_v2()`，它 = v1 `run()` + 追加趋势列
      （`trend` / `trend_blocked`），**v1 的 target 逐字不变**。
    - v1 `run()` 里 `target_position = legacy.core_position + ammo`（见
      `pipeline.py` 第 96 行），**没有任何 trend 乘法**。
    - 趋势折扣只存在于两处：`market_signal.trend_factor_series`（算出 `trend`）与
      `run_portfolio`（v2.5 组合级）里 —— 二者都**没有**把它乘进 v1 的 target。

    因此对 v1 数据而言，「关闭趋势过滤」= **无变化**，blocked 行**不得**再 ÷0.5。
    Mac 用真实数据实测：blocked 行 target/core 比值中位 **1.198**（0.864~2.093，
    含弹药），**绝非 0.5** —— 旧实现的 ÷0.5 会把仓位**翻倍**（实测 0.5→1.0），
    凭空造出一段「对照路径」，既**夸大**趋势过滤的收益贡献，又只压低对照的回撤，
    使 `contribution_table` 与 `verdict()` 双双失真。

    结论：对 **v1 数据**（target 未含趋势折扣）本函数原样返回
    （保留为具名函数，是为了让「对照」这一语义在调用处显式可见；
    将来若接入 v2.5 口径、target 真的乘过 trend，再在此处做对应还原）。

    ⚠️ 团队评审 S-4 曾建议此处加 shift(1)，**已核实不成立、未采纳**（见
    docs/notes/2026-10-12-s234-fixes.md）：生产调用方用的 `run_equity_v2()`
    直接返回 v1 `run()` 的结果再追加趋势列，`target_position` 与 `trend_blocked`
    是**同一行对齐**的；`run()` 里的 shift(1) 发生在 `run_equity_v2` 之前，
    不改变这两列的相对对齐。
    """
    return features.copy()


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
