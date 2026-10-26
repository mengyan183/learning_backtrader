# -*- coding: utf-8 -*-
"""`fg_system/data/asset_type.py` + 期权分流的测试 ✓。

背景：`trade_log` 混了 17 笔期权 ✗ ⇒ 期权 **1 张 = 100 股** ✗
⇒ `qty×(price−cost)` 会**低估 100 倍**且**不报错** ✗（2026-10-26）。
"""
import importlib.util
import os

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


at = _load("fg_system/data/asset_type.py", "asset_type")
dv = _load("fg_system/data/derived.py", "derived")
mt = _load("scripts/merge_trades.py", "merge_trades")


# ------------------------------------------------------------------ classify
@pytest.mark.parametrize("sym,expect", [
    ("US.AAPL250117C150000", "option"),      # 富途期权：YYMMDD + C + 行权价 ✓
    ("US.TSLA250620P00250000", "option"),
    ("AAPL", "stock"),
    ("TQQQ", "stock"),
    ("BTC-USDT", "stock"),
    ("", "stock"),
    (None, "stock"),
])
def test_classify(sym, expect):
    assert at.classify(sym) == expect


def test_is_option():
    assert at.is_option("US.AAPL250117C150000") is True
    assert at.is_option("SOXL") is False


def test_classify_df_without_symbol_column():
    """没有 symbol 列 ⇒ 全判 stock ✓，**不报错** ✗。"""
    df = pd.DataFrame({"a": [1, 2]})
    out = at.classify_df(df)
    assert list(out["asset_type"]) == ["stock", "stock"]


def test_classify_df_does_not_mutate_input():
    df = pd.DataFrame({"symbol": ["AAPL", "US.AAPL250117C150000"]})
    out = at.classify_df(df)
    assert "asset_type" not in df.columns          # 入参未被改 ✓
    assert list(out["asset_type"]) == ["stock", "option"]


# ------------------------------------------------------------------ derived
def test_unrealized_skips_options_with_nan():
    """🔴 期权必须置 `NaN` ✗ —— 否则低估 100 倍 ✗。"""
    pos = pd.DataFrame({
        "date": ["2026-10-01", "2026-10-01"],
        "symbol": ["AAPL", "US.AAPL250117C150000"],
        "qty": [10.0, 2.0],
        "price": [110.0, 5.0],
        "cost": [100.0, 4.0],
    })
    out = dv.unrealized(pos)
    assert out.loc[0, "unrealized"] == pytest.approx(100.0)   # 10×(110−100) ✓
    assert pd.isna(out.loc[1, "unrealized"])                   # 期权被跳过 ✓


def test_unrealized_stock_only_unchanged():
    """全股票时行为与原来**完全一致** ✓（无回归 ✓）。"""
    pos = pd.DataFrame({
        "date": ["2026-10-01"], "symbol": ["SOXL"],
        "qty": [100.0], "price": [40.0], "cost": [50.0],
    })
    assert dv.unrealized(pos).loc[0, "unrealized"] == pytest.approx(-1000.0)


# ------------------------------------------------------------------ merge
def test_norm_adds_asset_type_column():
    """合并视图必须带 `asset_type` ✓，下游才能分流 ✓。"""
    df = pd.DataFrame({
        "date": ["2026-10-01", "2026-10-02"],
        "symbol": ["aapl", "US.AAPL250117C150000"],
        "action": ["BUY", "SELL_SHORT"],
        "quantity": [1, 2],
        "price": [10.0, 3.0],
    })
    out = mt._norm(df, "manual")
    assert "asset_type" in out.columns
    assert list(out["asset_type"]) == ["stock", "option"]
    assert list(out["source"]) == ["manual", "manual"]
