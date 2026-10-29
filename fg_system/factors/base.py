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


def orthogonalize(y, x, window=None, min_periods=None):
    """把 `y` 对 `x` 做**滚动回归取残差** ✓（剔除 `x` 解释掉的那部分）。

    动机（2026-10-29 用户裁定）：C1_BAA10Y 与 `fed` 的 Spearman 相关 **+0.604**
    偏高 ✗ —— 与美联储因子中度重复，直接进回测裁判可能得出「无增量贡献」✗。
    先做正交化，再看 ICIR 是否仍然站得住 ✓。

    🔴 **无前视** ✗：β 用 `shift(1)` 取 **t-1 及之前**的窗口 ✗ ——
    若用含 t 的窗口，当天的 y 自己参与估参 ⇒ 残差被系统性压小 ⇒ IC 虚高 ✗
    （这正是本仓库最怕的那类错误 ✓）。

    :param y: 待正交化的序列（如因子分位）
    :param x: 解释变量（如 `fed` 因子），按 `y.index` 对齐
    :param window: 滚动窗口，默认 `config.RANK_WINDOW` ✓（不新设窗口 ✗）
    :returns: 残差 Series（index 同 `y`，窗口不足处 NaN ✓）
    """
    window = window or config.RANK_WINDOW
    min_periods = max(20, window // 4) if min_periods is None else min_periods
    yy = pd.Series(y, dtype="float64")
    xx = pd.Series(x, dtype="float64").reindex(yy.index)
    df = pd.concat([yy.rename("y"), xx.rename("x")], axis=1).dropna()
    if df.empty:
        return pd.Series(float("nan"), index=yy.index, name="resid")
    var = df["x"].rolling(window, min_periods=min_periods).var()
    cov = df["y"].rolling(window, min_periods=min_periods).cov(df["x"])
    # 🔴 shift(1)：β 只用 t-1 及之前的信息（无前视 ✓）
    beta = (cov / var.replace(0.0, float("nan"))).shift(1)
    resid = df["y"] - beta * df["x"]
    return resid.rename("resid").reindex(yy.index)


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
