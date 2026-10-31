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


def test_update_indices_survives_cboe_failure(tmp_path, monkeypatch):
    """CBOE 抓取失败时**不能**把整步拖死 ✓。

    2026-10-31 实测风险：`fetch_cboe_index` 一抛错，`update_indices` 整个失败 ✗
    ⇒ `fetch_vix_live()` 用 yfinance 补的最新值也白搭 ✗
    ⇒ `vix.csv` 停在旧日期 ⇒ 简报「VIX/TERM 缺失」反复复发 ✗

    正确行为：降级为「本地文件 + live 补最新」✓，并打一行 warn ✓。
    """
    import pandas as pd

    from fg_system.data import fetch as f

    # 本地已有历史（2026-10-01 起 3 天）
    old = pd.DataFrame({
        "date": pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-03"]),
        "open": 20.0, "high": 21.0, "low": 19.0, "close": 20.5,
    })
    (tmp_path / "vix.csv").write_text(old.to_csv(index=False), encoding="utf-8")

    def _boom(name):
        raise OSError("CBOE 连不上")

    live = {"VIX": pd.DataFrame({
        "date": pd.to_datetime(["2026-10-04"]),
        "open": 22.0, "high": 23.0, "low": 21.0, "close": 22.5,
    })}

    monkeypatch.setattr(f, "fetch_cboe_index", _boom)
    monkeypatch.setattr(f, "fetch_vix_live", lambda days=10: live)

    out = f.update_indices(raw_dir=str(tmp_path))

    assert "VIX" in out, "CBOE 失败后连本地+live 都没写 ✗"
    got = pd.read_csv(tmp_path / "vix.csv", parse_dates=["date"])
    assert len(got) == 4, "live 补数没生效（应 3 旧 + 1 新）✗"
    assert got["date"].max() == pd.Timestamp("2026-10-04")
    assert "VIX3M" not in out, "无本地文件也无 live ⇒ 应跳过而不是写空 ✗"
