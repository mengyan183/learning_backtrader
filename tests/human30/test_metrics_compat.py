# -*- coding: utf-8 -*-
"""C-1 守卫：aggregate() 的旧 key（level/level_name）语义必须保持「整体均分档」。"""
from fg_system.human30 import metrics


def test_aggregate_legacy_level_keeps_average_semantics():
    rec = {"mind": 80, "body": 80, "spirit": 80, "vocation": 20}   # avg=65 → L2
    agg = metrics.aggregate(rec)
    assert agg["level"] == 2                     # 均分档（旧语义，不得变）
    assert agg["avg"] == 65.0
    assert agg["weakest"] == "vocation"
    assert agg["quadrant_levels"]["vocation"] == 1   # 新增 key
    assert agg["weakest_level"] == 1


def test_aggregate_boundaries_unchanged():
    assert metrics.aggregate({"mind": 20, "body": 20, "spirit": 20,
                              "vocation": 20})["level"] == 1
    assert metrics.aggregate({"mind": 70, "body": 70, "spirit": 70,
                              "vocation": 70})["level"] == 2
    assert metrics.aggregate({"mind": 71, "body": 71, "spirit": 71,
                              "vocation": 71})["level"] == 3


def test_brief_line_uses_legacy_level_name():
    line = metrics.brief_line({"mind": 70, "body": 70, "spirit": 70, "vocation": 70})
    assert "Level 2.0" in line
