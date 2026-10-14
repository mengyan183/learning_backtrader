# tests/human30/test_lazy_migration.py
# -*- coding: utf-8 -*-
"""守卫 10：懒迁移必须无损（旧字段一个不丢；相位一律 unknown；不重写文件）。"""
import pytest

from fg_system.human30 import store


@pytest.fixture
def data_path(tmp_path, monkeypatch):
    p = tmp_path / "human30.json"
    monkeypatch.setattr(store, "DATA_PATH", str(p))
    return p


def test_bucket_mapping_thresholds():
    assert store.bucket_level(71) == 3
    assert store.bucket_level(70) == 2      # <=70 为 L2（沿用 v1 阈值）
    assert store.bucket_level(40) == 2
    assert store.bucket_level(39) == 1


def test_migrate_record_adds_levels_and_unknown_phases():
    old = {"date": "2026-10-01", "mind": 75.0, "body": 55.0,
           "spirit": 35.0, "vocation": 50.0, "note": "旧", "market": {"zone": 2}}
    m = store.migrate_record(old)
    assert m["levels"] == {"mind": 3, "body": 2, "spirit": 1, "vocation": 2}
    assert set(m["phases"].values()) == {"unknown"}
    for k in ("date", "mind", "body", "spirit", "vocation", "note", "market"):
        assert m[k] == old[k]


def test_migration_does_not_rewrite_file(data_path, monkeypatch):
    """懒迁移只在读取时进行 ⇒ 读取路径不得触发任何写盘。

    做法：把 _save 换成"一调用就抛错"的探针 —— 若读取路径真的写了盘，本测试必红。
    """
    store._save({"records": [{"date": "2026-10-01", "mind": 75.0, "body": 55.0,
                              "spirit": 35.0, "vocation": 50.0}]})
    before = data_path.read_text(encoding="utf-8")

    def _boom(*a, **kw):
        raise AssertionError("读取路径不得写盘（触发了 _save）")

    monkeypatch.setattr(store, "_save", _boom)
    recs = store.history(10)
    assert recs and recs[0]["mind"] == 75.0
    assert store.migrate_record(recs[0])["levels"]["mind"] == 3

    assert data_path.read_text(encoding="utf-8") == before


def test_migrate_is_idempotent():
    old = {"date": "2026-10-01", "mind": 75.0, "body": 55.0,
           "spirit": 35.0, "vocation": 50.0}
    assert store.migrate_record(old) == store.migrate_record(store.migrate_record(old))
