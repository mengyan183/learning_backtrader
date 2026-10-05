# -*- coding: utf-8 -*-
"""美联储政策因子（FED）。

把「政策方向 + 目标利率水平」映射为 0-100 情绪子分：
- 方向分 dir：加息周期 25 / 按兵不动 50 / 降息周期 75（收紧压情绪、宽松抬情绪）
- 水平分 level：以 2% 为中性锚，利率每高 1pct 压 15 分（与直觉一致的高利率压制）
- fed_score = 0.6 × dir + 0.4 × level

数据 = config.FED_POLICY_PERIODS（官方事件驱动的离散状态，人工随决议更新）；
2026-01-01 之前与未来返回 NaN（历史无政策数据 → combine 自动按剩余权重归一化，
指数历史口径仅微变；避免前瞻）。

权重见 config.WEIGHTS（fed 0.20，2026 前缺因子自动重归一）。
"""
import datetime as dt

import numpy as np
import pandas as pd

from fg_system import config
from fg_system.factors.base import Factor


class FedPolicyFactor(Factor):
    name = "fed"

    def __init__(self, periods=None):
        # periods: list[(生效日, stance, rate_high)]，按日期升序
        self.periods = periods if periods is not None else config.FED_POLICY_PERIODS

    def _score_for(self, d):
        """单日政策分数；无政策数据返回 NaN。"""
        s = None
        for start, stance, rate_high in self.periods:
            if d >= dt.date.fromisoformat(start):
                s = (start, stance, rate_high)
        if s is None:
            return np.nan
        _, stance, rate_high = s
        dir_map = {"加息周期": 25.0, "按兵不动": 50.0, "降息周期": 75.0}
        d0 = dir_map.get(stance, 50.0)
        lv = float(np.clip(50.0 - (rate_high - 2.0) * 15.0, 0.0, 100.0))
        return 0.6 * d0 + 0.4 * lv

    def raw(self, wide):
        # 抽象接口占位：本因子直接给出 0-100 分数（score 覆写优先，raw 不被调用）
        return self.score(wide) / 100.0

    def score(self, wide):
        """按 wide 索引（日期）逐日计算。只填充 ≤ 今天的日期，未来为 NaN。"""
        idx = pd.to_datetime(wide.index)
        today = dt.date.today()
        vals = []
        for ts in idx:
            d = ts.date()
            vals.append(self._score_for(d) if d <= today else np.nan)
        return pd.Series(vals, index=wide.index, name=self.name)
