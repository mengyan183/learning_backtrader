# -*- coding: utf-8 -*-
"""指数合成测试（§5.4）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system import index
from fg_system import index as idx


class FakeFactor:
    """用于隔离测试的假因子：直接返回预设序列，不依赖真实数据。"""

    def __init__(self, name, values):
        self.name = name
        self._values = values

    def score(self, wide):
        return self._values


def _scores(**kwargs):
    n = len(next(iter(kwargs.values())))
    return pd.DataFrame(kwargs, index=pd.date_range("2020-01-01", periods=n, freq="B"))


def _factors_from(scores):
    return [FakeFactor(k, scores[k]) for k in scores.columns]


def test_weighted_average_of_all_factors():
    s = _scores(vix=[100.0] * 3, term=[100.0] * 3, price=[0.0] * 3,
                breadth=[0.0] * 3, fed=[0.0] * 3)
    out = idx.combine(s, _factors_from(s))
    # 0.30*100 + 0.15*100 + 0.25*0 + 0.15*0 + 0.15*0 = 45
    assert out.iloc[0] == pytest.approx(45.0)


def test_missing_factor_renormalizes_weights():
    """F2 全 NaN 时，剩余三个因子按各自权重重新归一化。"""
    s = _scores(vix=[100.0] * 3, term=[np.nan] * 3, price=[100.0] * 3, breadth=[100.0] * 3)
    out = idx.combine(s, _factors_from(s))
    assert out.iloc[0] == pytest.approx(100.0)


def test_insufficient_factors_returns_nan():
    """有效因子少于 MIN_VALID_FACTORS 时当日不产生信号。"""
    s = _scores(vix=[50.0] * 3, term=[np.nan] * 3, price=[np.nan] * 3, breadth=[np.nan] * 3)
    out = idx.combine(s, _factors_from(s))
    assert out.isna().all()


def test_output_range_is_0_to_100():
    rng = np.random.RandomState(5)
    s = pd.DataFrame(
        {k: rng.uniform(0, 100, 500) for k in config.WEIGHTS},
        index=pd.date_range("2020-01-01", periods=500, freq="B"),
    )
    out = idx.combine(s, _factors_from(s)).dropna()
    assert out.between(0, 100).all()


def test_smoothing_days_one_is_identity():
    s = pd.Series(np.linspace(0, 100, 300))
    assert idx.smooth(s, 1).equals(s)


def test_build_factors_returns_six_named_factors():
    names = [f.name for f in idx.build_factors()]
    assert names == ["vix", "term", "price", "breadth", "fed", "putcall"]
    assert set(names) == set(config.WEIGHTS.keys())


# ---------------------------------------------------------------- v2 多市场

def test_build_factors_for_us_equity_unchanged():
    """大盘因子集合必须与 config.WEIGHTS 完全一致（v2.7 起含 putcall）。"""
    names = [f.name for f in index.build_factors_for("us_equity")]
    assert names == ["vix", "term", "price", "breadth", "fed", "putcall"]


def test_build_factors_for_crypto():
    names = [f.name for f in index.build_factors_for("crypto")]
    assert names == ["crypto_fng", "crypto_price"]


def test_weights_for_market():
    assert index.weights_for("us_equity") == config.WEIGHTS
    assert index.weights_for("crypto") == config.CRYPTO_WEIGHTS


def test_combine_uses_market_weights():
    """crypto 市场必须用 CRYPTO_WEIGHTS，而不是 WEIGHTS。"""
    scores = pd.DataFrame(
        {"crypto_fng": [100.0], "crypto_price": [0.0]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="crypto")
    # 50/50 权重 → 50
    assert out.iloc[0] == pytest.approx(50.0)


def test_combine_nan_when_one_of_two_missing_by_default():
    """crypto 只有 2 个因子，默认 min_valid=2 → 缺一个即无信号。

    设计依据 §5.4：「有效因子数 < MIN_VALID_FACTORS 时返回 NaN，避免单因子主导」。
    crypto 只有 2 个因子，若允许单因子重归一化，指数会被单个因子完全支配。
    """
    scores = pd.DataFrame(
        {"crypto_fng": [80.0], "crypto_price": [float("nan")]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="crypto")
    assert pd.isna(out.iloc[0])


def test_combine_renormalizes_when_min_valid_relaxed():
    """显式放宽 min_valid=1 时，单个有效因子按剩余权重重归一化（§5.4 的重归一化逻辑）。"""
    scores = pd.DataFrame(
        {"crypto_fng": [80.0], "crypto_price": [float("nan")]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="crypto", min_valid=1)
    assert out.iloc[0] == pytest.approx(80.0)


def test_combine_renormalizes_for_equity_when_one_missing():
    """大盘 5 个因子缺 1 个 → 4 个有效 ≥ 2 → 正常重归一化（§5.4）。"""
    scores = pd.DataFrame(
        {"vix": [80.0], "term": [60.0], "price": [40.0],
         "breadth": [float("nan")], "fed": [90.0]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="us_equity")
    # 权重 0.30/0.15/0.25/0.15，breadth 缺失 → 按剩余 4 因子归一化
    expected = (80 * 0.30 + 60 * 0.15 + 40 * 0.25 + 90 * 0.15) / \
        (0.30 + 0.15 + 0.25 + 0.15)
    assert out.iloc[0] == pytest.approx(expected)


def test_combine_nan_when_too_few_valid_factors():
    """有效因子数 < MIN_VALID_FACTORS 时必须 NaN，避免单因子主导。"""
    scores = pd.DataFrame(
        {"crypto_fng": [80.0], "crypto_price": [float("nan")]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="crypto", min_valid=2)
    assert pd.isna(out.iloc[0])


def test_build_index_returns_series_for_market():
    """build_index 是市场感知的统一入口。"""
    scores = pd.DataFrame(
        {"crypto_fng": [90.0, 10.0], "crypto_price": [90.0, 10.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    out = index.build_index(scores, market="crypto")
    assert isinstance(out, pd.Series)
    assert out.iloc[0] == pytest.approx(90.0)
    assert out.iloc[1] == pytest.approx(10.0)
