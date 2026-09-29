# -*- coding: utf-8 -*-
"""标的权重层测试（§7.2 / trading-discipline.md 第 4C 条：反比波动率 / 风险平价）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config, pipeline


def _wide(n=400, seed=0, scales=None, etf_scales=None):
    """构造宽表：含**无杠杆底层**与 **ETF 自身**两套价格。

    默认波动率刻意**互相矛盾**，使「用底层」与「用 ETF」得出**相反**的权重，
    从而让相关测试真正有判别力：
      底层：QQQ 0.010 / SOXX 0.030 / SPY 0.008   ⇒ SOXL 权重**最低**
      ETF ：TQQQ 0.030 / SOXL 0.010 / UPRO 0.030 ⇒ 若误用 ETF，SOXL 权重**最高**
    """
    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.RandomState(seed)
    scales = scales or {"QQQ": 0.010, "SOXX": 0.030, "SPY": 0.008}
    etf_scales = etf_scales or {"TQQQ": 0.030, "SOXL": 0.010, "UPRO": 0.030}
    cols = {}
    for und, scale in scales.items():
        r = rng.normal(0.0, scale, n)
        cols[(und, "close")] = 100.0 * (1.0 + r).cumprod()
    for sym, scale in etf_scales.items():
        r = rng.normal(0.0, scale, n)
        cols[(sym, "close")] = 100.0 * (1.0 + r).cumprod()
    w = pd.DataFrame(cols, index=idx)
    w.columns = pd.MultiIndex.from_tuples(w.columns)
    return w


# ---------------------------------------------------------------- 基本性质

def test_weights_columns_are_etf_symbols():
    w = pipeline.risk_weight_series(_wide(), window=252)
    assert list(w.columns) == config.SYMBOLS


def test_weights_sum_to_one():
    w = pipeline.risk_weight_series(_wide(), window=252)
    assert np.allclose(w.sum(axis=1), 1.0)


def test_weights_are_non_negative():
    w = pipeline.risk_weight_series(_wide(), window=252)
    assert (w.to_numpy() >= 0).all()


def test_weights_never_nan():
    """不足窗口时退化为等权，**不得**返回 NaN（§4C.6）。"""
    w = pipeline.risk_weight_series(_wide(n=100), window=252)
    assert not w.isna().any().any()


# ---------------------------------------------------------------- 反比关系

def test_higher_volatility_gets_lower_weight():
    """SOXX 波动率 3 倍于 QQQ、3.75 倍于 SPY ⇒ SOXL 权重最低、UPRO 最高。"""
    w = pipeline.risk_weight_series(_wide(), window=252)
    last = w.iloc[-1]
    assert last["SOXL"] < last["TQQQ"] < last["UPRO"]


def test_weights_match_inverse_vol_ratio():
    """权重必须严格等于 1/σ 归一化后的值（不只是排序对）。"""
    wide = _wide()
    w = pipeline.risk_weight_series(wide, window=252)
    vol = pd.DataFrame({
        s: wide[(config.UNDERLYING_MAP[s], "close")].pct_change(fill_method=None)
        .rolling(252, min_periods=252).std()
        for s in config.SYMBOLS
    })
    equal = 1.0 / len(config.SYMBOLS)
    expected = (1.0 / vol)
    expected = expected.div(expected.sum(axis=1), axis=0)
    # 不足窗口的行退化为等权（§4C.6），shift(1) 防前视
    expected = expected.where(expected.notna().all(axis=1), other=equal)
    expected = expected.shift(1).fillna(equal)
    pd.testing.assert_frame_equal(w, expected, check_freq=False)


# ---------------------------------------------------------------- 用底层而非 ETF

def test_weights_use_underlying_not_etf():
    """权重必须由**无杠杆底层**决定，**不能**用 ETF 自身波动率（§4C.4）。

    夹具刻意让两者矛盾（底层 SOXX 波动最大，ETF SOXL 波动最小）⇒
    若实现误用 ETF，权重排序会**反转**。
    """
    wide = _wide()
    last = pipeline.risk_weight_series(wide, window=252).iloc[-1]
    # 底层口径：SOXX 波动最大 ⇒ SOXL 权重最低
    assert last["SOXL"] == last.min()
    # 先证明夹具确实矛盾：ETF 口径下 SOXL 波动最小
    etf_vol = pd.DataFrame({
        s: wide[(s, "close")].pct_change(fill_method=None)
        .rolling(252, min_periods=252).std()
        for s in config.SYMBOLS
    }).iloc[-1]
    assert etf_vol["SOXL"] == etf_vol.min()


# ---------------------------------------------------------------- 前视红线

def test_weights_unchanged_by_future_data():
    """截断未来数据后，已发生日期的权重必须**逐位不变**（§4C.2 前视红线）。"""
    wide = _wide()
    full = pipeline.risk_weight_series(wide, window=252)
    cut_at = wide.index[320]
    part = pipeline.risk_weight_series(wide.loc[:cut_at], window=252)
    pd.testing.assert_frame_equal(part, full.loc[:cut_at], check_freq=False)


def test_weights_shift_with_input():
    """把输入整体后移一天，权重也必须后移一天。"""
    wide = _wide()
    a = pipeline.risk_weight_series(wide, window=252)
    b = pipeline.risk_weight_series(wide.shift(1), window=252)
    idx = wide.index[300:400]
    pd.testing.assert_frame_equal(
        b.loc[idx].reset_index(drop=True),
        a.shift(1).loc[idx].reset_index(drop=True),
        check_freq=False)


# ---------------------------------------------------------------- 等权模式

def test_equal_weighting_mode_returns_uniform():
    w = pipeline.risk_weight_series(_wide(), window=252, weighting="equal")
    assert np.allclose(w.to_numpy(), 1.0 / len(config.SYMBOLS))


# ---------------------------------------------------------------- 权重 → 标的仓位

def test_weighted_targets_sum_to_target_position():
    """各标的仓位之和必须等于组合目标仓位（Σw = 1）。"""
    w = pipeline.risk_weight_series(_wide(), window=252)
    target = pd.Series(0.435, index=w.index)
    t = pipeline.weighted_targets(target, w)
    assert list(t.columns) == config.SYMBOLS
    assert np.allclose(t.sum(axis=1), 0.435)


def test_weighted_targets_keep_nan_during_warmup():
    """目标仓位为 NaN（warmup）时，各标的也必须写 NaN——**不能写 0.0**。

    0.0 会被回测当成「策略主动空仓」，污染净值与逐年表现
    （同 pipeline.run 的既有约定）。
    """
    w = pipeline.risk_weight_series(_wide(), window=252)
    target = pd.Series(np.nan, index=w.index)
    t = pipeline.weighted_targets(target, w)
    assert t.isna().all().all()


def test_weighted_targets_lower_vol_gets_more_capital():
    """同样目标仓位下，低波动标的必须拿到更多资金。"""
    w = pipeline.risk_weight_series(_wide(), window=252)
    target = pd.Series(0.60, index=w.index)
    t = pipeline.weighted_targets(target, w)
    last = t.iloc[-1]
    assert last["UPRO"] > last["TQQQ"] > last["SOXL"]


# ---------------------------------------------------------------- 加密标的权重（第 4B.6 条）

def test_crypto_layer_weight_normalized_from_caps():
    """层权重 = 层上限归一化（第 4B.6 条）。"""
    caps = config.CRYPTO_LAYER_CAP
    total = sum(caps.values())
    for layer, w in config.CRYPTO_LAYER_WEIGHT.items():
        assert w == pytest.approx(caps[layer] / total)
    assert sum(config.CRYPTO_LAYER_WEIGHT.values()) == pytest.approx(1.0)


def test_crypto_symbol_weights_sum_to_one():
    w = pipeline.crypto_symbol_weights()
    assert w.sum() == pytest.approx(1.0)
    assert set(w.index) == set(config.CRYPTO_FLAT_SYMBOLS)


def test_crypto_symbol_weights_descending_by_layer():
    """越靠「间接」的层，权重越低（§6.3 的设计意图必须真正生效）。"""
    w = pipeline.crypto_symbol_weights()
    btc = w[config.CRYPTO_SYMBOLS["btc_beta"]].sum()
    high = w[config.CRYPTO_SYMBOLS["stock_high_beta"]].sum()
    ops = w[config.CRYPTO_SYMBOLS["stock_ops_beta"]].sum()
    assert btc > high > ops


def test_crypto_symbol_weights_equal_within_layer():
    """层内必须等权（第 4B.6 条）。"""
    w = pipeline.crypto_symbol_weights()
    for members in config.CRYPTO_SYMBOLS.values():
        vals = [w[s] for s in members]
        assert all(v == pytest.approx(vals[0]) for v in vals)


def test_crypto_symbol_weights_expected_values():
    """层上限 80/50/30 ⇒ 层权重 50%/31.25%/18.75%，层内等权。

    v2.8（第 12.23 条）：`btc_beta` 由 2 个标的增为 **3 个**（加入 BTC 现货杠杆），
    故该层各标的权重由 25% 降为 **50%/3 = 16.667%**。
    """
    w = pipeline.crypto_symbol_weights()
    assert w["BITX"] == pytest.approx(0.50 / 3)
    assert w["BITU"] == pytest.approx(0.50 / 3)
    assert w["BTC"] == pytest.approx(0.50 / 3)
    assert w["MSTX"] == pytest.approx(0.15625)
    assert w["MSTU"] == pytest.approx(0.15625)
    assert w["CONL"] == pytest.approx(0.1875)


def test_btc_spot_margin_leverage_upper_bound():
    """**核心约束**：BTC 现货杠杆的杠杆上限必须扛得住 BTC 历史最大回撤 + 5pp 余量。

    强平回撤 `x = (1/L − mmr)/(1 − mmr)`。第 12.13 条要求留约 5pp 余量。
    **若有人把 L 调到 3x（「小资金博收益」），此测试必须失败** ——
    强平 = 在最恐慌时被迫卖出，与 §1.3「拿得住」直接冲突，故 3x 不得进入系统。
    """
    L = config.CRYPTO_LEVERAGE["BTC"]
    mmr = 0.005
    liq_drop = (1.0 / L - mmr) / (1.0 - mmr)
    btc_max_dd = 0.832                        # 实测 2018-12-16
    assert liq_drop >= btc_max_dd + 0.05, \
        "杠杆 %.2fx 的强平回撤 %.1f%% 不足以扛 BTC 历史最大回撤 %.1f%% + 5pp 余量" \
        % (L, liq_drop * 100, btc_max_dd * 100)


def test_btc_spot_margin_cost_matches_derivation_and_beats_bitx():
    """**成本先验**：成本率必须等于 `(1 − 1/L) × 借U利率`，且显著低于 BITX/BITU。

    这是第 12.23 条先验推导①的量化形式：若有人把 BTC 成本率改高，
    说明「纳入现货杠杆」的理由已不成立，必须重新推导。
    """
    r = 0.035                                 # 借 USDT 年化利率（实盘）
    L = config.CRYPTO_LEVERAGE["BTC"]
    derived = (1.0 - 1.0 / L) * r
    assert config.CRYPTO_PRODUCT_COST_RATE["BTC"] == pytest.approx(derived, abs=1e-4)
    assert config.CRYPTO_PRODUCT_COST_RATE["BTC"] < \
        config.CRYPTO_PRODUCT_COST_RATE["BITU"] / 10.0


def test_btc_is_excluded_from_fetch_list():
    """BTC 不是 Nasdaq 标的，混进抓取清单会按 `assetclass=stocks` 去抓并失败。"""
    assert "BTC" in config.CRYPTO_FLAT_SYMBOLS
    assert "BTC" not in config.CRYPTO_FETCH_SYMBOLS


def test_long_to_wide_builds_multiindex_columns():
    idx = pd.bdate_range("2024-01-01", periods=5)
    long = pd.DataFrame({
        "date": list(idx) * 2,
        "symbol": ["A"] * 5 + ["B"] * 5,
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 2.0, "volume": 3.0,
    })
    wide = pipeline.long_to_wide(long)
    assert ("A", "close") in wide.columns
    assert ("B", "volume") in wide.columns
    assert wide[("A", "close")].iloc[0] == pytest.approx(2.0)


def test_long_to_wide_skips_missing_fields():
    """只有 date/symbol/close 的表（**加密合成轨就是这样**）必须可用。

    硬性要求 OHLCV 会 KeyError——合成轨只有 close。
    """
    idx = pd.bdate_range("2024-01-01", periods=5)
    long = pd.DataFrame({
        "date": list(idx) * 2,
        "symbol": ["A"] * 5 + ["B"] * 5,
        "close": 2.0,
    })
    wide = pipeline.long_to_wide(long)
    assert list(wide.columns.get_level_values("field").unique()) == ["close"]
    assert wide[("A", "close")].iloc[0] == pytest.approx(2.0)


def test_long_to_wide_requires_close():
    """连 close 都没有必须报错（fail fast），不得静默产出空表。"""
    long = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=2),
                         "symbol": ["A", "A"], "volume": 1.0})
    with pytest.raises(ValueError):
        pipeline.long_to_wide(long)


# ---------------------------------------------------------------- 加权篮子（组合级口径）

def test_basket_returns_is_weighted_sum():
    """篮子收益 = Σ w_i r_i。"""
    wide = _wide()
    w = pipeline.risk_weight_series(wide, window=252)
    rets = pd.DataFrame({s: wide[(s, "close")].pct_change(fill_method=None)
                         for s in config.SYMBOLS})
    expected = (w * rets).sum(axis=1, min_count=1)
    pd.testing.assert_series_equal(
        pipeline.weighted_basket_returns(wide, w), expected, check_freq=False)


def test_basket_returns_equal_weight_is_mean():
    """等权口径下篮子收益 = 三标的算术平均。"""
    wide = _wide()
    w = pipeline.risk_weight_series(wide, window=252, weighting="equal")
    rets = pd.DataFrame({s: wide[(s, "close")].pct_change(fill_method=None)
                         for s in config.SYMBOLS})
    pd.testing.assert_series_equal(
        pipeline.weighted_basket_returns(wide, w), rets.mean(axis=1),
        check_freq=False)


def test_basket_returns_renormalizes_on_missing_symbol():
    """某标的无数据时剔除并重新归一化，**不得**把缺失当成 0 收益。"""
    wide = _wide()
    wide.loc[wide.index[300:], ("SOXL", "close")] = np.nan
    w = pipeline.risk_weight_series(wide, window=252, weighting="equal")
    b = pipeline.weighted_basket_returns(wide, w)
    rets = pd.DataFrame({s: wide[(s, "close")].pct_change(fill_method=None)
                         for s in config.SYMBOLS})
    tail = rets.iloc[305:]
    expected = tail[["TQQQ", "UPRO"]].mean(axis=1)
    pd.testing.assert_series_equal(b.iloc[305:], expected, check_freq=False)


def test_basket_price_series_compounds_returns():
    r = pd.Series([0.10, -0.10, 0.05], index=pd.bdate_range("2024-01-01", periods=3))
    p = pipeline.basket_price_series(r, start=100.0)
    assert p.iloc[0] == pytest.approx(110.0)
    assert p.iloc[1] == pytest.approx(99.0)
    assert p.iloc[2] == pytest.approx(103.95)


def test_basket_price_series_keeps_leading_nan():
    """**前导 NaN 必须保持 NaN**，不得填成 0 收益。

    否则「数据尚未开始」会被当成「价格恒定」，把年化与回撤双双稀释
    （加密真实轨 ETF 2022 年才有数据，实测曾被算成「2510 日、年化 -0.52%」）。
    """
    idx = pd.bdate_range("2024-01-01", periods=5)
    r = pd.Series([np.nan, np.nan, 0.10, -0.10, 0.05], index=idx)
    p = pipeline.basket_price_series(r, start=100.0)
    assert p.iloc[:2].isna().all()
    assert p.iloc[2] == pytest.approx(110.0)
    assert p.iloc[4] == pytest.approx(103.95)


def test_basket_price_series_all_nan():
    idx = pd.bdate_range("2024-01-01", periods=3)
    p = pipeline.basket_price_series(pd.Series(np.nan, index=idx))
    assert p.isna().all()


def test_basket_price_series_fills_interior_gap():
    """**内部缺口**按 0 收益处理（不 splice 序列）。"""
    idx = pd.bdate_range("2024-01-01", periods=4)
    r = pd.Series([0.10, np.nan, 0.10, 0.10], index=idx)
    p = pipeline.basket_price_series(r, start=100.0)
    assert p.notna().all()
    assert p.iloc[1] == pytest.approx(110.0)     # 缺口 = 0 收益
    assert p.iloc[3] == pytest.approx(110.0 * 1.1 * 1.1)
