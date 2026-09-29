# -*- coding: utf-8 -*-
"""F2 波动率期限结构 VIX/VIX3M（先验权重 20%，§5.2）。

比值 > 1 表示短期恐慌高于中期（期限结构倒挂），是市场承压信号。
反转因子：比值高 = 恐惧 = 低分。

原设计为 CBOE 权益 Put/Call 比率，因官方 CSV 停更于 2019-10-04 而改用本因子。
已知代价：与 F1 同属波动率族，存在共线性（§17 风险 3），实现时须做相关性检查。
"""
from fg_system import config
from fg_system.factors.base import Factor, rolling_pct


class TermStructureFactor(Factor):
    name = "term"

    def raw(self, wide):
        vix = wide[("VIX", "close")]
        vix3m = wide[("VIX3M", "close")]
        ratio = (vix / vix3m).rolling(5).mean()      # 5 日均值消噪
        pct = rolling_pct(ratio, config.RANK_WINDOW)
        return 1.0 - pct                             # 反转：倒挂 → 低分
