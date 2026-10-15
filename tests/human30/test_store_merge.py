# tests/human30/test_store_merge.py
# -*- coding: utf-8 -*-
"""C-3 守卫：同日二次打卡不得丢字段；未知字段必须保留；畸形记录不得崩。"""
import pytest

from fg_system.human30 import store


@pytest.fixture
def data_path(tmp_path, monkeypatch):
    p = tmp_path / "human30.json"
    monkeypatch.setattr(store, "DATA_PATH", str(p))
    return p


def test_same_day_second_record_keeps_v2_fields(data_path):
    """先写带 v2 字段的记录，再同日打卡 ⇒ v2 字段不得被抹掉。"""
    store._save({"records": [{
        "date": "2026-10-14", "mind": 60.0, "body": 60.0,
        "spirit": 60.0, "vocation": 60.0, "note": "旧",
        "schema": 2, "levels": {"mind": 2}, "phases": {"mind": "dissonance"},
    }]})
    store.record(70, 70, 70, 70, note="新", when="2026-10-14")
    rec = store.latest()
    assert rec["mind"] == 70.0 and rec["note"] == "新"
    assert rec["schema"] == 2
    assert rec["levels"] == {"mind": 2}
    assert rec["phases"] == {"mind": "dissonance"}


def test_other_days_untouched(data_path):
    """写新一天不得改动其它天记录的字段。"""
    store._save({"records": [
        {"date": "2026-10-01", "mind": 1.0, "body": 1.0, "spirit": 1.0,
         "vocation": 1.0, "note": "a", "extra": "keep-me"},
    ]})
    store.record(50, 50, 50, 50, when="2026-10-02")
    recs = store._load()["records"]
    assert recs[0]["extra"] == "keep-me"
    assert recs[0]["note"] == "a"
    assert len(recs) == 2


def test_malformed_record_without_date_does_not_crash(data_path):
    """畸形记录（缺 date）不得让 record() 崩。"""
    store._save({"records": [{"mind": 50.0, "body": 50.0,
                              "spirit": 50.0, "vocation": 50.0}]})
    store.record(60, 60, 60, 60, when="2026-10-03")
    assert len(store._load()["records"]) == 2
