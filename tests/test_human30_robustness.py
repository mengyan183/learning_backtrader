# -*- coding: utf-8 -*-
"""S-2 守卫：human30 数据文件**损坏不得被当成空历史**，且写盘必须原子。

背景（团队评审 2026-10-12）：
原 `_load()` 是 `except Exception: return {"records": []}`，
把"文件损坏/权限错/编码错"与"首次无记录"压成同一结果；随后 `record()`
调 `_save()` **整文件覆盖** ⇒ 损坏文件被空历史覆盖，用户打卡记录
**永久丢失且无告警**（违反 §13.0「宁可没有数据，不可有错数据」）。

修法：① `_load` 对损坏显式 `raise`；② `_save` 改 tmp + fsync + os.replace 原子写。
"""
import json
import os

import pytest

from fg_system import human30


@pytest.fixture
def data_path(tmp_path, monkeypatch):
    p = tmp_path / "human30.json"
    monkeypatch.setattr(human30, "DATA_PATH", str(p))
    return p


def test_missing_file_returns_empty_history(data_path):
    """文件不存在 ⇒ 空历史（这是唯一允许降级的情形）。"""
    assert human30._load() == {"records": []}


def test_corrupt_file_raises_instead_of_silent_empty(data_path):
    """**守卫**：损坏 JSON 必须抛错，不得静默返回空历史。"""
    data_path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="损坏"):
        human30._load()


def test_corrupt_file_is_not_overwritten_by_record(data_path):
    """**守卫**：损坏文件在 `record()` 后必须**原样保留**（不被空历史覆盖）。"""
    data_path.write_text("{ broken", encoding="utf-8")
    before = data_path.read_text(encoding="utf-8")
    with pytest.raises(RuntimeError):
        human30.record(70, 70, 70, 70)
    assert data_path.read_text(encoding="utf-8") == before, (
        "损坏文件被覆盖了 ⇒ 用户记录不可逆丢失")


def test_save_is_atomic_and_leaves_no_tmp(data_path):
    """写盘用 tmp + os.replace，不留 .tmp 残骸，且内容可读回。"""
    human30._save({"records": [{"date": "2026-10-12", "mind": 70.0}]})
    assert not os.path.exists(str(data_path) + ".tmp")
    assert json.loads(data_path.read_text(encoding="utf-8"))["records"][0]["mind"] == 70.0


def test_record_then_load_roundtrip(data_path):
    """正常路径仍然可用（回归保护）。"""
    human30.record(80, 60, 70, 90)
    got = human30._load()
    assert len(got["records"]) == 1
    assert got["records"][0]["mind"] == 80.0
