# tests/human30/test_store_safety.py
# -*- coding: utf-8 -*-
"""store 数据安全守卫（继承 v1 的 S-2 修复，不得回退）。"""
import json
import os

import pytest

from fg_system.human30 import store


@pytest.fixture
def data_path(tmp_path, monkeypatch):
    p = tmp_path / "human30.json"
    monkeypatch.setattr(store, "DATA_PATH", str(p))
    return p


def test_missing_file_returns_empty_history(data_path):
    assert store._load() == {"records": []}


def test_corrupt_file_raises_instead_of_silent_empty(data_path):
    data_path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="损坏"):
        store._load()


def test_corrupt_file_is_not_overwritten_by_record(data_path):
    data_path.write_text("{ broken", encoding="utf-8")
    before = data_path.read_text(encoding="utf-8")
    with pytest.raises(RuntimeError):
        store.record(70, 70, 70, 70)
    assert data_path.read_text(encoding="utf-8") == before, "损坏文件被覆盖 ⇒ 数据不可逆丢失"


def test_save_is_atomic_and_leaves_no_tmp(data_path):
    store._save({"records": [{"date": "2026-10-12", "mind": 70.0}]})
    assert not os.path.exists(str(data_path) + ".tmp")
    assert json.loads(data_path.read_text(encoding="utf-8"))["records"][0]["mind"] == 70.0
