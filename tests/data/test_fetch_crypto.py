# -*- coding: utf-8 -*-
"""加密数据抓取测试。全部用离线 fixture，不发网络请求。"""
import json

import pandas as pd
import pytest

from fg_system.data import fetch


# ---------------------------------------------------------------- 贪恐指数

def test_parse_fng_rows_maps_value_and_date():
    payload = {
        "name": "Fear and Greed Index",
        "data": [
            {"value": "70", "value_classification": "Greed", "timestamp": "1789948800"},
            {"value": "15", "value_classification": "Extreme Fear", "timestamp": "1789862400"},
        ],
    }
    df = fetch.parse_fng_payload(payload)
    # 必须按日期升序
    assert list(df["value"]) == [15, 70]
    assert df["date"].is_monotonic_increasing
    assert df.loc[0, "classification"] == "Extreme Fear"


def test_parse_fng_payload_skips_bad_rows():
    payload = {"data": [
        {"value": "50", "value_classification": "Neutral", "timestamp": "1789948800"},
        {"value": "abc", "value_classification": "X", "timestamp": "1789862400"},
    ]}
    df = fetch.parse_fng_payload(payload)
    assert len(df) == 1


def test_parse_fng_payload_empty_returns_columns():
    df = fetch.parse_fng_payload({"data": []})
    assert list(df.columns) == ["date", "value", "classification"]
    assert df.empty


def test_fng_url_requests_full_history():
    """limit=0 才是全量；用默认 limit 只能拿到 1 条。"""
    url = fetch.fng_url()
    assert "limit=0" in url
    assert "format=json" in url


# ---------------------------------------------------------------- BTC 现货

def test_btc_url_has_sampled_false():
    """必须带 sampled=false，否则会降采样到 2-4 天间隔（§4.1）。"""
    url = fetch.btc_spot_url()
    assert "sampled=false" in url


def test_parse_btc_payload_converts_unix_to_date():
    payload = {"status": "ok", "values": [
        {"x": 1474588800, "y": 594.08},
        {"x": 1789948800, "y": 81136.2},
    ]}
    df = fetch.parse_btc_payload(payload)
    assert len(df) == 2
    assert df["date"].is_monotonic_increasing
    assert df.loc[0, "close"] == pytest.approx(594.08)
    assert str(df.loc[0, "date"].date()) == "2016-09-23"


def test_parse_btc_payload_drops_zero_prices():
    """blockchain.info 早期返回 y=0.0（2009 年 BTC 无市场价），必须剔除。"""
    payload = {"values": [
        {"x": 1230940800, "y": 0.0},
        {"x": 1789948800, "y": 81136.2},
    ]}
    df = fetch.parse_btc_payload(payload)
    assert len(df) == 1
    assert df.loc[0, "close"] == pytest.approx(81136.2)


def test_parse_btc_payload_empty_returns_columns():
    df = fetch.parse_btc_payload({"values": []})
    assert list(df.columns) == ["date", "close"]
    assert df.empty


# ---------------------------------------------------------------- 增量合并

def test_merge_crypto_prices_is_idempotent():
    a = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "symbol": ["BITX", "BITX"],
        "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
        "close": [1.0, 2.0], "volume": [10.0, 20.0],
    })
    merged = fetch.merge_incremental(a, a.copy())
    assert len(merged) == 2


def test_merge_crypto_prices_keeps_newer():
    old = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01"]), "symbol": ["BITX"],
        "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0],
    })
    new = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01"]), "symbol": ["BITX"],
        "open": [9.0], "high": [9.0], "low": [9.0], "close": [9.0], "volume": [9.0],
    })
    merged = fetch.merge_incremental(old, new)
    assert len(merged) == 1
    assert merged.loc[0, "close"] == pytest.approx(9.0)


# ---------------------------------------------------------------- $ 剥离（stocks 格式）

def test_parse_nasdaq_rows_strips_dollar_signs():
    """stocks 格式的所有价格字段都带 $，必须全部剥离（MSTR/COIN 依赖）。"""
    rows = [{"date": "01/02/2026", "open": "$164.58", "high": "$169.52",
             "low": "$164.49", "close": "$168.50", "volume": "1,234,567"}]
    df = fetch.parse_nasdaq_rows(rows, "MSTR")
    assert len(df) == 1
    assert df.loc[0, "close"] == pytest.approx(168.50)
    assert df.loc[0, "open"] == pytest.approx(164.58)
    assert df.loc[0, "high"] == pytest.approx(169.52)
    assert df.loc[0, "low"] == pytest.approx(164.49)


def test_parse_nasdaq_rows_still_works_without_dollar():
    """etf 格式不带 $，剥离操作必须是 no-op（v1 回归防线）。"""
    rows = [{"date": "01/02/2026", "open": "741.47", "high": "745.00",
             "low": "738.00", "close": "741.47", "volume": "1,000"}]
    df = fetch.parse_nasdaq_rows(rows, "QQQ")
    assert df.loc[0, "close"] == pytest.approx(741.47)
