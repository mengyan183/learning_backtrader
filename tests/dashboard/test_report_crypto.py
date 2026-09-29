# -*- coding: utf-8 -*-
"""仪表盘加密区块测试。"""
import pandas as pd
import pytest

from fg_system.dashboard import report


def _us():
    idx = pd.bdate_range("2024-01-01", periods=30)
    return pd.DataFrame({
        "fg_index": range(30), "zone": [0] * 30, "target_position": [0.4] * 30,
        "core_position": [0.4] * 30, "ammo_position": [0.0] * 30,
        "drawdown": [0.0] * 30, "circuit_breaker": [False] * 30,
        "note": [""] * 30, "trend_blocked": [False] * 30,
    }, index=idx)


def _crypto():
    idx = pd.bdate_range("2024-01-01", periods=30)
    return pd.DataFrame({
        "crypto_fg_index": range(30), "zone": [0] * 30,
        "target_position": [0.1] * 30, "core_position": [0.1] * 30,
        "layer_btc_beta": [0.1] * 30, "layer_stock_high_beta": [0.07] * 30,
        "layer_stock_ops_beta": [0.05] * 30,
        "greed_tier": [0] * 30, "trend_blocked": [False] * 30,
        "drawdown": [0.0] * 30, "note": [""] * 30,
    }, index=idx)


def _html(tmp_path, crypto=None, coinglass=None):
    p = str(tmp_path / "dash.html")
    report.build_v2(_us(), crypto if crypto is not None else _crypto(),
                    path=p, coinglass_value=coinglass)
    return open(p, encoding="utf-8").read()


def test_crypto_section_included(tmp_path):
    assert "加密贪婪恐惧指数" in _html(tmp_path)


def test_crypto_layer_caps_shown(tmp_path):
    html = _html(tmp_path)
    assert "BTC 纯 Beta" in html
    assert "币股高 Beta" in html
    assert "币股经营 Beta" in html


def test_coinglass_reference_section_present(tmp_path):
    """coinglass 人工对照栏必须存在（设计 §10.3）。"""
    assert "coinglass" in _html(tmp_path).lower()


def test_coinglass_value_shown_when_provided(tmp_path):
    html = _html(tmp_path, coinglass=72.0)
    assert "72.0" in html


def test_trend_filter_status_shown(tmp_path):
    assert "趋势过滤" in _html(tmp_path)


def test_warmup_crypto_shows_notice(tmp_path):
    """加密无有效信号时必须给出说明，不能崩溃。"""
    cr = _crypto()
    cr["crypto_fg_index"] = float("nan")
    html = _html(tmp_path, crypto=cr)
    assert "warmup" in html


def test_greed_tier_label_shown(tmp_path):
    cr = _crypto()
    cr["greed_tier"] = 2
    html = _html(tmp_path, crypto=cr)
    assert "第 2 档" in html


def test_v1_build_still_works(tmp_path):
    """v1 的 build() 必须不受影响（回归防线）。"""
    p = str(tmp_path / "v1.html")
    out = report.build(_us(), path=p)
    assert out == p
    assert "贪婪恐惧指数仪表盘" in open(p, encoding="utf-8").read()
