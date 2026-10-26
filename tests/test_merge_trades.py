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


def _splits_df(rows):
    return pd.DataFrame(rows, columns=["symbol", "date", "ratio",
                                       "source", "verified"])


def test_classify_verified1_split_exempt():
    """MT-65：verified=1 邻近 split ⇒ 自动豁免（人工已核实公司行动 ✓）。"""
    splits = _splits_df([
        {"symbol": "AXTX", "date": "2026-10-01", "ratio": 0.24615,
         "source": "manual", "verified": 1},
    ])
    exempt, advisory, pending = mt.classify_miss(
        ["2026-10-01|AXTX|sell"], splits)
    assert "2026-10-01|AXTX|sell" in exempt
    assert advisory == [] and pending == []


def test_classify_verified0_only_advisory_not_exempt():
    """MT-65②：yfinance 未核实(verified=0) ⇒ **只提示**，不静默豁免 ✗、也不当漏单 ✗。"""
    splits = _splits_df([
        {"symbol": "SOXL", "date": "2026-10-01", "ratio": 0.5,
         "source": "yfinance", "verified": 0},
    ])
    exempt, advisory, pending = mt.classify_miss(
        ["2026-10-01|SOXL|sell"], splits)
    assert advisory == ["2026-10-01|SOXL|sell"]
    assert exempt == [] and pending == []


def test_classify_unknown_is_pending():
    """清单无匹配 ⇒ 真疑似漏单 ✗（进入待查，可告警 ✓）。"""
    exempt, advisory, pending = mt.classify_miss(
        ["2026-10-02|ZZZ|sell"], _splits_df([]))
    assert pending == ["2026-10-02|ZZZ|sell"]
    assert exempt == [] and advisory == []


def test_classify_nearby_window():
    """合股日 ±3 工作日内的 miss 也命中邻近 split ✓（不必同日 ✓）。"""
    splits = _splits_df([
        {"symbol": "TQQQ", "date": "2026-09-30", "ratio": 2.0,
         "source": "manual", "verified": 1},
    ])
    exempt, _, _ = mt.classify_miss(["2026-10-01|TQQQ|sell"], splits)
    assert "2026-10-01|TQQQ|sell" in exempt


def test_audit_splits_exempt_vs_pending(monkeypatch, capsys, tmp_path):
    """audit 三类分流：verified=1 豁免 / verified=0 仅提示 / 未知待查告警；
    待查非零 + --alert ⇒ 只对真漏单告警且退出码 1 ✓。"""
    import pandas as pd
    # 写临时三源到 tmp DATA_DIR
    monkeypatch.setattr(mt.config, "DATA_DIR", str(tmp_path))
    (tmp_path / "raw").mkdir()
    # MT-65：公司行动清单（AXTX manual verified=1；SOXL yfinance verified=0 未核实）
    pd.DataFrame([
        {"symbol": "AXTX", "date": "2026-10-01", "ratio": 0.24615,
         "source": "manual", "verified": 1},
        {"symbol": "SOXL", "date": "2026-10-01", "ratio": 0.5,
         "source": "yfinance", "verified": 0},
    ]).to_csv(tmp_path / "raw" / "splits.csv", index=False)
    pd.DataFrame([{"date": "2026-10-01", "symbol": "AAA", "action": "buy",
                  "quantity": 1, "price": 5.0}]).to_csv(
        tmp_path / "trade_log.csv", index=False)
    # 反推：AXTX 已豁免 + SOXL 未核实仅提示 + ZZZ 未知待查
    pd.DataFrame([
        {"date": "2026-10-01", "symbol": "AXTX", "action": "sell",
         "quantity": 147, "price": None},
        {"date": "2026-10-01", "symbol": "SOXL", "action": "sell",
         "quantity": 10, "price": None},
        {"date": "2026-10-02", "symbol": "ZZZ", "action": "sell",
         "quantity": 3, "price": None},
    ]).to_csv(tmp_path / "trade_log_derived.csv", index=False)

    sent = []
    monkeypatch.setattr(
        __import__("scripts.invest_research", fromlist=["push_feishu"]),
        "push_feishu", lambda t: sent.append(t))

    rc = mt.main(["--audit", "--alert"])
    out = capsys.readouterr().out
    assert "已豁免（verified=1" in out and "AXTX" in out
    assert "未核实" in out and "SOXL" in out       # verified=0 仅提示 ✓
    assert "待查 1" in out
    assert "ZZZ|sell" in out
    assert rc == 1                 # 待查非零 ⇒ 退出码 1 ✗
    assert sent and "ZZZ" in sent[0]   # 飞书告警只发真漏单 ✓
    assert "AXTX" not in sent[0] and "SOXL" not in sent[0]  # 公司行动不告警 ✓
