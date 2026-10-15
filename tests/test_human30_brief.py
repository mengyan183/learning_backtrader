# -*- coding: utf-8 -*-
"""P5：简报 Human 3.0 节 —— 无分数数字 / 无交易动词 / 不崩。"""
import re

import pytest

from fg_system.human30 import store

VERBS = ["减仓", "加仓", "买入", "卖出", "仓位", "止损", "清仓", "抄底", "杠杆"]


@pytest.fixture
def data_path(tmp_path, monkeypatch):
    p = tmp_path / "human30.json"
    monkeypatch.setattr(store, "DATA_PATH", str(p))
    return p


def _brief():
    import sys
    sys.path.insert(0, "scripts")
    from invest_research import _human30_brief
    return _human30_brief()


def test_no_records_returns_none(data_path):
    assert _brief() is None


def test_with_record_no_score_digits(data_path):
    """§7.1：**非 🟡 部分**禁分数与 Level 数字 ✗。

    🟡 AI 复盘段（前缀 `AI 复盘（🟡`）是**明标的研究参考** ✓，
    与看板 🟡 块同性质 ⇒ 不计入本判据 ✓。
    """
    store._save({"records": [{
        "date": "2026-10-15", "mind": 70.0, "body": 60.0,
        "spirit": 40.0, "vocation": 65.0, "note": "",
    }]})
    t = _brief()
    assert t
    head = t.split("AI 复盘（🟡")[0]          # 只查 🟡 之前的部分 ✓
    assert not re.search(r"\bL[123]\b", head)
    assert not re.search(r"\d+\.\d+", head)
    assert "均分" not in head
    for v in VERBS:
        assert v not in head
