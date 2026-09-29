# -*- coding: utf-8 -*-
"""CF1 加密贪恐因子（先验权重 50%，§5.2）。

输入：alternative.me 的 0-100 贪恐值（高分 = 贪婪，**方向与自建指数一致，不反转**）。

为什么要再做滚动百分位：alternative.me 是**绝对刻度**，而加密市场的情绪中枢
在漂移——2018 年的「贪恐 30」与 2024 年的「贪恐 30」不是同一件事。滚动百分位
把它转为「相对当下环境的情绪位置」，这是跨 10 年回测成立的前提（v1 §5.3）。
"""
from fg_system.factors.base import Factor, rolling_pct

FNG_COLUMN = ("FNG", "value")


class CryptoFngFactor(Factor):
    name = "crypto_fng"
    market = "crypto"

    def raw(self, wide):
        if FNG_COLUMN not in wide.columns:
            raise ValueError(
                "CF1 需要 %s 列（alternative.me 贪恐指数），当前列: %s"
                % (FNG_COLUMN, list(wide.columns)))
        return rolling_pct(wide[FNG_COLUMN])
