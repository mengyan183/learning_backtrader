# -*- coding: utf-8 -*-
"""`scripts/merge_trades.py` —— 三源合并（原始表**只读** ✗）。

用户 2026-10-26 拍板 ✓：
- `futu`（券商 ✓）**权威** ✓ > `manual`（手工 ✓）> `derived`（反推 ✗ **仅对账** ✗）
"""
import importlib.util
import os

import pandas as pd

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "merge_trades", os.path.join(_HERE, "scripts", "merge_trades.py"))
mt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mt)


def test_futu_wins_over_manual():
    """同一 (date,symbol,action) ⇒ **futu 覆盖 manual** ✗。"""
    futu = pd.DataFrame([{"date": "2026-10-01", "symbol": "AAA",
                          "action": "buy", "quantity": 10, "price": 5.0}])
    manual = pd.DataFrame([{"date": "2026-10-01", "symbol": "AAA",
                            "action": "buy", "quantity": 999, "price": 1.0}])
    out = mt.merge(futu, manual)
    assert len(out) == 1
    assert out.iloc[0]["source"] == "futu"
    assert out.iloc[0]["quantity"] == 10


def test_same_source_same_key_sums_quantity():
    """🔴 同源同 key ⇒ **数量求和** ✗（2026-10-26 实测：原实现去重 ⇒ 26 变 22 且**数量丢失** ✗）。"""
    manual = pd.DataFrame([
        {"date": "2026-10-01", "symbol": "AAA", "action": "buy",
         "quantity": 10, "price": 5.0},
        {"date": "2026-10-01", "symbol": "AAA", "action": "buy",
         "quantity": 20, "price": 7.0},
    ])
    out = mt.merge(None, manual)
    assert len(out) == 1
    assert out.iloc[0]["quantity"] == 30          # 10 + 20 ✓
    assert abs(out.iloc[0]["price"] - (10 * 5 + 20 * 7) / 30) < 1e-6  # 加权均价 ✓


def test_manual_used_when_futu_missing():
    """futu 缺失 ⇒ 用 manual ✓ 且**不报错** ✗。"""
    manual = pd.DataFrame([{"date": "2026-10-01", "symbol": "AAA",
                            "action": "sell", "quantity": 1, "price": 2.0}])
    out = mt.merge(None, manual)
    assert len(out) == 1 and out.iloc[0]["source"] == "manual"


def test_empty_inputs():
    """两源都空 ⇒ 空表 ✓（不抛错 ✗）。"""
    out = mt.merge(None, None)
    assert out.empty and list(out.columns) == mt.COLUMNS


def test_corp_action_exempt_listed():
    """AXTX 2026-09 合股（用户证实 ✓）必须在公司行动豁免表里 ✓。"""
    assert "2026-10-01|AXTX|sell" in mt.CORP_ACTION_EXEMPT


def test_audit_splits_exempt_vs_pending(monkeypatch, capsys, tmp_path):
    """audit 把「已知公司行动」与「待查漏单」分开；待查非零 + --alert ⇒ 告警且退出码 1 ✓。"""
    import pandas as pd
    # 写临时三源到 tmp DATA_DIR
    import os
    monkeypatch.setattr(mt.config, "DATA_DIR", str(tmp_path))
    pd.DataFrame([{"date": "2026-10-01", "symbol": "AAA", "action": "buy",
                  "quantity": 1, "price": 5.0}]).to_csv(
        tmp_path / "trade_log.csv", index=False)
    # 反推：一笔已豁免（AXTX 合股）+ 一笔未知待查（ZZZ sell）
    pd.DataFrame([
        {"date": "2026-10-01", "symbol": "AXTX", "action": "sell",
         "quantity": 147, "price": None},
        {"date": "2026-10-02", "symbol": "ZZZ", "action": "sell",
         "quantity": 3, "price": None},
    ]).to_csv(tmp_path / "trade_log_derived.csv", index=False)

    sent = []
    monkeypatch.setattr(
        __import__("scripts.invest_research", fromlist=["push_feishu"]),
        "push_feishu", lambda t: sent.append(t))

    rc = mt.main(["--audit", "--alert"])
    out = capsys.readouterr().out
    assert "已豁免（公司行动" in out
    assert "待查 1" in out
    assert "ZZZ|sell" in out
    assert rc == 1                 # 待查非零 ⇒ 退出码 1 ✗
    assert sent and "ZZZ" in sent[0]   # 飞书告警已发 ✓
