# -*- coding: utf-8 -*-
"""损耗归因测试（§4.5）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import leverage


def test_decay_rate_matches_theory_for_3x():
    """年化波动率拖累 ≈ N(N-1)/2 × σ²；N=3 时 = 3σ²。"""
    assert leverage.vol_decay_rate(sigma=0.20, n=3) == pytest.approx(3 * 0.20 ** 2)
    assert leverage.vol_decay_rate(sigma=0.35, n=3) == pytest.approx(3 * 0.35 ** 2)


def test_decay_rate_is_zero_for_unleveraged():
    """N=1 时无杠杆，拖累必须为 0。"""
    assert leverage.vol_decay_rate(sigma=0.20, n=1) == pytest.approx(0.0)
    assert leverage.vol_decay_rate(sigma=0.50, n=2) == pytest.approx(1 * 0.50 ** 2)


def test_decompose_splits_vol_decay_and_product_cost():
    """构造已知损耗：标的零漂移有波动，杠杆 ETF 额外扣产品费率。"""
    n_days = 756
    rng = np.random.RandomState(7)
    und_ret = pd.Series(0.001 * rng.randn(n_days))
    lev_ret = 3 * und_ret - 0.0003          # 每日多扣 3bp ≈ 年化 7.56%

    out = leverage.decompose(und_ret, lev_ret)
    assert out["vol_decay_annual"] > 0
    assert out["product_cost_annual"] > 0
    assert out["total_annual"] == pytest.approx(
        out["vol_decay_annual"] + out["product_cost_annual"], rel=1e-6)


def test_decompose_handles_empty_input():
    out = leverage.decompose(pd.Series(dtype=float), pd.Series(dtype=float))
    assert np.isnan(out["total_annual"])


def test_current_decay_rate_includes_product_rate():
    rng = np.random.RandomState(8)
    ret = pd.Series(0.01 * rng.randn(300))
    rate = leverage.current_decay_rate(ret, sigma_window=20, n=3, product_rate=0.08)
    assert rate > 0.08          # 至少包含产品损耗率


def test_current_decay_rate_nan_when_insufficient_data():
    rate = leverage.current_decay_rate(pd.Series([0.01, 0.02]), sigma_window=20)
    assert np.isnan(rate)


def test_real_data_decay_is_in_expected_range():
    """真实数据回归：TQQQ 年化总损耗应在 15%~25%（§4.5 实测 20.22%）。"""
    prices = pd.read_csv("Data/raw/prices.csv", parse_dates=["date"])
    lev = prices[prices["symbol"] == "TQQQ"].set_index("date")["close"].sort_index()
    und = prices[prices["symbol"] == "QQQ"].set_index("date")["close"].sort_index()
    joined = pd.concat([lev.rename("lev"), und.rename("und")], axis=1).dropna()

    out = leverage.decompose(joined["und"].pct_change().dropna(),
                             joined["lev"].pct_change().dropna())
    assert 0.15 <= out["total_annual"] <= 0.25


def test_attribution_table_covers_all_symbols():
    prices = pd.read_csv("Data/raw/prices.csv", parse_dates=["date"])
    table = leverage.attribution_table(prices)
    assert set(table["leveraged"]) == {"TQQQ", "SOXL", "UPRO"}
    # SOXL 波动率最高，其损耗应显著高于 UPRO
    soxl = table.set_index("leveraged").loc["SOXL", "total_annual"]
    upro = table.set_index("leveraged").loc["UPRO", "total_annual"]
    assert soxl > upro
