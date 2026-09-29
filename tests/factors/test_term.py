# -*- coding: utf-8 -*-
"""F2 波动率期限结构测试（§5.2 F2）。

原设计为 CBOE Put/Call，因官方文件停更于 2019-10 而改用 VIX/VIX3M 比值。
断言写法说明：按**比值取值分组**比较均值，不用位置切片——滚动窗口会混合正常段
与倒挂段，位置切片不稳定（见 Task 5 的同类修正）。
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors.term import TermStructureFactor


def _wide(vix, vix3m):
    idx = pd.date_range("2020-01-01", periods=len(vix), freq="B")
    cols = pd.MultiIndex.from_tuples(
        [("VIX", "close"), ("VIX3M", "close")], names=["symbol", "field"]
    )
    return pd.DataFrame(np.c_[vix, vix3m], index=idx, columns=cols)


def test_score_range():
    rng = np.random.RandomState(1)
    vix = 15 + 5 * rng.randn(1200)
    vix3m = 18 + 4 * rng.randn(1200)
    score = TermStructureFactor().score(_wide(vix, vix3m)).dropna()
    assert not score.empty
    assert score.between(0, 100).all()


def test_inverted_term_structure_lowers_score():
    """期限结构倒挂（VIX > VIX3M）表示短期恐慌，分数必须更低。"""
    rng = np.random.RandomState(2)
    base = 15 + 2 * rng.randn(1200)
    normal_vix, normal_3m = base, base + 3.0            # 正常：远期高于近期
    inv_vix = 60 + 2 * rng.randn(400)
    inv_3m = 45 + 2 * rng.randn(400)                    # 倒挂：近期高于远期
    vix = np.concatenate([normal_vix, inv_vix])
    vix3m = np.concatenate([normal_3m, inv_3m])

    score = TermStructureFactor().score(_wide(vix, vix3m))
    valid = score.dropna()
    assert len(valid) > 500

    ratio = (vix / vix3m)[score.notna()]
    inv_mask = ratio > 1.15
    norm_mask = ratio < 0.95
    assert inv_mask.sum() > 50 and norm_mask.sum() > 50
    assert valid.values[inv_mask].mean() < valid.values[norm_mask].mean()


def test_nan_when_insufficient_warmup():
    score = TermStructureFactor().score(_wide(np.full(50, 15.0), np.full(50, 18.0)))
    assert score.isna().all()
