# -*- coding: utf-8 -*-
"""v1 单市场信号层的**逐字副本**，仅为向后兼容保留。

**不要修改本文件。** v1 的行为已被 tests/test_signal.py 的断言锁定，
任何改动都必须走 docs/trading-discipline.md 第 8 条流程。

v2 的新逻辑在 fg_system/signal/market_signal.py（单市场）与
fg_system/signal/portfolio.py（组合级）。本模块保留的原因是：
重构已验收的代码是纯风险——v2 的拆分不应该让 v1 的行为产生任何不确定性。

硬性约定（§3.4）：纯函数 + 显式状态。禁止读写全局变量或文件。

--------------------------------------------------------------------
**退役条件**（R-5，WT-12 审查：死代码/兼容层不得永久堆积）：

本模块**只允许**被两处引用 —— `fg_system/signal/__init__.py`（向后兼容
重导出）与 `tests/**`（v1 行为回归）。`tests/signal/test_compat.py`
以测试锁住这条约束：一旦**生产代码**直接 import 本模块，测试立刻失败。

满足下列**全部**条件即可整体删除本文件（同时从 `signal/__init__.py`
的导入里摘掉，并在 `docs/trading-discipline.md` 记录删除决策）：

1. 全仓搜索「signal.legacy / from .legacy / import legacy」只剩 tests；
2. v1 的调用方（历史脚本 / 外部笔记本）确认已全部迁移到 v2
   （`market_signal` + `portfolio`）或已废弃；
3. `tests/signal/test_compat.py` 与 `tests/test_signal.py` 中对 v1 的
   断言一并删除（届时 v1 不再有任何消费者）。
--------------------------------------------------------------------
"""
__deprecated__ = True   # 兼容层标记：新代码**不得**依赖（R-5）
import math
from dataclasses import dataclass, field

import pandas as pd

from fg_system import config


@dataclass
class SignalState:
    """信号状态机。所有字段均可 JSON 序列化，用于 state.json 持久化。"""

    ammo_released: list = field(default_factory=list)     # 已释放批次索引 [0,1,2]
    last_rebalance_date: str = None                       # ISO 日期字符串
    circuit_breaker: bool = False
    cb_trigger_index: float = None                        # 熔断时的指数峰值
    cb_trigger_date: str = None
    cb_low_price: dict = field(default_factory=dict)      # symbol -> 熔断后最低价
    last_extreme_fear_date: str = None

    def to_dict(self):
        return {
            "ammo_released": sorted(self.ammo_released),
            "last_rebalance_date": self.last_rebalance_date,
            "circuit_breaker": self.circuit_breaker,
            "cb_trigger_index": self.cb_trigger_index,
            "cb_trigger_date": self.cb_trigger_date,
            "cb_low_price": dict(self.cb_low_price),
            "last_extreme_fear_date": self.last_extreme_fear_date,
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        return cls(
            ammo_released=list(data.get("ammo_released") or []),
            last_rebalance_date=data.get("last_rebalance_date"),
            circuit_breaker=bool(data.get("circuit_breaker", False)),
            cb_trigger_index=data.get("cb_trigger_index"),
            cb_trigger_date=data.get("cb_trigger_date"),
            cb_low_price=dict(data.get("cb_low_price") or {}),
            last_extreme_fear_date=data.get("last_extreme_fear_date"),
        )


def _is_nan(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


def _copy(state):
    """返回状态的**独立副本**（含 list/dict 深拷贝）。

    §3.4 硬约定：本层必须是纯函数，禁止修改入参。所有状态变更函数都必须先调用本函数，
    否则调用方传入 state 副本（并行回测、多组合对比）时会静默丢失状态。
    """
    return SignalState.from_dict(state.to_dict())


# ---------------------------------------------------------------- 核心仓（§7.2）
def zone_of(fg_index):
    """返回档位索引 0-4。边界为**下闭区间**：20 属于档 1。"""
    for i, edge in enumerate(config.ZONE_EDGES):
        if fg_index < edge:
            return i
    return len(config.ZONE_EDGES)


def core_position(fg_index):
    """核心仓仓位 = 饱和度 × CORE_CAP。指数无效时返回 None。"""
    if _is_nan(fg_index):
        return None
    return config.CORE_CAP * config.ZONE_SATURATION[zone_of(fg_index)]


# ---------------------------------------------------------------- 弹药池（§7.3）
def update_ammo(state, drawdown):
    """按**标的指数**回撤释放弹药。每批只释放一次。

    返回 (新状态, 弹药仓位, 本次新释放的批次列表)。
    """
    if _is_nan(drawdown):
        return state, ammo_position(state), []

    state = _copy(state)
    newly = []
    for i, trigger in enumerate(config.DRAWDOWN_BATCHES):
        if drawdown >= trigger and i not in state.ammo_released:
            state.ammo_released.append(i)
            newly.append(i)
    return state, ammo_position(state), newly


def ammo_position(state):
    return config.AMMO_PER_BATCH * len(state.ammo_released)


def target_position(fg_index, state):
    """目标总仓位 = 核心仓 + 弹药仓（§7.4）。指数无效时返回 None。"""
    core = core_position(fg_index)
    if core is None:
        return None
    return core + ammo_position(state)


# ---------------------------------------------------------------- 极端规则（§8）
def apply_extremes(state, fg_index, date, prices, target):
    """应用极贪熔断，返回 (新状态, 修正后的目标仓位, 说明)。

    优先级：极贪熔断 > 极恐加仓 > 五档映射（§8.3）。
    prices: {symbol: 当日收盘价}，用于熔断的标的级反弹判断。

    熔断解锁（§8.1，满足任一）：
      ① 指数 < EXTREME_GREED_UNLOCK_INDEX
      ② 某标的自熔断后低点反弹 >= EXTREME_GREED_UNLOCK_REBOUND（标的级独立解锁）
      ③ 指数自熔断峰值回落 >= EXTREME_GREED_UNLOCK_DROP
    """
    if _is_nan(fg_index):
        return state, target, "指数无效"

    state = _copy(state)

    # --- 触发
    if not state.circuit_breaker and fg_index >= config.EXTREME_GREED_TRIGGER:
        state.circuit_breaker = True
        state.cb_trigger_index = fg_index
        state.cb_trigger_date = date
        state.cb_low_price = dict(prices or {})
        return state, config.EXTREME_GREED_FLOOR, "极贪熔断触发（指数 %.1f）" % fg_index

    if not state.circuit_breaker:
        return state, target, ""

    # --- 熔断中：先更新低点
    for sym, px in (prices or {}).items():
        if px is None or (isinstance(px, float) and math.isnan(px)):
            continue
        low = state.cb_low_price.get(sym)
        if low is None or px < low:
            state.cb_low_price[sym] = px

    # --- 解锁条件 ①
    if fg_index < config.EXTREME_GREED_UNLOCK_INDEX:
        state.circuit_breaker = False
        return state, target, "熔断解锁（指数回落至 %.1f）" % fg_index

    # --- 解锁条件 ③
    if (state.cb_trigger_index is not None
            and state.cb_trigger_index - fg_index >= config.EXTREME_GREED_UNLOCK_DROP):
        state.circuit_breaker = False
        return state, target, "熔断解锁（指数自峰值回落 %.1f 点）" % (
            state.cb_trigger_index - fg_index)

    # --- 解锁条件 ②（标的级）
    for sym, px in (prices or {}).items():
        low = state.cb_low_price.get(sym)
        if low and low > 0 and px / low - 1.0 >= config.EXTREME_GREED_UNLOCK_REBOUND:
            state.circuit_breaker = False
            return state, target, "熔断解锁（%s 自低点反弹 %.1f%%）" % (
                sym, (px / low - 1.0) * 100)

    return state, config.EXTREME_GREED_FLOOR, "熔断维持中"


def apply_extreme_fear(state, fg_index, date):
    """极恐提前释放弹药（§8.2）。返回 (新状态, 本次释放批数, 说明)。

    每次极恐事件最多提前释放 1 批；两次事件间隔需 >= EXTREME_FEAR_COOLDOWN_DAYS
    （自然日；设计口径为 60 个交易日，见 config 注释）。
    """
    if _is_nan(fg_index) or fg_index > config.EXTREME_FEAR_TRIGGER:
        return state, 0, ""
    if len(state.ammo_released) >= len(config.DRAWDOWN_BATCHES):
        return state, 0, ""

    if state.last_extreme_fear_date:
        gap = (pd.Timestamp(date) - pd.Timestamp(state.last_extreme_fear_date)).days
        if gap < config.EXTREME_FEAR_COOLDOWN_DAYS:
            return state, 0, ""

    state = _copy(state)
    nxt = next(i for i in range(len(config.DRAWDOWN_BATCHES)) if i not in state.ammo_released)
    state.ammo_released.append(nxt)
    state.last_extreme_fear_date = date
    return state, 1, "极恐提前释放第 %d 批弹药（指数 %.1f）" % (nxt + 1, fg_index)


# ---------------------------------------------------------------- 防抖动（§9）
def throttle_ok(state, current, target, date, extreme=False):
    """调仓阈值 / 冷却 / 单次上限三条约束（§9）。极端规则触发时全部豁免。"""
    if extreme:
        return True, "极端规则豁免"
    if current is None or target is None:
        return False, "仓位无效"
    if abs(target - current) < config.REBALANCE_THRESHOLD:
        return False, "未达调仓阈值 %.0fpp（偏离 %.1fpp）" % (
            config.REBALANCE_THRESHOLD * 100, abs(target - current) * 100)
    if state.last_rebalance_date:
        gap = (pd.Timestamp(date) - pd.Timestamp(state.last_rebalance_date)).days
        if gap < config.REBALANCE_COOLDOWN:
            return False, "处于调仓冷却期（距上次 %d 天 < %d 天）" % (
                gap, config.REBALANCE_COOLDOWN)
    return True, "可操作"


def clip_adjustment(current, target):
    """单次调仓幅度上限（§9）。返回调整后的目标仓位。"""
    delta = target - current
    if abs(delta) <= config.MAX_SINGLE_ADJUST:
        return target
    return current + math.copysign(config.MAX_SINGLE_ADJUST, delta)
