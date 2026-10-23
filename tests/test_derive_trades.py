# -*- coding: utf-8 -*-
"""`scripts/derive_trades.py` —— 从持仓快照反推成交流水。

背景（2026-10-23 实测 ✗）：`trade_log.csv` 26 笔**全是 buy** ✓、`sell` 记录 **0** ✗，
但 `DPST`/`RKLX`/`SOXL`/`TQQQ` **买过却不在持仓** ✗ ⇒ **卖过但没记** ✗
⇒ 卖出的理由/比例/`fg_index` **全丢** ✗ ⇒ 没有可复盘素材 ✗。
"""
import importlib.util
import os
import sys

import pandas as pd
import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "derive_trades", os.path.join(_HERE, "scripts", "derive_trades.py"))
dt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dt)


def _pos(rows):
    return pd.DataFrame(rows)


def test_first_day_is_baseline_not_trade():
    """🔴 **首日只作基准** ✗ —— 否则单日快照会产出**假成交** ✗（2026-10-23 实测 ✓）。"""
    pos = _pos([
        {"date": "2026-10-01", "symbol": "AAA", "qty": 100, "price": 10.0},
    ])
    out = dt.derive(pos)
    assert out.empty, "单日快照不得产出任何成交 ✗"


def test_increase_is_buy_and_decrease_is_sell():
    """qty 增 ⇒ buy ✓；减 ⇒ sell ✓。"""
    pos = _pos([
        {"date": "2026-10-01", "symbol": "AAA", "qty": 100, "price": 10.0},
        {"date": "2026-10-02", "symbol": "AAA", "qty": 150, "price": 11.0},
        {"date": "2026-10-03", "symbol": "AAA", "qty": 50, "price": 12.0},
    ])
    out = dt.derive(pos)
    assert len(out) == 2
    assert out.iloc[0]["action"] == "buy" and out.iloc[0]["quantity"] == 50
    assert out.iloc[1]["action"] == "sell" and out.iloc[1]["quantity"] == 100


def test_vanished_symbol_is_full_sell():
    """清仓后标的**从快照消失** ✗ ⇒ 必须反推出**全量卖出** ✗（这是最易漏的一种 ✓）。"""
    pos = _pos([
        {"date": "2026-10-01", "symbol": "AAA", "qty": 100, "price": 10.0},
        {"date": "2026-10-02", "symbol": "BBB", "qty": 1, "price": 1.0},
    ])
    out = dt.derive(pos)
    sells = out[out["action"] == "sell"]
    assert len(sells) == 1
    assert sells.iloc[0]["symbol"] == "AAA"
    assert sells.iloc[0]["quantity"] == 100


def test_audit_flags_unlogged_trade():
    """对账必须抓出「有成交但没记录」✗。"""
    pos = _pos([
        {"date": "2026-10-01", "symbol": "AAA", "qty": 100, "price": 10.0},
        {"date": "2026-10-02", "symbol": "AAA", "qty": 200, "price": 10.0},
    ])
    dr = dt.derive(pos)
    logged = pd.DataFrame(columns=["date", "symbol", "action", "quantity"])
    unlogged, _ = dt.audit(dr, logged)
    assert len(unlogged) == 1
    assert unlogged.iloc[0]["action"] == "buy"


def test_audit_matches_when_logged():
    """记录一致时**不得**报不一致 ✗。"""
    pos = _pos([
        {"date": "2026-10-01", "symbol": "AAA", "qty": 100, "price": 10.0},
        {"date": "2026-10-02", "symbol": "AAA", "qty": 50, "price": 10.0},
    ])
    dr = dt.derive(pos)
    logged = pd.DataFrame([{"date": "2026-10-02", "symbol": "AAA",
                            "action": "sell", "quantity": 50}])
    unlogged, unmatched = dt.audit(dr, logged)
    assert unlogged.empty and unmatched.empty


def test_missing_column_raises():
    """缺列 ⇒ 明确抛错 ✗（不静默给 0 ✗）。"""
    with pytest.raises(ValueError):
        dt.derive(pd.DataFrame([{"date": "2026-10-01", "symbol": "A"}]))
