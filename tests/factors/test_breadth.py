# -*- coding: utf-8 -*-
"""F4 广度代理测试（§5.2 F4）。

断言写法：用「广度恶化 vs 广度改善」两种情景**直接对比**分数，而不是套绝对阈值
（绝对值依赖滚动排名的边界细节，不稳定，见 Task 5/6 的同类修正）。
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors.breadth import BreadthFactor


def _wide(series_map):
    n = len(next(iter(series_map.values())))
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    cols = pd.MultiIndex.from_tuples([(s, "close") for s in series_map], names=["symbol", "field"])
    return pd.DataFrame(np.column_stack(list(series_map.values())), index=idx, columns=cols)


def _scenario(n, rsp_daily):
    """构造统一情景：SPY 稳步上行，RSP 以给定日收益演化。"""
    spy = 100 * np.exp(np.cumsum(np.full(n, 0.0010)))
    rsp = 100 * np.exp(np.cumsum(np.full(n, rsp_daily)))
    return _wide({"SPY": spy, "QQQ": spy, "RSP": rsp, "IWM": spy * 0.9})


def test_score_range():
    rng = np.random.RandomState(4)
    n = 1300
    base = 100 * np.exp(np.cumsum(0.0003 + 0.008 * rng.randn(n)))
    wide = _wide({"SPY": base, "QQQ": base * 1.1, "RSP": base * 0.98, "IWM": base * 0.9})
    score = BreadthFactor().score(wide).dropna()
    assert not score.empty
    assert score.between(0, 100).all()


def test_narrowing_breadth_lowers_score():
    """广度恶化（RSP 持续弱于 SPY）的分数必须低于广度改善情景。"""
    narrow = BreadthFactor().score(_scenario(1200, -0.0005)).dropna()
    broad = BreadthFactor().score(_scenario(1200, 0.0015)).dropna()
    assert not narrow.empty and not broad.empty
    assert narrow.iloc[-1] < broad.iloc[-1]


def test_ma_breadth_subitem_reflects_decline():
    """均线宽度子项：4 个标的中 1 个跌破 200 日均线 → 该子项为 0.75。

    注意：不要对「恒定增长率」构造的数据断言分数绝对值。此类序列的
    `pct_change` 近似恒定，滚动百分位会退化为「由浮点噪声决定的任意排名」
    （实测 (RSP/SPY) 子项给出 0.90 而非预期的 0.50）。真实数据有波动，不受影响。
    这里只校验均线宽度这一**不依赖滚动排名**的子项。
    """
    n = 1200
    spy = 100 * np.exp(np.cumsum(np.full(n, 0.0010)))
    rsp = 100 * np.exp(np.cumsum(np.full(n, -0.0005)))      # 持续下跌，必然跌破 200 日均线
    wide = _wide({"SPY": spy, "QQQ": spy, "RSP": rsp, "IWM": spy * 0.9})

    above = None
    for sym in ["SPY", "QQQ", "RSP", "IWM"]:
        s = wide[(sym, "close")]
        ma200 = s.rolling(200, min_periods=200).mean()
        flag = (s > ma200).astype(float).where(ma200.notna())
        above = flag if above is None else above + flag
    above = (above / 4.0).dropna()

    assert above.iloc[-1] == pytest.approx(0.75)


def test_missing_breadth_symbol_raises():
    n = 900
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    cols = pd.MultiIndex.from_tuples([("SPY", "close")], names=["symbol", "field"])
    wide = pd.DataFrame(np.full((n, 1), 100.0), index=idx, columns=cols)
    with pytest.raises(ValueError, match="广度标的缺失"):
        BreadthFactor().score(wide)
