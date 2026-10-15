# -*- coding: utf-8 -*-
"""P5：看板 Human 3.0 块 —— 无数字 / 无交易动词 / 跨机提示 / 不崩。"""
import json
import re

import pytest

from fg_system.dashboard import report
from fg_system.human30 import store

VERBS = ["减仓", "加仓", "买入", "卖出", "仓位", "止损", "清仓", "抄底", "杠杆"]


@pytest.fixture
def data_path(tmp_path, monkeypatch):
    p = tmp_path / "human30.json"
    monkeypatch.setattr(store, "DATA_PATH", str(p))
    return p


def test_no_data_shows_cross_machine_notice(data_path):
    """§8.1：无数据文件 ⇒ 跨机文案（不是空白 ✗）。"""
    html = report._human30_block()
    assert "本机无 Human 3.0 数据" in html


def test_empty_records_shows_hint(data_path):
    store._save({"records": []})
    assert "暂无打卡记录" in report._human30_block()


def test_with_record_no_score_or_level_digits(data_path):
    """§7.1：不得出现**分数与 Level 数字** ✗（日期与 CSS 值不算 ✗）。"""
    store._save({"records": [{
        "date": "2026-10-15", "mind": 70.0, "body": 60.0,
        "spirit": 40.0, "vocation": 65.0, "note": "",
    }]})
    html = report._human30_block()
    assert not re.search(r"\d+\s*/\s*100", html)      # 禁 "xx/100"
    assert not re.search(r"Level\s*[123]", html)      # 禁 "Level 1/2/3"
    assert not re.search(r"\bL[123]\b", html)         # 禁 "L1/L2/L3"
    assert "均分" not in html                          # 禁均分
    assert not re.search(r"\d+\.\d+", html)           # 禁小数分（如 70.0）
    for v in VERBS:
        assert v not in html


def test_with_record_shows_date_and_quadrants(data_path):
    """日期必须在 ✓（它不是分数 ✗）；四象限 Archetype 名必须在 ✓。"""
    store._save({"records": [{
        "date": "2026-10-15", "mind": 70.0, "body": 60.0,
        "spirit": 40.0, "vocation": 65.0, "note": "",
    }]})
    html = report._human30_block()
    assert "2026-10-15" in html
    assert "Lifestyle：" in html and "Metatype：" in html


def test_dashboard_json_keeps_old_keys_and_adds_new(data_path):
    store._save({"records": [{
        "date": "2026-10-15", "mind": 70.0, "body": 60.0,
        "spirit": 40.0, "vocation": 65.0, "note": "",
    }]})
    d = report._human30_dashboard_json()
    for k in ("dates", "keys", "labels", "series", "avg", "latest"):
        assert k in d, "丢了旧键：%s" % k
    for k in ("levels", "level_words", "phases", "lifestyle", "metatype", "has_data"):
        assert k in d, "缺新键：%s" % k
    assert d["has_data"] is True
    assert all("：" not in v for v in d["level_words"].values())


def test_dashboard_json_none_when_no_records(data_path):
    """§8.2：无记录仍返回 None（前端 default('null') 兜底 ✓）。"""
    assert report._human30_dashboard_json() is None


def test_index_html_keeps_null_default():
    """§8.2 回归：human30_json 的 default('null') 必须保留。"""
    import os
    p = os.path.join(os.path.dirname(report.__file__), "templates", "index.html")
    assert "human30_json | default('null')" in open(p, encoding="utf-8").read()
