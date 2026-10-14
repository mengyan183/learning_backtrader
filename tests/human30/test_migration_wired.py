# tests/human30/test_migration_wired.py
# -*- coding: utf-8 -*-
"""守卫 10b：读取链必须自动懒迁移（旧记录读出来就带 levels/phases）。"""
import pytest

from fg_system.human30 import store


@pytest.fixture
def data_path(tmp_path, monkeypatch):
    p = tmp_path / "human30.json"
    monkeypatch.setattr(store, "DATA_PATH", str(p))
    return p


def test_latest_migrates_old_record(data_path):
    """旧记录（无 levels/phases）经 latest() 读出时必须已被迁移。"""
    store._save({"records": [{"date": "2026-10-01", "mind": 75.0, "body": 55.0,
                              "spirit": 35.0, "vocation": 50.0}]})
    rec = store.latest()
    assert rec["levels"] == {"mind": 3, "body": 2, "spirit": 1, "vocation": 2}
    assert set(rec["phases"].values()) == {"unknown"}


def test_history_migrates_all_records(data_path):
    store._save({"records": [
        {"date": "2026-10-01", "mind": 75.0, "body": 55.0, "spirit": 35.0, "vocation": 50.0},
        {"date": "2026-10-02", "mind": 45.0, "body": 45.0, "spirit": 45.0, "vocation": 45.0},
    ]})
    recs = store.history(10)
    assert len(recs) == 2
    assert recs[0]["levels"]["mind"] == 3
    assert recs[1]["levels"]["mind"] == 2


def test_migration_on_read_does_not_write(data_path, monkeypatch):
    """读取链的懒迁移**不得写盘**（用 _save 探针，触发即红）。"""
    store._save({"records": [{"date": "2026-10-01", "mind": 75.0, "body": 55.0,
                              "spirit": 35.0, "vocation": 50.0}]})
    before = data_path.read_text(encoding="utf-8")

    def _boom(*a, **kw):
        raise AssertionError("读取链不得写盘")

    monkeypatch.setattr(store, "_save", _boom)
    assert store.latest()["levels"]["mind"] == 3
    assert store.history(5)[0]["levels"]["mind"] == 3

    assert data_path.read_text(encoding="utf-8") == before
