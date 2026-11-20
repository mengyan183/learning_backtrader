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
    """加权平均：vix/term 给 100 分、其余 0 分 ⇒ 结果 = 两者权重占比。

    🔴 2026-11-20（第 12.47 条）：**期望值改为从 `config.WEIGHTS` 派生** ✗
       原来硬编码 `45.0`（注释还写着 0.30/0.15/0.25/0.15/0.15 的**五因子**口径，
       早就过期 ✗）⇒ 权重一改测试就红，但红得没意义 ✗
       现在：`putcall` 未参与 ⇒ 按**剩余权重归一**，期望值现算 ✓
    """
    from fg_system import config

    s = _scores(vix=[100.0] * 3, term=[100.0] * 3, price=[0.0] * 3,
                breadth=[0.0] * 3, fed=[0.0] * 3)
    out = idx.combine(s, _factors_from(s))
    w = config.WEIGHTS
    present = ("vix", "term", "price", "breadth", "fed")
    expect = (w["vix"] + w["term"]) / sum(w[k] for k in present) * 100.0
    assert out.iloc[0] == pytest.approx(expect)


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
    # 🔴 2026-11-20（第 12.47 条）：期望值从 `config.WEIGHTS` 派生 ✗
    #    原来硬编码 0.30/0.15/0.25/0.15（五因子旧口径）⇒ 权重一改就红 ✗
    from fg_system import config

    w = config.WEIGHTS
    present = ("vix", "term", "price", "fed")      # breadth 缺失
    expected = (80 * w["vix"] + 60 * w["term"] + 40 * w["price"]
                + 90 * w["fed"]) / sum(w[k] for k in present)
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


# ---------------------------------------------------------------- ICIR 折算（12.48）
def test_icir_deflates_by_overlap():
    """ICIR 必须按**重叠倍数**折算 ✓ —— 否则滚动窗口把 std 压低、ICIR 放大 ✗。

    🔴 2026-11-20（第 12.48 条）：`IC_WINDOW=60` + `HORIZON=20` ⇒ 相邻 IC
       共享 40 个观测 ⇒ 有效样本 ≈ n/3 ⇒ 按 1/sqrt(3) 折算 ✓
    """
    import math

    import numpy as np
    import pandas as pd

    from fg_system.factors.eval import icir

    rng = np.random.default_rng(7)
    s = pd.Series(rng.normal(-0.3, 0.2, 200))
    raw = icir(s)
    adj = icir(s, overlap=3)
    assert raw["overlap"] == 1
    assert adj["overlap"] == 3
    assert adj["icir_raw"] == pytest.approx(raw["icir"])
    assert adj["icir"] == pytest.approx(raw["icir"] / math.sqrt(3))
    # 均值/正值比/n 不受折算影响 ✓
    assert adj["ic_mean"] == pytest.approx(raw["ic_mean"])
    assert adj["n"] == raw["n"]


def test_evaluate_carries_overlap_from_window_and_horizon():
    """`evaluate()` 必须把 `overlap = ceil(window/horizon)` 带进结果 ✓。

    ⚠️ `window_stats()` 靠这个字段保证**全窗与近窗用同一系数** ✗
       —— 两者不一致会让对比失去意义 ✗
    """
    import numpy as np
    import pandas as pd

    from fg_system.factors.eval import evaluate, window_stats

    n = 300
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    rng = np.random.default_rng(11)
    sig = pd.Series(rng.normal(50, 10, n), index=idx)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)), index=idx)
    res = evaluate(sig, close, horizons=(20,), window=60)
    assert res[20]["overlap"] == 3          # ceil(60/20)
    ws = window_stats(res, 20)
    assert ws["stats"]["overlap"] == 3
    assert ws["recent_stats"]["overlap"] == 3
