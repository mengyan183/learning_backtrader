# -*- coding: utf-8 -*-
"""`scripts/query_symbol_fg.py`（按标的查系统贪恐系数）。

核心断言：**来源必须可辨** ✗ ——
- 已登记 + 底层够 ⇒ `个股` ✓
- 已登记 + 底层不足 ⇒ `大盘回退` ✓ + 说明原因 ✓
- **未登记** ⇒ **不给分数** ✗（否则等于把大盘分冒充个股分 ✗）
"""
import importlib.util
import json
import os

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "query_symbol_fg.py")


def _load():
    spec = importlib.util.spec_from_file_location("query_symbol_fg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


q = _load()


@pytest.fixture
def prices():
    """只给 `AXTI` 900 行 ⇒ AXTX 够 ✓；CONL 的 `COIN` 缺 ✗。"""
    dates = pd.date_range("2022-01-03", periods=900, freq="B")
    return pd.DataFrame({"symbol": "AXTI", "date": dates,
                         "close": pd.Series(range(100, 1000), dtype=float).values})


@pytest.fixture
def market(tmp_path, monkeypatch):
    """给市场级 fg_index（回退用）✓。"""
    p = tmp_path / "features.csv"
    pd.DataFrame({"date": ["2026-10-16"], "fg_index": [62.0]}).to_csv(p, index=False)
    monkeypatch.setattr(q.config, "DATA_DIR", str(tmp_path))
    return 62.0


def test_registered_with_data_is_per_symbol(prices, market):
    r = q.query("AXTX", prices=prices)
    assert r["source"] == "个股"
    assert r["value"] is not None and 0 <= r["value"] <= 100
    assert r["error"] is None


def test_registered_but_short_history_falls_back(prices, market):
    """CONL 底层 COIN 缺 ⇒ 回退大盘，但**必须标注** ✓ 且说明原因 ✓。"""
    r = q.query("CONL", prices=prices)
    assert r["source"] == "大盘回退"
    assert r["value"] == market
    assert "回退" in (r["error"] or "")


def test_unregistered_symbol_gets_no_score(prices, market):
    """NVDA 未登记 ⇒ **不得给分数** ✗（给了就是把大盘分冒充个股分 ✗）。"""
    r = q.query("NVDA", prices=prices)
    assert r["value"] is None
    assert r["source"] is None
    assert "未在" in (r["error"] or "")


def test_cli_json_output(prices, market, tmp_path, monkeypatch, capsys):
    """`--json` 可被程序消费 ✓；含 `source` 字段 ✓。"""
    monkeypatch.setattr(q, "main", q.main)      # 保持原样，仅确认可调用
    rc = q.main(["--json", "AXTX"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[0]["symbol"] == "AXTX"
    assert data[0]["source"] in ("个股", "大盘回退")
    assert rc == 0


def test_cli_returns_one_when_any_symbol_unresolved(prices, market):
    """有标的分不出 ⇒ 退出码 1 ✓（便于脚本判断 ✗）。"""
    assert q.main(["NVDA"]) == 1
