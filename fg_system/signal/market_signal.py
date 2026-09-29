# -*- coding: utf-8 -*-
"""单市场信号层：五档 + 趋势过滤 + 分层上限 + 极端规则（§6.1–6.3、§6.5）。

硬性约定（§3.4）：纯函数 + 显式状态。禁止读写全局变量或文件。

优先级（§6.6）：趋势过滤 > 极端规则 > 五档映射 > 分层上限 > 共享弹药池。
本模块负责前四项；弹药池在 portfolio 层。

关于加密极贪档位与五档的关系（实施中发现并修正）：档位 > 0 时**替换**五档饱和度
（即设一个下限），**不是与之相乘**。因为五档在指数 >=80 时已给饱和度 0（清仓），
若写成相乘，档位永远对着 0 做乘法，成为死代码——这违背设计 §6.5 的初衷
（不一次性清仓、分批递减）。档位 = 0 时沿用五档饱和度。
"""
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fg_system import config

ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


@dataclass
class MarketState:
    """单市场状态机。所有字段可 JSON 序列化。"""

    market: str = "us_equity"
    circuit_breaker: bool = False
    cb_trigger_index: float = None
    cb_trigger_date: str = None
    cb_low_price: dict = field(default_factory=dict)
    greed_tier: int = 0                   # 加密极贪已触发档位数（0-3）
    last_extreme_fear_date: str = None

    def to_dict(self):
        return {
            "market": self.market,
            "circuit_breaker": self.circuit_breaker,
            "cb_trigger_index": self.cb_trigger_index,
            "cb_trigger_date": self.cb_trigger_date,
            "cb_low_price": dict(self.cb_low_price),
            "greed_tier": int(self.greed_tier),
            "last_extreme_fear_date": self.last_extreme_fear_date,
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        return cls(
            market=data.get("market", "us_equity"),
            circuit_breaker=bool(data.get("circuit_breaker", False)),
            cb_trigger_index=data.get("cb_trigger_index"),
            cb_trigger_date=data.get("cb_trigger_date"),
            cb_low_price=dict(data.get("cb_low_price") or {}),
            greed_tier=int(data.get("greed_tier", 0)),
            last_extreme_fear_date=data.get("last_extreme_fear_date"),
        )


@dataclass
class MarketOutput:
    """单市场的输出，供 portfolio 层消费。"""

    market: str
    core_position: float      # 已含趋势过滤与分层上限；None 表示无信号
    drawdown: float
    trend: float              # 1.0 或 TREND_FILTER_FACTOR
    trend_blocked: bool
    extreme_fear: bool
    extreme: bool             # 是否触发极端规则（用于豁免防抖动）
    layer_caps: dict
    note: str = ""


def _is_nan(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


def _copy(state):
    """返回独立副本（§3.4 硬约定：不得修改入参）。"""
    return MarketState.from_dict(state.to_dict())


# ---------------------------------------------------------------- 趋势过滤（§6.1）
def trend_factor_series(close, ma_days=None, factor=None):
    """趋势系数序列：收盘 < MA 时为 factor，否则 1.0。

    均线窗口不足处返回 1.0（不做限制）。这与 v1 §10.4「不足窗口返回 NaN」不冲突：
    此处是**风险约束**而非因子，指数本身的 756 日 warmup 已保证有效信号出现时
    200 日均线必然有效，因此该分支只影响 warmup 期，不会污染有效信号。
    """
    ma_days = config.TREND_MA_DAYS if ma_days is None else ma_days
    factor = config.TREND_FILTER_FACTOR if factor is None else factor
    ma = close.rolling(ma_days, min_periods=ma_days).mean()
    below = close < ma
    out = pd.Series(np.where(below, factor, 1.0), index=close.index)
    out[ma.isna()] = 1.0
    return out


# ---------------------------------------------------------------- 核心仓（§6.2）
def zone_of(index_value):
    """档位索引 0-4。边界为**下闭区间**：20 属于档 1。"""
    for i, edge in enumerate(config.ZONE_EDGES):
        if index_value < edge:
            return i
    return len(config.ZONE_EDGES)


def market_core(index_value, trend, market):
    """核心仓 = 五档饱和度 × CORE_CAP × MARKET_CORE_RATIO × 趋势系数。

    指数无效时返回 None（warmup 期不产生信号）。
    """
    if _is_nan(index_value):
        return None
    ratio = config.MARKET_CORE_RATIO[market]
    saturation = config.ZONE_SATURATION[zone_of(index_value)]
    return config.CORE_CAP * ratio * saturation * trend


# ---------------------------------------------------------------- 分层上限（§6.3）
def layer_cap_position(core_position, market):
    """加密三层各自的上限（相对加密核心仓满仓值）。

    大盘返回空 dict（无分层概念）。
    """
    if market != "crypto":
        return {}
    return {layer: core_position * cap for layer, cap in config.CRYPTO_LAYER_CAP.items()}


# ---------------------------------------------------------------- 加密极贪分批（§6.5）
def greed_tier_factor(tier):
    """档位对应的核心仓系数。tier=0 → 1.0（未减仓）。"""
    if tier <= 0:
        return 1.0
    idx = min(tier, len(config.CRYPTO_GREED_REDUCE)) - 1
    return config.CRYPTO_GREED_REDUCE[idx]


def apply_greed_tiers(state, index_value):
    """加密极贪分批减仓（§6.5）。返回 (新状态, 说明)。

    - 指数 ≥ 各档触发线 → 逐档加深（每档只触发一次）
    - 指数 < CRYPTO_GREED_UNLOCK_INDEX → **逐档恢复**（一次只退一档）
    """
    if _is_nan(index_value):
        return state, ""

    state = _copy(state)
    n_tiers = len(config.CRYPTO_GREED_TIERS)

    target_tier = 0
    for i, trigger in enumerate(config.CRYPTO_GREED_TIERS):
        if index_value >= trigger:
            target_tier = i + 1

    if target_tier > state.greed_tier:
        state.greed_tier = min(target_tier, n_tiers)
        return state, "加密极贪减仓至第 %d 档（指数 %.1f）" % (state.greed_tier, index_value)

    if index_value < config.CRYPTO_GREED_UNLOCK_INDEX and state.greed_tier > 0:
        state.greed_tier -= 1
        return state, "加密极贪恢复一档（指数 %.1f，剩余 %d 档）" % (
            index_value, state.greed_tier)

    return state, ""


# ---------------------------------------------------------------- 大盘熔断（§6.5，沿用 v1）
def apply_circuit_breaker(state, index_value, date, prices):
    """大盘极贪熔断（v1 §8.1 逻辑，阈值改为相对该市场核心仓满仓值）。

    返回 (新状态, 熔断后的核心仓系数或 None, 说明)。
    系数 None 表示未熔断，沿用五档结果。
    """
    if _is_nan(index_value):
        return state, None, ""

    state = _copy(state)

    if not state.circuit_breaker and index_value >= config.EXTREME_GREED_TRIGGER:
        state.circuit_breaker = True
        state.cb_trigger_index = index_value
        state.cb_trigger_date = date
        state.cb_low_price = dict(prices or {})
        return state, config.EXTREME_GREED_FLOOR, "极贪熔断触发（指数 %.1f）" % index_value

    if not state.circuit_breaker:
        return state, None, ""

    for sym, px in (prices or {}).items():
        if px is None or (isinstance(px, float) and math.isnan(px)):
            continue
        low = state.cb_low_price.get(sym)
        if low is None or px < low:
            state.cb_low_price[sym] = px

    if index_value < config.EXTREME_GREED_UNLOCK_INDEX:
        state.circuit_breaker = False
        return state, None, "熔断解锁（指数回落至 %.1f）" % index_value

    if (state.cb_trigger_index is not None
            and state.cb_trigger_index - index_value >= config.EXTREME_GREED_UNLOCK_DROP):
        state.circuit_breaker = False
        return state, None, "熔断解锁（指数自峰值回落 %.1f 点）" % (
            state.cb_trigger_index - index_value)

    for sym, px in (prices or {}).items():
        low = state.cb_low_price.get(sym)
        if low and low > 0 and px / low - 1.0 >= config.EXTREME_GREED_UNLOCK_REBOUND:
            state.circuit_breaker = False
            return state, None, "熔断解锁（%s 自低点反弹 %.1f%%）" % (
                sym, (px / low - 1.0) * 100)

    return state, config.EXTREME_GREED_FLOOR, "熔断维持中"


# ---------------------------------------------------------------- 单市场总入口
def market_target(index_value, drawdown, trend, state, market, date=None, prices=None,
                  core=None, trigger_index=None):
    """计算单市场的核心仓与极端状态，返回 (MarketOutput, 新 MarketState)。

    `core`（可选）：**替换**五档结果 `market_core(index_value, trend, market)`。
    用于「清仓线变体」的离线回放（A1）—— 变体只换五档 core 的**来源**，
    熔断 / 极恐加仓的**触发源仍是 `index_value`（市场指数）**，`full` 基准也不变。

    `trigger_index`（可选）：**极端规则的触发源**（A2 的 keyed extremes）。
    给定且非 NaN 时，`apply_circuit_breaker` 的触发/解锁判定与 `extreme_fear`
    判定改用 `trigger_index`；**五档 core 的来源仍由 `core=` 决定**，
    `full = CORE_CAP × RATIO × trend` 也**不变**。
    为 `None`（默认）或 NaN 时 ⇒ 一律用 `index_value` ⇒ **逐位不变**。

    ⚠️ 生产上**只对 `us_equity` 传**（`run_portfolio` 如此）。但这是**调用方的
    自律**，不是函数层面的限制：函数层面该参数**不区分 `market`**，对
    `market="crypto"` 传入非 NaN 值同样会改用它——`extreme_fear` 与熔断
    （`apply_circuit_breaker`）都会真的按 `trigger_index` 判定，
    `extreme_fear` 的阈值也会随之换成 `CRYPTO_EXTREME_FEAR_TRIGGER`。
    只有 `apply_greed_tiers` / 五档 core 仍读 `index_value`。
    因此**不要对 `crypto` 传 `trigger_index`**（那会让「触发源」与「五档来源」
    两个注入点错位，产生非预期的熔断/极恐行为）。

    ⚠️ `core=None` 且 `trigger_index=None`（默认）时行为与改动前**逐位相同**
    （等价性红线：`tests/test_shoutu_variants.py`）。
    """
    state = _copy(state)
    note = ""
    extreme = False

    if core is None:
        core = market_core(index_value, trend, market)
    else:
        # 变体 core 的 NaN（warmup）与 `market_core` 的 None **同语义**
        core = None if _is_nan(core) else core
    if core is None:
        return (MarketOutput(market=market, core_position=None, drawdown=drawdown,
                             trend=trend, trend_blocked=(trend < 1.0),
                             extreme_fear=False, extreme=False, layer_caps={},
                             note="指数无效"),
                state)

    full = config.CORE_CAP * config.MARKET_CORE_RATIO[market] * trend

    # A2 keyed extremes：极端规则的触发源可与五档 core 的来源不同。
    # None / NaN ⇒ 用 index_value（NaN 不是有效信号，不得静默改变触发行为）。
    # ⚠️ 只在此处推导一次，供熔断与 `extreme_fear` **共用同一份规则**；
    # 未来改「NaN 如何回退」只需改这里，避免两者静默不一致。
    trig = index_value if (trigger_index is None or _is_nan(trigger_index)) \
        else trigger_index

    if market == "crypto":
        state, tier_note = apply_greed_tiers(state, index_value)
        if tier_note:
            note = tier_note
            extreme = True
        # 档位 > 0 时**替换**五档饱和度：设一个下限，避免五档在指数 >=80 时
        # 直接清仓（设计 §6.5 的初衷是「不一次性清仓，分批递减」）。
        # 档位 = 0 时沿用五档饱和度。
        if state.greed_tier > 0:
            core = full * greed_tier_factor(state.greed_tier)
    else:
        state, cb_floor, cb_note = apply_circuit_breaker(
            state, trig, date, prices or {})
        if cb_floor is not None:
            # **替换**而非取 min：熔断在指数 >=85 触发，而五档在 >=80 时已给
            # 饱和度 0（清仓）。若写成 min(core, ...)，熔断永远对着 0 取最小，
            # 「25% 底仓」成为死代码——而设计 §8.1 的原话是「减至 25% 底仓
            # （不清仓——避免完全踏空后续反弹）」，语义就是替换。
            # 比例基准是该市场核心仓满仓值（与加密极贪档位一致）。
            core = full * cb_floor
            note = cb_note
            extreme = True

    extreme_fear = (not _is_nan(trig)
                    and trig <= (config.CRYPTO_EXTREME_FEAR_TRIGGER
                                 if market == "crypto"
                                 else config.EXTREME_FEAR_TRIGGER))

    return (MarketOutput(
        market=market, core_position=core, drawdown=drawdown, trend=trend,
        trend_blocked=(trend < 1.0), extreme_fear=extreme_fear, extreme=extreme,
        layer_caps=layer_cap_position(core, market), note=note), state)
