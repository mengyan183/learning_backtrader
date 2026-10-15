# -*- coding: utf-8 -*-
"""趋势过滤贡献度归因（设计文档 §8.4）。

目的：量化 v2 核心改动（趋势过滤）的实际价值。设计文档 §12 风险 7 明确：
**若贡献度接近零，说明修正无效，应回到验收报告的选项 A（降低核心仓上限），
而不是继续调趋势过滤的参数。**

⚠️ **MT-21 已推翻该建议**：生产口径实测趋势过滤为 **−5.90% 收益 / +1.72pp 回撤**，
即「收益略降但回撤改善」。收益维度为负**不等于**应回退核心仓上限；是否保留趋势过滤
取决于收益/回撤偏好，须结合 `max_drawdown_table` 的 `mdd_delta` 人工裁决。

做法：构造一条「不带趋势过滤」的对照仓位序列，两条路径都按同一价格序列算收益。

**裁决 B（2026-10-12，WT-22）**：v1 的 `target_position = core_position + ammo`
（**无 trend 乘法**）⇒ 在 v1 数据上「关闭趋势过滤」= 原样返回。

**接线（P-2026-10-12-trend-wiring，C-3 已批）**：`run_equity_v2()` 现已把趋势过滤
真实接进 target（选项 ii：`target[T] = core[T-1]×trend[T-1] + ammo[T-1]`，弹药豁免，
见 `pipeline.run_equity_v2`）。因此「关闭趋势过滤」的对照 = **还原未接线版**
（`core[T-1] + ammo[T-1]`），见 `without_trend`——它不再是原样返回。
"""
import pandas as pd


def without_trend(features):
    """构造「关闭趋势过滤」的对照 features —— **还原未接线版**。

    ============================================================================
    接线后的对照语义（P-2026-10-12-trend-wiring）
    ============================================================================
    归因的目标是回答「**趋势过滤到底贡献了多少**」，因此对照必须是
    「把趋势过滤关掉之后的同一条仓位序列」。

    接线后（选项 ii）：`target[T] = core[T-1] × trend[T-1] + ammo[T-1]`
    （`trend ∈ {TREND_FILTER_FACTOR=0.5, 1.0}`，blocked 日核心仓打折、弹药豁免）。

    关闭趋势过滤 ⇒ `target_no_trend[T] = core[T-1] + ammo[T-1]`：
    用 features 里**未 shift** 的 `core_position` / `ammo_position` 各 `shift(1)`
    还原（与 v1 `run()` 的 target shift(1) 语义对齐，pipeline.py:119-120）；
    warmup（v1 target 为 NaN）行保持 NaN。

    ⚠️ 历史（裁决 B，WT-22）：接线前 v1 target 从未乘 trend ⇒ 对照=原样返回。
    接线后该前提不再成立，必须还原；若将来改回不接线或改用其他折扣公式，
    此处对照须同步重校。
    """
    out = features.copy()
    if "core_position" not in out.columns or "ammo_position" not in out.columns:
        # 缺列（守卫测试的纯 features 场景）：保守原样返回
        return out
    prev_core = out["core_position"].shift(1)
    prev_ammo = out["ammo_position"].shift(1).fillna(0.0)
    restored = (prev_core + prev_ammo).where(out["target_position"].notna())
    out["target_position"] = restored
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

    min_delta 是「有效」的最低累计**收益改善**阈值（默认 2 个百分点），
    即 `delta` 为**有符号**值，**不是** `abs(delta)`：负贡献（拖累收益）
    应判 effective=False 并如实报负。

    ⚠️ MT-21：本函数**只看收益表**，没有资格对「核心仓上限」等回撤维度下结论；
    负贡献分支的结论一律以 `max_drawdown_table` 的 `mdd_delta` 为准，人工裁决。
    """
    delta = float(table["return_delta"].iloc[0])
    blocked_days = int(table["blocked_days"].iloc[0])
    effective = delta >= min_delta and blocked_days > 0
    if blocked_days == 0:
        reason = "趋势过滤从未触发（blocked_days=0），本次回测无法评估其价值"
    elif delta <= -min_delta:
        reason = ("趋势过滤贡献度 %.2f%%（**负**贡献，拖累收益）—— 是否保留取决于收益/回撤偏好，"
                  "请结合 max_drawdown_table 的 mdd_delta 人工裁决；**不得**据此回退核心仓上限"
                  % (delta * 100))
    elif not effective:
        reason = ("趋势过滤贡献度 %.2f%% < 阈值 %.2f%%，收益维度未显示价值 —— "
                  "结论以 max_drawdown_table 为准" % (delta * 100, min_delta * 100))
    else:
        reason = "趋势过滤贡献度 %.2f%%，收益维度为正" % (delta * 100)
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
