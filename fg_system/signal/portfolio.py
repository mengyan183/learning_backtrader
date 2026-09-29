# -*- coding: utf-8 -*-
"""组合级信号层：共享弹药池 + 统一资金池（§6.4、§6.7、§7）。

硬性约定（§3.4）：纯函数 + 显式状态。

为什么弹药池是组合级而非市场级：加密三层高度相关，BTC 崩盘时 BITX/MSTX/CONL
会在**同一天**触发加仓。若各自备弹药，会在同一天同时打光并实际超配；
共享池把「谁先用」变成显式规则，而不是隐性超配。
"""
import math
from dataclasses import dataclass, field

import pandas as pd

from fg_system import config

# 平局时的市场优先级（§6.4）：大盘标的流动性优于加密 ETF，且大盘崩盘往往
# 伴随系统性风险，先补大盘更符合风险管理直觉。
TIE_BREAK_ORDER = ["us_equity", "crypto"]


@dataclass
class PortfolioState:
    """组合级状态机。所有字段可 JSON 序列化。"""

    ammo_released: list = field(default_factory=list)          # 共享池已用槽位
    market_batches: dict = field(default_factory=dict)         # market -> 已触发档位数
    last_rebalance_date: str = None
    last_extreme_fear_date: str = None

    def to_dict(self):
        return {
            "ammo_released": sorted(self.ammo_released),
            "market_batches": dict(self.market_batches),
            "last_rebalance_date": self.last_rebalance_date,
            "last_extreme_fear_date": self.last_extreme_fear_date,
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        return cls(
            ammo_released=list(data.get("ammo_released") or []),
            market_batches=dict(data.get("market_batches") or {}),
            last_rebalance_date=data.get("last_rebalance_date"),
            last_extreme_fear_date=data.get("last_extreme_fear_date"),
        )


def _copy(state):
    """返回独立副本（§3.4 硬约定：不得修改入参）。"""
    return PortfolioState.from_dict(state.to_dict())


def batches_for(market):
    """该市场的弹药触发档位。"""
    if market == "crypto":
        return config.CRYPTO_DRAWDOWN_BATCHES
    return config.DRAWDOWN_BATCHES


def pending_threshold(state, market):
    """该市场**当前待释放批次**的阈值。已全部触发时返回 None。

    口径说明（§6.4 消歧）：分母是当前待释放的那一批，不是全部三档。
    """
    batches = batches_for(market)
    done = int(state.market_batches.get(market, 0))
    if done >= len(batches):
        return None
    return batches[done]


def ammo_priority(state, output):
    """优先级 = 当前回撤 / 当前待释放批次的阈值。未触发返回 None。

    用比值而非绝对值：加密天然跌得多，用绝对值会让加密永远优先。
    """
    if output.drawdown is None or (isinstance(output.drawdown, float)
                                   and math.isnan(output.drawdown)):
        return None
    threshold = pending_threshold(state, output.market)
    if threshold is None or output.drawdown < threshold:
        return None
    return output.drawdown / threshold


def market_batch_cap(n_markets=None, n_batches=None):
    """单市场可拿的**最大批次**（第 12.11 条）。

    共享池必须为**其他每个市场**至少保留 1 批，因此：

        单市场上限 = 批数 − (市场数 − 1)

    当前 3 批 / 2 个市场 ⇒ **上限 2 批**。

    **为什么需要它**：实测（第 12.8.1 条）**加密把 3 批全部拿走、大盘拿到 0 批**，
    使「共享弹药池」名存实亡、**大盘的「跌了加仓」机制从未生效**。
    加密档位虽按比例加宽（-30/-50/-70），但加密崩得更深 ⇒ 比值更大 ⇒
    加宽**没有**达到「防止加密抽干池子」的设计目的。本上限是**结构性保证**，
    不引入任何可调参数。
    """
    n_markets = len(config.MARKETS) if n_markets is None else n_markets
    n_batches = (len(config.DRAWDOWN_BATCHES) if n_batches is None
                 else n_batches)
    return max(1, n_batches - (n_markets - 1))


def release_ammo(state, outputs):
    """裁决共享弹药池释放。返回 (新状态, 本次释放批数, 说明)。

    规则：
      - 单日最多释放 1 批（避免一天打光）
      - 池子共 3 个槽位，先到先得
      - **单市场最多 `market_batch_cap()` 批**（为其他市场保留至少 1 批）
      - 同日多市场触发时按优先级比值排序，平局按 TIE_BREAK_ORDER
    """
    state = _copy(state)
    if len(state.ammo_released) >= len(config.DRAWDOWN_BATCHES):
        return state, 0, ""

    # 上限由**系统配置** `config.MARKETS` 决定，而不是「本次调用传了几个市场」——
    # 后者会让上限隐含依赖调用方式，难以推理。单市场系统（如 v1 兼容测试）
    # 应把 `config.MARKETS` monkeypatch 成单元素。
    cap = market_batch_cap()
    candidates = []
    for out in outputs:
        # 已达份额上限 ⇒ 跳过，把批次留给其他市场（保留的选择权不算浪费：
        # 它仍可用于**将来**任一方更深的回撤）。
        if int(state.market_batches.get(out.market, 0)) >= cap:
            continue
        p = ammo_priority(state, out)
        if p is None:
            continue
        tie = TIE_BREAK_ORDER.index(out.market) if out.market in TIE_BREAK_ORDER else 99
        candidates.append((p, -tie, out))

    if not candidates:
        return state, 0, ""

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, _, winner = candidates[0]

    slot = max(state.ammo_released) + 1 if state.ammo_released else 0
    state.ammo_released.append(slot)
    state.market_batches[winner.market] = int(
        state.market_batches.get(winner.market, 0)) + 1
    return state, 1, "弹药释放（%s 回撤 %.1f%%）" % (
        winner.market, winner.drawdown * 100)


def apply_extreme_fear(state, outputs, date):
    """极恐提前释放弹药（v1 §8.2 语义）。返回 (新状态, 释放批数, 说明)。"""
    state = _copy(state)
    if len(state.ammo_released) >= len(config.DRAWDOWN_BATCHES):
        return state, 0, ""

    hit = next((o for o in outputs if o.extreme_fear), None)
    if hit is None:
        return state, 0, ""

    # 同样受份额上限约束（第 12.11 条）：极恐路径不得绕过「为其他市场保留批次」。
    if int(state.market_batches.get(hit.market, 0)) >= market_batch_cap():
        return state, 0, ""

    if state.last_extreme_fear_date:
        gap = (pd.Timestamp(date) - pd.Timestamp(state.last_extreme_fear_date)).days
        if gap < config.EXTREME_FEAR_COOLDOWN_DAYS:
            return state, 0, ""

    slot = max(state.ammo_released) + 1 if state.ammo_released else 0
    state.ammo_released.append(slot)
    state.market_batches[hit.market] = int(state.market_batches.get(hit.market, 0)) + 1
    state.last_extreme_fear_date = date
    return state, 1, "极恐提前释放弹药（%s）" % hit.market


def ammo_position(state):
    """弹药仓仓位 = 每批比例 × 已释放批数。"""
    return config.AMMO_PER_BATCH * len(state.ammo_released)


def combine(outputs, state):
    """组合目标仓位 = Σ各市场核心仓 + 弹药仓（§7.2）。

    某市场核心仓为 None（warmup）时跳过该市场；全部为 None 时返回 None
    （写盘为 NaN，回测自然跳过——不能写 0.0，那会被当成"主动空仓"）。
    """
    cores = [o.core_position for o in outputs if o.core_position is not None]
    if not cores:
        return None, "全部市场无有效信号"
    target = sum(cores) + ammo_position(state)
    return min(max(target, 0.0), 1.0), ""


# ---------------------------------------------------------------- 防抖动（§6.7）
# v2 把 clamp 统一收敛到本层，解决 v1 遗留问题 6（strategy.py 与 signal.throttle_ok
# 两处重复实现）。
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


def next_position(current, target):
    """`FgStrategy.next()` 的**纯函数版**：目标仓位 → 本次调仓后的实际仓位。

    **这是唯一实现** —— `FgStrategy.next()` 也调它。分析与回测共用同一段逻辑，
    否则"分析里的规则 ≠ 回测里的规则"，测出来的代价不是真规则的代价。

    ⚠️ 阈值判断是 `<` 不是 `≤`：`|target - current|` **恰好等于**
    `REBALANCE_THRESHOLD` 时**要动作**（与 `FgStrategy` 原实现逐字一致）。

    ⚠️ `target` 为 NaN（warmup / 无信号）时**保持不动** —— 不得当成"空仓"，
    那会被回测误读为"策略主动空仓"，污染净值（同 `pipeline` 的约定）。
    """
    if target != target:                       # NaN
        return current
    if abs(target - current) < config.REBALANCE_THRESHOLD:
        return current
    return max(0.0, min(1.0, clip_adjustment(current, target)))
