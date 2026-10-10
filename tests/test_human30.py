# -*- coding: utf-8 -*-
"""Human 3.0 组合骨架核心规则测试（level 判定 / 聚合 / 建议 / 记录）。"""
import os

import pytest

from fg_system import human30


@pytest.fixture(autouse=True)
def _tmp_data(tmp_path, monkeypatch):
    """把数据文件指到临时目录，测试不污染真实 Data/。"""
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "human30.json"))


def test_level_boundaries():
    assert human30.aggregate({"mind": 20, "body": 20, "spirit": 20, "vocation": 20})["level"] == 1
    assert human30.aggregate({"mind": 50, "body": 50, "spirit": 50, "vocation": 50})["level"] == 2
    assert human30.aggregate({"mind": 50, "body": 50, "spirit": 50, "vocation": 51})["level"] == 2
    assert human30.aggregate({"mind": 80, "body": 80, "spirit": 80, "vocation": 80})["level"] == 3
    # 70 边界：<=70 为 L2，>70 为 L3
    assert human30.aggregate({"mind": 70, "body": 70, "spirit": 70, "vocation": 70})["level"] == 2
    assert human30.aggregate({"mind": 71, "body": 71, "spirit": 71, "vocation": 71})["level"] == 3


def test_aggregate_avg_std_weakest():
    agg = human30.aggregate({"mind": 80, "body": 40, "spirit": 60, "vocation": 60})
    assert agg["avg"] == 60.0
    assert agg["weakest"] == "body"
    assert agg["weakest_label"] == "体/行动"
    assert agg["weakest_val"] == 40
    assert agg["imbalanced"] is False  # std=14.1 <= 20


def test_imbalanced_flag():
    # 均衡：std=0 → 不失衡
    agg = human30.aggregate({"mind": 50, "body": 50, "spirit": 50, "vocation": 50})
    assert agg["std"] == 0
    assert agg["imbalanced"] is False
    # 极端失衡：std 大 → 失衡
    agg = human30.aggregate({"mind": 90, "body": 10, "spirit": 90, "vocation": 90})
    assert agg["imbalanced"] is True


def test_advice_weak_quadrant():
    rec = {"mind": 30, "body": 80, "spirit": 70, "vocation": 60}
    adv = human30.advice(rec)
    assert any("优先补短板" in a and "心/认知" in a for a in adv)


def test_advice_strong_all():
    rec = {"mind": 85, "body": 80, "spirit": 82, "vocation": 78}
    adv = human30.advice(rec)
    assert any("外化输出" in a for a in adv)


def test_advice_trend_drop():
    prev = {"mind": 80, "body": 80, "spirit": 80, "vocation": 80}
    rec = {"mind": 60, "body": 80, "spirit": 80, "vocation": 80}
    adv = human30.advice(rec, prev)
    assert any("心/认知" in a and "下降" in a for a in adv)


def test_record_roundtrip_and_overwrite():
    human30.record(60, 55, 50, 45, note="第一天", when="2026-10-01")
    human30.record(65, 60, 55, 50, note="第二天", when="2026-10-02")
    recs = human30.history(10)
    assert len(recs) == 2
    assert human30.latest()["note"] == "第二天"
    # 同日重复打卡 → 覆盖当日（记录数不变）
    human30.record(70, 65, 60, 55, note="覆盖", when="2026-10-02")
    recs = human30.history(10)
    assert len(recs) == 2
    assert human30.latest()["note"] == "覆盖"


def test_record_range_validation():
    with pytest.raises(ValueError):
        human30.record(101, 50, 50, 50)
    with pytest.raises(ValueError):
        human30.record(50, -1, 50, 50)


def test_brief_line_none_when_no_data():
    assert human30.brief_line() is None
    human30.record(70, 60, 65, 55)
    line = human30.brief_line()
    assert line is not None
    assert "Level 2.0" in line
