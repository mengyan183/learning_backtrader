# -*- coding: utf-8 -*-
"""因子抽象基类与滚动分位归一化工具（§5.1、§5.3）。

硬约束（§4.5 约束 1）：因子输入必须是**无杠杆标的**（QQQ/SOXX/SPY/VIX 等），
禁止使用 TQQQ/SOXL/UPRO 自身价格——杠杆 ETF 含年化 12%~38% 的波动率拖累，
会把损耗系统性误读为恐惧。
"""
from abc import ABC, abstractmethod

import pandas as pd

from fg_system import config


def rolling_pct(series, window=None, min_periods=None):
    """滚动百分位，返回 [0, 1]。窗口不足处为 NaN（禁止用不足窗口的数据凑值）。

    实现说明：使用「窗口内 <= 当前值的比例」，与 pandas 的 `rolling().rank(pct=True)`
    在无重复值时**数学等价**（二者都等于「当前值在窗口内的升序位置 / 窗口长度」）。
    差异只出现在窗口内存在重复值时：本实现统计「≤ 当前值」的个数，
    而 `rank(pct=True)` 使用平均排名。

    注意（避免误解）：**单调序列上两种实现都恒返回 1.0**——因为每个窗口的右端点
    必然是窗口内最大值。这是滚动百分位的数学必然，不是实现缺陷；趋势段的因子
    区分度由「动量/回撤/波动率」等多子项共同提供，而非依赖单点百分位的取值变化。
    """
    window = window or config.RANK_WINDOW
    min_periods = window if min_periods is None else min_periods
    return series.rolling(window, min_periods=min_periods).apply(
        lambda x: (x <= x[-1]).mean(), raw=True
    )


def pct_score(series, window=None, reverse=False):
    """滚动百分位映射为 0-100 分数。reverse=True 时高分代表低原始值。"""
    pct = rolling_pct(series, window)
    return 100.0 * (1.0 - pct) if reverse else 100.0 * pct


class Factor(ABC):
    """单一因子 → 0-100 情绪分（高分 = 贪婪）。纯函数，无副作用。"""

    name = ""

    @abstractmethod
    def raw(self, wide):
        """原始合成值（通常为 [0,1] 的百分位加权平均，高分 = 贪婪）。"""

    def score(self, wide):
        """0-100 情绪分。默认把 raw（[0,1]）线性映射到 [0,100]。"""
        raw = self.raw(wide)
        return 100.0 * raw
