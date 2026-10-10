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


# ================================================================ 二期：市场快照/未打卡/窗口统计/CSV

def test_record_with_market_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h.json"))
    human30.record(70, 60, 65, 55, market={"fg_index": 54.9, "zone": 2})
    rec = human30.latest()
    assert rec["market"] == {"fg_index": 54.9, "zone": 2}
    # 非法快照值不写入（容忍），记录仍成功
    human30.record(71, 61, 66, 56, market={"fg_index": "bad", "zone": 9})
    rec2 = human30.latest()
    assert "fg_index" not in rec2["market"]
    assert rec2["market"]["zone"] == 9


def test_days_since_last(tmp_path, monkeypatch):
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h.json"))
    assert human30.days_since_last() is None          # 从未打卡
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    human30.record(60, 60, 60, 60, when=yesterday)
    assert human30.days_since_last() == 1
    human30.record(61, 61, 61, 61)                     # 今日打卡
    assert human30.days_since_last() == 0


def test_window_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h.json"))
    from datetime import date, timedelta
    for i in range(5):
        d = (date.today() - timedelta(days=4 - i)).isoformat()
        human30.record(50 + i, 50, 50, 50, when=d)
    w = human30.window_stats(7)
    assert w["records"] == 5
    assert w["level_counts"][2] == 5                   # 均分 50-54 都落 L2
    # 并列最小时取 QUADRANTS 顺序首个：mind=50 一天 / 之后四天 body/spirit/vocation 并列取 body
    assert w["weakest_counts"].get("心/认知") == 1
    assert w["weakest_counts"].get("体/行动") == 4
    assert w["avg_series"][0]["date"] == (date.today() - timedelta(days=4)).isoformat()
    assert w["no_data"] is False
    assert human30.window_stats(7, today=date(2020, 1, 1))["no_data"] is True


def test_to_csv_exports_all(tmp_path, monkeypatch):
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h.json"))
    human30.record(70, 60, 65, 55, note="甲", when="2026-10-09",
                  market={"fg_index": 54.9, "zone": 2})
    human30.record(72, 62, 66, 58, note="乙", when="2026-10-10")
    out = tmp_path / "out.csv"
    human30.to_csv(str(out))
    lines = out.read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(lines) == 3                             # 表头 + 2 行
    assert "54.9" in lines[1] and ",2," in lines[1]
    assert "乙" in lines[2] and "甲" in lines[1]
