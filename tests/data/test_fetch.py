# -*- coding: utf-8 -*-
"""抓取层测试：解析与增量合并逻辑（不依赖网络）。"""
import pandas as pd
import pytest

from fg_system.data import fetch


NASDAQ_ROW = {"date": "09/18/2026", "close": "72.64", "volume": "41,007,910",
              "open": "71.915", "high": "72.7777", "low": "70.8094"}


def test_parse_nasdaq_rows_handles_commas_and_mm_dd_yyyy():
    df = fetch.parse_nasdaq_rows([NASDAQ_ROW], "TQQQ")
    assert len(df) == 1
    assert df["date"].iloc[0] == pd.Timestamp("2026-09-18")
    assert df["close"].iloc[0] == pytest.approx(72.64)
    assert df["volume"].iloc[0] == pytest.approx(41007910)
    assert df["symbol"].iloc[0] == "TQQQ"


def test_parse_nasdaq_rows_skips_bad_rows():
    rows = [NASDAQ_ROW, {"date": "", "close": "", "volume": "", "open": "", "high": "", "low": ""}]
    df = fetch.parse_nasdaq_rows(rows, "TQQQ")
    assert len(df) == 1


def test_merge_incremental_is_idempotent():
    old = pd.DataFrame({"date": [pd.Timestamp("2026-09-17")], "symbol": ["TQQQ"],
                        "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})
    new = pd.DataFrame({"date": [pd.Timestamp("2026-09-17"), pd.Timestamp("2026-09-18")],
                        "symbol": ["TQQQ", "TQQQ"], "open": [1.0, 2.0], "high": [1.0, 2.0],
                        "low": [1.0, 2.0], "close": [1.0, 2.0], "volume": [1.0, 2.0]})
    merged = fetch.merge_incremental(old, new)
    assert len(merged) == 2
    # 重复执行不产生重复行
    assert len(fetch.merge_incremental(merged, new)) == 2


def test_missing_ranges_returns_start_when_empty():
    assert fetch.missing_ranges(pd.DataFrame(), "TQQQ") == (None, None)


def test_missing_ranges_returns_last_date_plus_one():
    old = pd.DataFrame({"date": [pd.Timestamp("2026-09-17")], "symbol": ["TQQQ"]})
    start, _ = fetch.missing_ranges(old, "TQQQ")
    assert start == pd.Timestamp("2026-09-18")


def test_parse_nasdaq_rows_empty_returns_frame_with_columns():
    """空数据必须返回带列名的空表，不能抛 KeyError。

    真实场景：本地数据已是最新时，missing_ranges 返回"明天"，Nasdaq 对未来日期
    返回 0 行——原实现无条件 sort_values("date") 会因无列而崩溃，导致首次增量
    更新即失败。
    """
    df = fetch.parse_nasdaq_rows([], "TQQQ")
    assert df.empty
    assert list(df.columns) == ["date", "symbol", "open", "high", "low", "close", "volume"]


def test_parse_nasdaq_rows_all_rows_invalid_returns_empty_frame():
    """所有行都解析失败时同样必须返回带列名的空表。"""
    bad = [{"date": "", "close": "", "volume": "", "open": "", "high": "", "low": ""}]
    df = fetch.parse_nasdaq_rows(bad, "TQQQ")
    assert df.empty
    assert "date" in df.columns


def test_merge_incremental_handles_empty_new():
    """本次无新增数据时合并应原样返回，不崩溃。"""
    old = pd.DataFrame({"date": [pd.Timestamp("2026-09-17")], "symbol": ["TQQQ"],
                        "open": [1.0], "high": [1.0], "low": [1.0],
                        "close": [1.0], "volume": [1.0]})
    merged = fetch.merge_incremental(old, pd.DataFrame())
    assert len(merged) == 1
