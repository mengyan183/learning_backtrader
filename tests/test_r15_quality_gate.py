# -*- coding: utf-8 -*-
"""R1.5 数据质量闸门测试（drift_monitor 扩展）。

覆盖：
- check_price_series：无效值 / 断档 / 跳空检出，近窗限定
- check_vix_series：极端值 / 跳空
- check_sentiment_series：NaN / 断档
- quality_gate 合并写 freshness_warning.txt（保留停更告警、替换旧数据质量节）
"""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.drift_monitor import (  # noqa: E402
    check_price_series, check_vix_series, check_sentiment_series,
    quality_gate, QUALITY_TAG, WARN_PATH, DATA, JUMP_SPY)


def _px(dates, closes, symbol="TQQQ", volumes=None):
    n = len(dates)
    return pd.DataFrame({
        "date": dates, "symbol": symbol,
        "open": closes, "high": closes, "low": closes,
        "close": closes,
        "volume": volumes if volumes is not None else [1e6] * n,
    })


def test_price_invalid_values():
    df = _px(pd.date_range("2026-09-01", periods=5, freq="B"), [10, 11, 0, 12, 13])
    issues = check_price_series(df, "TQQQ")
    assert any("无效值" in i for i in issues)


def test_price_gap_detected():
    # 中间插入 10 天缺口
    dates = list(pd.date_range("2026-09-01", periods=10, freq="B"))
    dates += list(pd.date_range("2026-09-21", periods=10, freq="B"))
    closes = [10 + i for i in range(20)]
    df = _px(dates, closes)
    issues = check_price_series(df, "TQQQ")
    assert any("断档" in i for i in issues)


def test_price_jump_detected():
    dates = pd.date_range("2026-09-01", periods=6, freq="B")
    closes = [10, 10.1, 10.2, 10.3, 10.4, 16.0]   # 最后一日 +54%
    df = _px(dates, closes)
    issues = check_price_series(df, "TQQQ")
    assert any("跳空" in i for i in issues)
    # SPY 阈值更严：同样 20% 应检出
    dates2 = pd.date_range("2026-09-01", periods=6, freq="B")
    closes2 = [10, 10.1, 10.2, 10.3, 10.4, 12.1]  # +16% < 20% 不报
    df2 = _px(dates2, closes2, symbol="SPY")
    assert check_price_series(df2, "SPY", jump=JUMP_SPY) == []


def test_price_clean_series():
    dates = pd.date_range("2026-09-01", periods=30, freq="B")
    closes = [10 + i * 0.01 for i in range(30)]
    assert check_price_series(_px(dates, closes), "TQQQ") == []


def test_vix_extreme_and_jump():
    dates = pd.date_range("2026-09-01", periods=30, freq="B")
    closes = [15.0] * 29 + [85.0]          # 极端值 85
    issues = check_vix_series(pd.DataFrame({"date": dates, "close": closes}))
    assert any("极端值" in i for i in issues)
    closes2 = [15.0] * 29 + [20.0]          # +33% 跳空 > 30%
    issues2 = check_vix_series(pd.DataFrame({"date": dates, "close": closes2}))
    assert any("跳空" in i for i in issues2)


def test_sentiment_nan_ratio():
    dates = pd.date_range("2026-09-01", periods=10, freq="B")
    df = pd.DataFrame({"date": dates, "mkt_score": [0.5] * 5 + [None] * 5})
    issues = check_sentiment_series(df)
    assert any("NaN 比例" in i for i in issues)


def test_quality_gate_merge_warn(tmp_path, monkeypatch):
    """异常写 [数据质量] 节；正常时清理旧节，保留停更告警。"""
    from scripts import drift_monitor as dm
    monkeypatch.setattr(dm, "WARN_PATH", Path(tmp_path) / "freshness_warning.txt")
    # 先写入停更告警
    warn = Path(tmp_path) / "freshness_warning.txt"
    warn.write_text("features 尾行滞后 5 交易日\n", encoding="utf-8")
    # 构造有跳空的数据 → quality_gate 追加数据质量节
    dates = pd.date_range("2026-09-01", periods=30, freq="B")
    closes = [10.0] * 29 + [15.0]
    rows = []
    for sym in ["TQQQ", "SOXL", "UPRO", "SPY"]:
        rows.append(pd.DataFrame({"date": dates, "symbol": sym, "open": closes,
                                  "high": closes, "low": closes, "close": closes,
                                  "volume": [1e6] * 30}))
    px = pd.concat(rows, ignore_index=True)
    monkeypatch.setattr(dm, "DATA", tmp_path)
    (tmp_path / "raw").mkdir()
    px.to_csv(tmp_path / "raw" / "prices.csv", index=False)
    pd.DataFrame({"date": dates, "close": closes}).to_csv(
        tmp_path / "raw" / "vix.csv", index=False)
    issues = quality_gate()
    assert issues, "构造数据应检出跳空"
    content = warn.read_text(encoding="utf-8")
    assert "features 尾行滞后" in content          # 停更告警保留
    assert QUALITY_TAG in content                  # 数据质量节存在
    # 正常数据 → 清理数据质量节，保留停更告警
    px_clean = px.copy()
    for sym in ["TQQQ", "SOXL", "UPRO", "SPY"]:
        px_clean.loc[px_clean["symbol"] == sym, "close"] = [10.0 + i * 0.001 for i in range(30)]
    px_clean["open"] = px_clean["high"] = px_clean["low"] = px_clean["close"]
    px_clean.to_csv(tmp_path / "raw" / "prices.csv", index=False)
    pd.DataFrame({"date": dates,
                  "close": [15.0 + i * 0.001 for i in range(30)]}).to_csv(
        tmp_path / "raw" / "vix.csv", index=False)
    issues2 = quality_gate()
    assert issues2 == []
    content2 = warn.read_text(encoding="utf-8")
    assert QUALITY_TAG not in content2
    assert "features 尾行滞后" in content2
