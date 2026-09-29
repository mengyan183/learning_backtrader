# -*- coding: utf-8 -*-
"""F1 VIX 水位与变化率（先验权重 30%，§5.2）。

反转因子：VIX 高 = 恐惧 = 低分。
数据源：Data/raw/vix.csv（CBOE，1990 起）。
"""
from fg_system import config
from fg_system.factors.base import Factor, rolling_pct


class VixFactor(Factor):
    name = "vix"

    def raw(self, wide):
        vix = wide[("VIX", "close")]
        chg5 = vix.pct_change(5)
        level_pct = rolling_pct(vix, config.RANK_WINDOW)
        chg_pct = rolling_pct(chg5, config.RANK_WINDOW)
        composite = 0.7 * level_pct + 0.3 * chg_pct
        return 1.0 - composite          # 反转：VIX 高 → raw 低 → score 低
