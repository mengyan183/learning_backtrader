# -*- coding: utf-8 -*-
"""CF2 BTC 价格因子测试（§5.2 CF2）。输入必须是 BTC 现货。

夹具长度要求：`drawdown_52w`(252) 与 `rolling_pct`(756) 串联，二者叠加后
首个非 NaN 出现在第 **1007** 个点（0-based 索引 1006）。因此本文件所有
断言有效输出的测试一律使用 **≥1100 点**，留足余量。

断言写法（对齐 v1 `tests/factors/test_price.py`）：用「持续上涨 vs 长上涨后
近期急跌」两类行情比较分数，**不能**用「单调上涨 vs 单调下跌」——`rolling_pct`
度量的是「今日在近 756 日中的相对位置」而非趋势方向，持续下跌会让反转子项
（dd = 1 - 回撤分位、calm = 1 - 波动分位）反而变高，净效应是下跌行情分更高。
这是 `rolling_pct` 的结构性性质（见 `fg_system/factors/base.py` docstring）。
"""
import pandas as pd
import pytest

from fg_system.factors.crypto_price import CryptoPriceFactor

# drawdown_52w(252) + rolling_pct(756) 串联 → 索引 1006 为首个有效值。
WARMUP_INDEX = 1006


def _wide(closes, start="2016-01-04"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({("BTC", "close"): list(closes)}, index=idx)


def _trending(n, start=100.0, step=0.01):
    return [start * (1 + step) ** i for i in range(n)]


def test_name_and_market():
    f = CryptoPriceFactor()
    assert f.name == "crypto_price"
    assert f.market == "crypto"


def test_score_in_range():
    w = _wide(_trending(1100))
    s = CryptoPriceFactor().score(w)
    assert not s.dropna().empty
    assert s.dropna().min() >= 0.0 and s.dropna().max() <= 100.0


def test_warmup_returns_nan():
    w = _wide(_trending(100))
    s = CryptoPriceFactor().score(w)
    assert s.isna().all()


def test_warmup_boundary_is_1008_days():
    """drawdown_52w(252) 叠加 rolling_pct(756) → 首个有效值在 0-based 索引 1006。

    （序列第 1007 个点；`rolling_pct` 需要完整 756 个非 NaN 输入才产出首值。）
    """
    w = _wide(_trending(1100, step=0.003))
    s = CryptoPriceFactor().score(w)
    valid_idx = s.dropna().index
    assert len(valid_idx) > 0
    assert s.iloc[:WARMUP_INDEX].isna().all(), "索引 1006 之前必须全为 NaN"
    assert pd.notna(s.iloc[WARMUP_INDEX]), "索引 1006 处必须是首个有效值"


def test_recent_crash_scores_lower_than_sustained_rise():
    """长上涨 vs 长上涨后近期急跌：后者分数必须更低。

    注意：**不能**用「单调上涨 vs 单调下跌」做对照——rolling_pct 度量的是
    「今日在近 756 日中的相对位置」而非趋势方向，持续下跌会让反转子项
    （dd=1-回撤分位、calm=1-波动分位）反而变高，净效应是下跌行情分更高。
    这是 rolling_pct 的结构性性质（见 factors/base.py docstring），
    v1 的 tests/factors/test_price.py 同样避开了这个陷阱。
    """
    n = 1200
    rising = _trending(n, step=0.004)
    crash = rising[:-30] + [rising[-30] * (1 - 0.01 * i) for i in range(1, 31)]
    s_up = CryptoPriceFactor().score(_wide(rising)).dropna()
    s_crash = CryptoPriceFactor().score(_wide(crash)).dropna()
    assert s_up.iloc[-1] > s_crash.iloc[-1]


def test_deep_drawdown_scores_low():
    """深度回撤后分数必须显著下降（回撤子项是反转方向）。"""
    n = 1100
    rising = _trending(n)
    crashed = rising[:-1] + [rising[-1] * 0.4]
    w = _wide(crashed)
    s = CryptoPriceFactor().score(w).dropna()
    assert s.iloc[-1] < 50.0


def test_missing_btc_column_raises():
    w = pd.DataFrame({("FNG", "value"): [50.0, 60.0]})
    with pytest.raises(ValueError):
        CryptoPriceFactor().raw(w)


def test_uses_btc_not_leveraged_etf():
    """红线：因子输入必须是 BTC 现货，出现 BITX 列也不应被使用。

    做法：同时提供 BTC 与 BITX 列，其中 BITX 是人为污染的极端值。
    若实现误用 BITX，分数会明显不同。

    注意：夹具必须足够长（≥1100）——否则两个序列都全 NaN，`dropna()` 后
    都为空，`assert_series_equal` 会**假通过**，起不到红线作用。
    """
    n = 1100
    btc = _trending(n)
    idx = pd.bdate_range("2016-01-04", periods=n)
    w = pd.DataFrame({("BTC", "close"): btc}, index=idx)
    w[("BITX", "close")] = [1.0] * n          # 污染列：恒定值
    clean = pd.DataFrame({("BTC", "close"): btc}, index=idx)
    a = CryptoPriceFactor().score(w).dropna()
    b = CryptoPriceFactor().score(clean).dropna()
    assert not a.empty and not b.empty         # 防止全 NaN 假通过
    pd.testing.assert_series_equal(a, b)
