# -*- coding: utf-8 -*-
"""MT-53：OKX SWAP 的 pos 是「张数」，必须乘 ctVal 才是币数。

BTC-USDT-SWAP ctVal=0.01 ⇒ 100 张 = 1 BTC，不是 100 BTC。
"""
import importlib.util
import os
import sys

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "sync_positions.py")


def _load(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sync_positions.py"])
    spec = importlib.util.spec_from_file_location("sync_positions_mt53", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_swap_qty_times_ctval(monkeypatch, tmp_path):
    """100 张 × ctVal=0.01 = 1 BTC（不是 100 BTC）。"""
    mod = _load(monkeypatch)

    # mock 凭据 + API
    monkeypatch.setattr(mod, "_okx_creds", lambda: {"api_key": "k", "secret": "s",
                                                     "passphrase": "p"})
    def fake_request(creds, path):
        if "/account/balance" in path:
            return {"code": "0", "data": [{"totalEq": "10000.0", "cash": "100"}]}
        if "/account/positions" in path:
            return {"code": "0", "data": [{
                "instId": "BTC-USDT-SWAP",
                "instType": "SWAP",
                "pos": "100",           # 100 张
                "ctVal": "0.01",        # 每张 0.01 BTC
                "avgPx": "60000",
                "markPx": "65000",
                "notionalUsd": "6500",
            }]}
        return {"code": "-1", "msg": "unknown"}
    monkeypatch.setattr(mod, "_okx_request", fake_request)

    accounts = pd.DataFrame(columns=["date", "account", "net_value", "pnl", "cash",
                                     "market_value", "unrealized_pnl", "currency", "note"])
    positions = pd.DataFrame(columns=["date", "account", "symbol", "name", "qty", "price",
                                       "cost", "market_value", "notional", "margin",
                                       "bucket", "currency"])
    acc, pos = mod.sync_okx(accounts, positions, "2026-10-21")
    row = pos.iloc[0]
    assert row["symbol"] == "BTC-USDT-SWAP"
    assert row["qty"] == pytest.approx(1.0, abs=1e-6)   # 100 × 0.01 = 1 BTC
    assert row["notional"] == pytest.approx(6500.0, abs=0.1)
    assert "张" in row["name"] or "ctVal" in row["name"]


def test_spot_no_ctval(monkeypatch, tmp_path):
    """现货 instType=MARGIN/SPOT，无 ctVal 或 ctVal=0 ⇒ qty 直接用 pos。"""
    mod = _load(monkeypatch)
    monkeypatch.setattr(mod, "_okx_creds", lambda: {"api_key": "k", "secret": "s",
                                                     "passphrase": "p"})
    def fake_request(creds, path):
        if "/account/balance" in path:
            return {"code": "0", "data": [{"totalEq": "10000.0", "cash": "100"}]}
        if "/account/positions" in path:
            return {"code": "0", "data": [{
                "instId": "BTC-USDT",
                "instType": "MARGIN",
                "pos": "0.029976",      # 现货就是币数
                "avgPx": "60000",
                "markPx": "65000",
                "notionalUsd": "1948",
            }]}
        return {"code": "-1", "msg": "unknown"}
    monkeypatch.setattr(mod, "_okx_request", fake_request)
    accounts = pd.DataFrame(columns=["date", "account", "net_value", "pnl", "cash",
                                     "market_value", "unrealized_pnl", "currency", "note"])
    positions = pd.DataFrame(columns=["date", "account", "symbol", "name", "qty", "price",
                                       "cost", "market_value", "notional", "margin",
                                       "bucket", "currency"])
    acc, pos = mod.sync_okx(accounts, positions, "2026-10-21")
    row = pos.iloc[0]
    assert row["qty"] == pytest.approx(0.029976, abs=1e-6)
