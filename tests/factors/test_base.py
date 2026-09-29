# -*- coding: utf-8 -*-
"""因子基类工具测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors import base


def test_rolling_pct_returns_uniform_between_0_and_1():
    s = pd.Series(np.arange(100, dtype=float))
    out = base.rolling_pct(s, 20)
    assert out.dropna().between(0, 1).all()
    assert out.iloc[:19].isna().all()      # 窗口不足返回 NaN
    assert out.iloc[-1] == pytest.approx(1.0)


def test_rolling_pct_min_periods_enforced():
    s = pd.Series(np.arange(50, dtype=float))
    out = base.rolling_pct(s, 20)
    assert out.notna().sum() == 50 - 20 + 1


def test_pct_score_reverse_direction():
    """反转方向：同一位置 normal 与 reverse 之和恒为 100。

    注意：不能用「原始值上升 → 分数上升」来断言。对单调递增序列，滚动百分位
    在每个窗口的末尾元素恒为最大值，normal 与 reverse 在所有位置分别恒为
    100 与 0，原写法 `normal.iloc[-1] > normal.iloc[-20]` 必然失败。
    """
    s = pd.Series(np.arange(100, dtype=float))
    normal = base.pct_score(s, 20, reverse=False)
    reverse = base.pct_score(s, 20, reverse=True)
    valid = normal.dropna().index.intersection(reverse.dropna().index)
    assert len(valid) > 0
    assert (normal.loc[valid] + reverse.loc[valid] - 100.0).abs().max() < 1e-9


def test_factor_is_abstract():
    with pytest.raises(TypeError):
        base.Factor()
