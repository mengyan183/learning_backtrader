# -*- coding: utf-8 -*-
"""CF1 加密贪恐因子测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system.factors.crypto_fng import CryptoFngFactor


def _wide(values, start="2016-01-04"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame({("FNG", "value"): list(values)}, index=idx)


def test_name_and_market():
    f = CryptoFngFactor()
    assert f.name == "crypto_fng"
    assert f.market == "crypto"


def test_score_in_range():
    w = _wide(np.linspace(10, 90, config.RANK_WINDOW + 50))
    s = CryptoFngFactor().score(w)
    valid = s.dropna()
    assert not valid.empty
    assert valid.min() >= 0.0 and valid.max() <= 100.0


def test_warmup_returns_nan():
    """窗口不足处必须 NaN（§10.4：禁止用不足窗口的数据凑值）。"""
    w = _wide(np.linspace(10, 90, 100))
    s = CryptoFngFactor().score(w)
    assert s.isna().all()


def test_high_fng_gives_high_score():
    """贪恐值高 = 贪婪 = 高分，**方向不反转**（与 VIX 相反）。"""
    w = _wide(np.linspace(10, 90, config.RANK_WINDOW))
    s = CryptoFngFactor().score(w)
    assert s.dropna().iloc[-1] > 50.0


def test_low_fng_gives_low_score():
    w = _wide(np.linspace(90, 10, config.RANK_WINDOW))
    s = CryptoFngFactor().score(w)
    assert s.dropna().iloc[-1] < 50.0


def test_missing_column_raises():
    """缺少 FNG 列必须报错，不能静默返回全 NaN。"""
    w = pd.DataFrame({("BTC", "close"): [1.0, 2.0]})
    with pytest.raises(ValueError):
        CryptoFngFactor().raw(w)


def test_constant_series_is_handled():
    """恒定值序列不应崩溃（百分位退化为固定值）。"""
    w = _wide([50.0] * (config.RANK_WINDOW + 10))
    s = CryptoFngFactor().score(w)
    assert not s.dropna().empty
