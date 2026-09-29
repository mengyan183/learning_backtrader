# -*- coding: utf-8 -*-
"""信号层包（v2）。

对外暴露三组 API：

1. **v1 兼容 API**（来自 `legacy`，逐字保留）：`SignalState`、`zone_of`、
   `core_position`、`update_ammo`、`ammo_position`、`target_position`、
   `apply_extremes`、`apply_extreme_fear`、`throttle_ok`、`clip_adjustment`。
   这些名字**行为与 v1 完全一致**，不得修改。

2. **v2 单市场 API**（`market_signal`）：五档 + 趋势过滤 + 分层上限 + 极端规则。

3. **v2 组合级 API**（`portfolio`）：共享弹药池 + 统一资金池 + 防抖动收敛。

v2 的主流程用 2 + 3；1 仅为向后兼容与回归测试保留。
"""
from fg_system.signal import legacy, market_signal, portfolio
from fg_system.signal.legacy import (
    SignalState,
    ammo_position,
    apply_extreme_fear,
    apply_extremes,
    clip_adjustment,
    core_position,
    target_position,
    throttle_ok,
    update_ammo,
    zone_of,
)
from fg_system.signal.market_signal import (
    MarketOutput,
    MarketState,
    greed_tier_factor,
    layer_cap_position,
    market_core,
    market_target,
    trend_factor_series,
)
from fg_system.signal.portfolio import (
    PortfolioState,
    release_ammo,
)

__all__ = [
    # v1 兼容
    "SignalState", "zone_of", "core_position", "update_ammo", "ammo_position",
    "target_position", "apply_extremes", "apply_extreme_fear", "throttle_ok",
    "clip_adjustment",
    # v2 单市场
    "MarketState", "MarketOutput", "market_core", "market_target",
    "trend_factor_series", "layer_cap_position", "greed_tier_factor",
    # v2 组合级
    "PortfolioState", "release_ammo",
    # 子模块
    "legacy", "market_signal", "portfolio",
]
