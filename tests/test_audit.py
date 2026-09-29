# -*- coding: utf-8 -*-
"""违规审计测试（§13.2）。"""
import pandas as pd
import pytest

from fg_system import audit


def _log(rows):
    return pd.DataFrame(rows, columns=["date", "symbol", "action", "quantity", "price", "reason"])


def _features(rows):
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def test_compliant_trade_marked_ok():
    log = _log([["2024-01-10", "TQQQ", "buy", 100, 50.0, "signal"]])
    feats = _features([{"date": "2024-01-10", "target_position": 0.70,
                        "circuit_breaker": False}])
    out = audit.audit(log, feats)
    assert out.iloc[0]["verdict"] == "合规"


def test_reverse_trade_flagged():
    """指令要求减仓，实际买入 → 逆向违规。"""
    log = _log([
        ["2024-01-10", "TQQQ", "sell", 100, 50.0, "signal"],
        ["2024-01-11", "TQQQ", "buy", 100, 50.0, "manual"],
    ])
    feats = _features([
        {"date": "2024-01-10", "target_position": 0.20, "circuit_breaker": False},
        {"date": "2024-01-11", "target_position": 0.20, "circuit_breaker": False},
    ])
    out = audit.audit(log, feats)
    assert "违规" in out.iloc[-1]["verdict"]


def test_trade_on_non_operable_day_flagged():
    """熔断期买入 → 违规。"""
    log = _log([["2024-01-10", "TQQQ", "buy", 100, 50.0, "manual"]])
    feats = _features([{"date": "2024-01-10", "target_position": 0.25,
                        "circuit_breaker": True}])
    out = audit.audit(log, feats)
    assert "违规" in out.iloc[0]["verdict"]


def test_overadjust_trade_flagged():
    """单笔金额超过组合总值 30% → 超幅违规（§13.2 第五类）。"""
    log = _log([["2024-01-10", "TQQQ", "buy", 5000, 100.0, "signal"]])   # 50 万 / 100 万
    feats = _features([{"date": "2024-01-10", "target_position": 0.70,
                        "circuit_breaker": False}])
    out = audit.audit(log, feats, portfolio_value=1_000_000.0)
    assert "超幅" in out.iloc[0]["verdict"]


def test_normal_size_trade_not_flagged_as_overadjust():
    log = _log([["2024-01-10", "TQQQ", "buy", 1000, 100.0, "signal"]])    # 10 万 / 100 万
    feats = _features([{"date": "2024-01-10", "target_position": 0.70,
                        "circuit_breaker": False}])
    out = audit.audit(log, feats, portfolio_value=1_000_000.0)
    assert out.iloc[0]["verdict"] == "合规"


def test_violation_rate_computed():
    log = _log([
        ["2024-01-10", "TQQQ", "buy", 100, 50.0, "signal"],
        ["2024-01-11", "TQQQ", "buy", 100, 50.0, "manual"],
    ])
    feats = _features([
        {"date": "2024-01-10", "target_position": 0.70, "circuit_breaker": False},
        {"date": "2024-01-11", "target_position": 0.70, "circuit_breaker": False},
    ])
    out = audit.audit(log, feats)
    assert 0.0 <= audit.violation_rate(out) <= 1.0


def test_unknown_date_trade_is_flagged():
    """交易日不在 features 索引中 → 无指令操作。"""
    log = _log([["2024-03-15", "TQQQ", "buy", 100, 50.0, "signal"]])
    feats = _features([{"date": "2024-01-10", "target_position": 0.70,
                        "circuit_breaker": False}])
    out = audit.audit(log, feats)
    assert "违规" in out.iloc[0]["verdict"]
