# -*- coding: utf-8 -*-
"""守猪待兔「清仓线」变体的定义与 core 序列计算（A1）。

设计：docs/superpowers/specs/2026-09-24-shoutu-variants-replay-design.md

**本模块只做纯计算**：不读文件、不打印、不做 I/O。
编排（读数据、跑回放、出表）在 `scripts/analyze_shoutu_variants.py`。

⚠️ 变体表是**先验定义**，不是从回测里搜出来的（第 8 条 / 第 13.1 条）。
"""
import pandas as pd

from fg_system import config, pipeline

# 基准（市场指数口径）的标识。它**不走本模块**（core=None），
# 只是给编排层一个统一的枚举值，避免在脚本里散落字符串。
BASELINE = "B0"

# 三个守猪待兔变体。`edges` / `saturation` 都是**系统口径（0~100）** ——
# 守猪待兔原值 → 系统口径的映射是 `(x + 100) / 2`（`loader.shoutu_to_system_scale`）。
#
# 先验推导（第 8 条：不是"试出来的"）：
#   V1 = 现状规则（守猪待兔 +60 ⇒ 系统 80 ⇒ 末档 sat 0.00 = 清仓）
#   V2 = 清仓线抬到守猪待兔 +80 ⇒ 系统 90 ⇒ **只把末档边界**从 80 挪到 90，
#        使 +60 ~ +80（系统 80 ~ 90）落在 sat 0.25（贪婪档）而不是 0.00
#   V3 = 不设清仓线 ⇒ **复用系统已有**的 `ZONE_SATURATION[3] = 0.25` 作末档
#        （与加密「减至 25% 底仓（不清仓——避免完全踏空后续反弹）」同语义）
#        ⇒ **不新造参数**（第 4B.6 条）
VARIANTS = {
    "V1": {"label": "守猪待兔 +60 清仓（现状）",
           "edges": [20.0, 40.0, 60.0, 80.0],
           "saturation": [1.00, 0.75, 0.50, 0.25, 0.00]},
    "V2": {"label": "守猪待兔 +80 才清仓",
           "edges": [20.0, 40.0, 60.0, 90.0],
           "saturation": [1.00, 0.75, 0.50, 0.25, 0.00]},
    "V3": {"label": "守猪待兔 不设清仓线（末档留 25% 底仓）",
           "edges": [20.0, 40.0, 60.0, 80.0],
           "saturation": [1.00, 0.75, 0.50, 0.25, 0.25]},
}

# 编排层要跑的**全部**变体键（含基准），顺序固定（基准在最前）。
VARIANT_KEYS = (BASELINE,) + tuple(VARIANTS)


def shoutu_wide_from_long(hist, symbols=None):
    """守猪待兔**长表** → 宽表（index = date，columns = symbol，值 = `score`）。

    `hist`：`loader.load_shoutu_history()` 的输出（列 `date,symbol,score,price`）。

    ⚠️ `hist` 为空、或**主样本三个标的一个都没有** ⇒ **抛错**。
    **不得**静默回退成基准 —— 那会把「变体无效应」伪装成「变体无差异」
    （spec §5.1）。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    if hist is None or hist.empty:
        raise ValueError("守猪待兔历史为空 —— 无法构造变体 core（不得静默回退成基准）")
    sub = hist[hist["symbol"].isin(symbols)]
    if sub.empty:
        raise ValueError(
            "守猪待兔历史里没有任何主样本标的 %s —— 无法构造变体 core" % (symbols,))
    return sub.pivot(index="date", columns="symbol", values="score").sort_index()


def variant_core_series(us_features, weights, hist, variant, symbols=None):
    """某个变体口径下的 `us_equity` 核心仓序列（**未 shift**）。

    `= CORE_CAP × MARKET_CORE_RATIO["us_equity"] × Σ_i(sat_i(edges_v, sat_v) · w_i) × trend`

    ⚠️ **必须复用** `pipeline.shoutu_symbol_index` / `pipeline.saturation_of` /
    `pipeline.risk_weight_series` —— **不得**在此重写档位查找或加权逻辑
    （第 12.26 条⑤：两套写法 = 「分析里的规则 ≠ 生产的规则」）。

    `us_features` **必须含 `trend` 列**（由 `run_equity_v2` 产出）；缺列 ⇒ 抛错。
    """
    if variant not in VARIANTS:
        raise KeyError("未知变体 %r；可选：%s" % (variant, tuple(VARIANTS)))
    if "trend" not in us_features.columns:
        raise ValueError("us_features 缺 trend 列（应由 pipeline.run_equity_v2 产出）")
    spec = VARIANTS[variant]
    wide = shoutu_wide_from_long(hist, symbols)
    return pipeline.shoutu_core_series(
        us_features, weights, shoutu_wide=wide, symbols=symbols,
        edges=spec["edges"], saturation=spec["saturation"])


def attribution_contributions(wide, weights, base, mask, symbols=None):
    """各标的的**加权贡献** `Σ_{t ∈ mask} base_t × w_i,t × r_i,t`。

    回答「谁在拖累」。⚠️ **不得**用逐 sleeve 回测替代（spec §2 事实 7：
    每条 sleeve 的目标只有组合的 1/3，低于 `REBALANCE_THRESHOLD` ⇒ 几乎不交易，
    是已知错误口径）。

    返回 Series（index = symbol）。**各标的之和 == `Σ_t base_t × 篮子收益_t`**
    （因 `篮子收益_t = Σ_i w_i,t × r_i,t`）—— 由
    `tests/test_shoutu_variants.py::test_attribution_sums_to_basket_return` 常驻守卫。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    rets = pd.DataFrame(
        {s: wide[(s, "close")] for s in symbols}).pct_change(fill_method=None)
    w = weights.reindex(rets.index).ffill()
    b = pd.Series(base).reindex(rets.index).fillna(0.0)
    contrib = w.mul(rets).mul(b, axis=0)
    m = pd.Series(mask).reindex(rets.index).fillna(False).astype(bool)
    return contrib[m].sum()
