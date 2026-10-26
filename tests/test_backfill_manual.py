# -*- coding: utf-8 -*-
"""`scripts/backfill_manual.py` —— 富途流水幂等回填手工账本（MT-72④）。

口径（用户拍板 2A：全量含期权回填、期权纳入账本 ✓）：
- futu 有、manual 无的 key（date|SYMBOL|action）⇒ reason=backfill 逐笔追加 ✓
- manual 已有 key 跳过（幂等 ✓）；manual 独有（OKX/BTC 系）保留不动 ✓
- 不覆盖、不聚合分批 ✓；默认 dry-run，--write 才落盘 ✓
"""
import importlib.util
import os

import pandas as pd

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "backfill_manual", os.path.join(_HERE, "scripts", "backfill_manual.py"))
bm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bm)


def _futu(rows):
    return pd.DataFrame(rows)


def _manual(rows):
    return pd.DataFrame(rows)


def test_plan_only_missing_keys_reason_backfill():
    """futu 有、manual 无 ⇒ 入选，reason=backfill，列对齐 MANUAL_COLS ✓。"""
    futu = _futu([
        {"date": "2025-01-27", "account": "a", "symbol": "SOXL",
         "action": "buy", "quantity": 40.0, "price": 25.0, "fee": ""},
        {"date": "2025-04-03", "account": "a", "symbol": "TMF250516P41000",
         "action": "buy_back", "quantity": 1.0, "price": 0.7, "fee": ""},
    ])
    manual = _manual([
        {"date": "2026-06-04", "symbol": "BTC", "action": "buy",
         "quantity": 0.015, "price": 60000, "reason": "manual"},
    ])
    add = bm.plan(futu, manual)
    assert len(add) == 2
    assert set(add["reason"]) == {"backfill"}
    # 列对齐，不带 account/fee ✓
    assert list(add.columns) == bm.MANUAL_COLS
    # 期权 action 保留 ✓
    assert "TMF250516P41000" in set(add["symbol"])


def test_idempotent_when_key_already_in_manual():
    """manual 已含同 key ⇒ 待回填 0（重复跑不重复写 ✓）。"""
    futu = _futu([{"date": "2025-01-27", "symbol": "SOXL", "action": "buy",
                   "quantity": 40.0, "price": 25.0}])
    manual = _manual([{"date": "2025-01-27", "symbol": "soxl",
                       "action": "BUY", "quantity": 99, "price": 1.0,
                       "reason": "manual"}])
    assert bm.plan(futu, manual).empty


def test_manual_private_rows_preserved_on_write(monkeypatch, tmp_path):
    """--write 落盘：manual 独有行（BTC 系）保留，回填行追加，不覆盖 ✓。"""
    (tmp_path / "trade_log_futu.csv").write_text(
        "date,account,symbol,action,quantity,price,fee\n"
        "2025-01-27,a,SOXL,buy,40.0,25.0,\n", encoding="utf-8")
    (tmp_path / "trade_log.csv").write_text(
        "date,symbol,action,quantity,price,reason\n"
        "2026-10-01,BTC,sell,0.0299,,reconstructed\n", encoding="utf-8")
    monkeypatch.setattr(bm.config, "DATA_DIR", str(tmp_path))

    rc = bm.main(["--write"])
    assert rc == 0
    out = pd.read_csv(tmp_path / "trade_log.csv", dtype=str)
    # 原 BTC 行仍在 ✓
    assert ((out["symbol"] == "BTC") & (out["action"] == "sell")).any()
    # 回填的 SOXL 行追加进来 ✓
    assert ((out["symbol"] == "SOXL") & (out["reason"] == "backfill")).any()
