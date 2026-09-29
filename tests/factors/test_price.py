# -*- coding: utf-8 -*-
"""F3 价格因子测试（§5.2 F3）。输入必须是 QQQ 等无杠杆标的。

断言写法：用「持续上涨 vs 深度回撤」两类明确行情比较分数，避免依赖滚动排名的
边界细节（见 Task 5/6 的同类修正）。
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors.price import PriceFactor


def _wide(close):
    idx = pd.date_range("2020-01-01", periods=len(close), freq="B")
    cols = pd.MultiIndex.from_tuples([("QQQ", "close")], names=["symbol", "field"])
    return pd.DataFrame(np.array(close, dtype=float).reshape(-1, 1), index=idx, columns=cols)


def test_score_range():
    rng = np.random.RandomState(3)
    close = 300 * np.exp(np.cumsum(0.0004 + 0.01 * rng.randn(1300)))
    score = PriceFactor().score(_wide(close)).dropna()
    assert not score.empty
    assert score.between(0, 100).all()


def test_deep_drawdown_lowers_score():
    """深度回撤（高波动 + 负动量 + 深回撤）应给出低分（恐惧）。"""
    up = 300 * np.exp(np.cumsum(np.full(900, 0.0008)))
    crash = up[-1] * np.exp(np.cumsum(np.full(300, -0.004)))
    score = PriceFactor().score(_wide(np.concatenate([up, crash]))).dropna()
    assert not score.empty
    assert score.iloc[-1] < 30


def test_strong_uptrend_raises_score():
    """持续上涨（无回撤、极低波动）应给出高分。"""
    up = 300 * np.exp(np.cumsum(np.full(1200, 0.0012)))
    score = PriceFactor().score(_wide(up)).dropna()
    assert not score.empty
    assert score.iloc[-1] > 60


def test_uptrend_scores_above_drawdown():
    """同一测试内直接对比：上涨行情末尾分数 > 崩跌行情末尾分数。"""
    up = 300 * np.exp(np.cumsum(np.full(1200, 0.0012)))
    up_score = PriceFactor().score(_wide(up)).dropna().iloc[-1]

    base = 300 * np.exp(np.cumsum(np.full(900, 0.0008)))
    crash = base[-1] * np.exp(np.cumsum(np.full(300, -0.004)))
    crash_score = PriceFactor().score(_wide(np.concatenate([base, crash]))).dropna().iloc[-1]

    assert up_score > crash_score


def test_requires_underlying_not_leveraged():
    """传入 TQQQ 列应报错——强制使用无杠杆标的（§4.5 约束 1）。"""
    idx = pd.date_range("2020-01-01", periods=900, freq="B")
    cols = pd.MultiIndex.from_tuples([("TQQQ", "close")], names=["symbol", "field"])
    wide = pd.DataFrame(np.full((900, 1), 50.0), index=idx, columns=cols)
    with pytest.raises(ValueError, match="无杠杆标的"):
        PriceFactor().score(wide)
