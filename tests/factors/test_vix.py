# -*- coding: utf-8 -*-
"""F1 VIX 因子测试（§5.2 F1）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors.vix import VixFactor


def _wide(vix_values):
    idx = pd.date_range("2020-01-01", periods=len(vix_values), freq="B")
    cols = pd.MultiIndex.from_tuples([("VIX", "close")], names=["symbol", "field"])
    return pd.DataFrame(np.array(vix_values, dtype=float).reshape(-1, 1), index=idx, columns=cols)


def test_score_range_is_0_to_100():
    vix = 15 + 5 * np.sin(np.arange(1200) / 30.0)
    score = VixFactor().score(_wide(vix))
    valid = score.dropna()
    assert not valid.empty
    assert valid.between(0, 100).all()


def test_reverse_direction_vix_high_lowers_score():
    """VIX 水平高 → 分数低（§14.1 反转方向正确）。

    注意：不要用「线性 ramp 下末尾分数低于 30 天前」来断言——该写法依赖滚动
    排名的边界细节，不稳定（实测会得到相反结果）。改用相关性 + 分段均值。
    """
    rng = np.random.RandomState(0)
    # 低段取 1200 天，保证 warmup(756) 之后仍留有充足低 VIX 样本
    low = 12 + 0.5 * rng.randn(1200)
    high = 60 + 0.5 * rng.randn(400)
    vix = np.concatenate([low, high])
    score = VixFactor().score(_wide(vix))
    valid = score.dropna()
    assert len(valid) > 500
    aligned = vix[score.notna()]

    # 有效区间内 score 与 VIX 水平显著负相关
    assert np.corrcoef(aligned, valid.values)[0, 1] < -0.5

    # 按 VIX 取值本身分组比较（不按位置切片——滚动窗口会混合两段，位置切片不稳定）
    high_mask = aligned > 40
    low_mask = aligned < 20
    assert high_mask.sum() > 50 and low_mask.sum() > 50
    assert valid.values[high_mask].mean() < valid.values[low_mask].mean()


def test_nan_when_warmup_insufficient():
    score = VixFactor().score(_wide(np.full(100, 15.0)))
    assert score.isna().all()
