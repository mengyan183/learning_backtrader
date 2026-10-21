# -*- coding: utf-8 -*-
"""`fg_system/data/derived.py` —— 从未实现盈亏自算（不读 API 字段 ✓）。

背景（2026-10-21 ✗）：11 条假说依赖浮亏 ✗，但 `accounts.csv` 的 `unrealized_pnl`
来自富途 `unrealized_pl` ✗ —— 部分 FutuOpenD 版本**没有该字段** ⇒ 静默写 0.0 ✗。
而 `positions.csv` 有 `qty/price/cost` ✓ ⇒ 可完全自算 ✓。
"""
import pandas as pd
import pytest

from fg_system.data import derived


def _pos():
    return pd.DataFrame([
        {"date": "2026-10-20", "symbol": "AXTX", "qty": 195.0,
         "price": 9.41, "cost": 21.923},
        {"date": "2026-10-20", "symbol": "GDXU", "qty": 42.0,
         "price": 133.06, "cost": 111.19},
        {"date": "2026-10-19", "symbol": "AXTX", "qty": 195.0,
         "price": 10.0, "cost": 21.923},
    ])


def test_unrealized_formula():
    """`unrealized = qty × (price − cost)` ✓ —— 必须断言**具体数值** ✗（不能只断言不报错 ✗）。"""
    d = derived.unrealized(_pos())
    row = d[(d["symbol"] == "GDXU") & (d["date"] == "2026-10-20")].iloc[0]
    assert row["unrealized"] == pytest.approx(42.0 * (133.06 - 111.19), abs=0.01)


def test_unrealized_does_not_mutate_input():
    """不得修改入参 ✓（派生函数要可重入 ✓）。"""
    pos = _pos()
    before = pos.columns.tolist()
    derived.unrealized(pos)
    assert pos.columns.tolist() == before


def test_by_symbol_picks_last_date_by_default():
    """`by_symbol()` 默认取**最后一日** ✓（不能混入历史日 ✗）。"""
    out = derived.by_symbol(_pos())
    assert set(out["date"]) == {"2026-10-20"}
    assert len(out) == 2


def test_daily_sums_per_date():
    """逐日汇总 ✓ —— 合计必须等于逐标的之和 ✗。"""
    out = derived.daily(_pos())
    assert len(out) == 2
    d20 = out[out["date"] == "2026-10-20"].iloc[0]
    expect = 195.0 * (9.41 - 21.923) + 42.0 * (133.06 - 111.19)
    assert d20["unrealized"] == pytest.approx(round(expect, 2), abs=0.01)
    assert d20["n_symbols"] == 2


def test_missing_column_raises():
    """缺列 ⇒ 必须**明确抛错** ✗（不能静默给 0 ✗）。"""
    bad = _pos().drop(columns=["cost"])
    with pytest.raises(ValueError):
        derived.unrealized(bad)


def test_audit_flags_mismatch():
    """审计必须**抓出**不一致 ✗ —— 2026-10-21 实测 `accounts` 报 −1052.63 vs 自算 −1033.41 ✗。"""
    pos = pd.DataFrame([
        {"date": "2026-10-20", "symbol": "X", "qty": 1.0,
         "price": 10.0, "cost": 20.0},
    ])
    acc = pd.DataFrame([{"date": "2026-10-20", "unrealized_pnl": 0.0}])
    out = derived.audit_accounts(acc, pos)
    assert len(out) == 1
    assert out.iloc[0]["ok"] is False or not out.iloc[0]["ok"]
    assert out.iloc[0]["diff"] == pytest.approx(10.0, abs=0.01)
