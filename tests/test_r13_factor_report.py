# -*- coding: utf-8 -*-
"""R1.3 分因子独立报告：factor_zone / factor_score_summary / 简报分项 / dashboard api。

覆盖：
- factor_zone：边界 [20,40,60,80]（>= 判定）映射 0~4 档，NaN→None
- factor_score_summary：六因子 分+档位+方向+权重；缺失因子 score=None
- 简报 _factor_breakdown 确定性文本含全部六因子行
- dashboard /api/factors 返回结构与档位一致
"""
import json

import pandas as pd
import pytest

from fg_system.index import ZONE_NAMES, factor_score_summary, factor_zone


def test_factor_zone_edges():
    assert factor_zone(0.0) == 0
    assert factor_zone(19.9) == 0
    assert factor_zone(20.0) == 1          # >= 20 → 恐惧
    assert factor_zone(40.0) == 2
    assert factor_zone(60.0) == 3
    assert factor_zone(80.0) == 4
    assert factor_zone(99.9) == 4
    assert factor_zone(float("nan")) is None
    assert factor_zone(None) is None


def test_zone_names_cover_five():
    assert ZONE_NAMES == ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


def test_factor_score_summary_full():
    row = pd.Series({"vix": 72.0, "term": 45.0, "price": 58.0,
                     "breadth": 30.0, "fed": 50.0, "putcall": 88.0})
    s = factor_score_summary(row)
    assert set(s.keys()) == {"vix", "term", "price", "breadth", "fed", "putcall"}
    assert s["vix"]["score"] == 72.0 and s["vix"]["zone"] == 3
    assert s["vix"]["zone_name"] == "贪婪" and s["vix"]["direction"] == "贪婪向"
    assert s["breadth"]["zone"] == 1 and s["breadth"]["direction"] == "恐惧向"
    assert s["fed"]["zone"] == 2 and s["fed"]["direction"] == "中性"
    assert s["putcall"]["zone"] == 4
    # 权重与合成权重一致（vix 0.27 / putcall 0.10）
    assert s["vix"]["weight"] == pytest.approx(0.270, abs=1e-9)
    assert s["putcall"]["weight"] == pytest.approx(0.100, abs=1e-9)


def test_factor_score_summary_missing():
    row = pd.Series({"vix": float("nan"), "term": 45.0})
    s = factor_score_summary(row, factors=["vix", "term"])
    assert s["vix"]["score"] is None and s["vix"]["zone"] is None
    assert s["vix"]["zone_name"] == "—"
    assert s["term"]["score"] == 45.0


def test_brief_factor_breakdown_has_all_six():
    import scripts.invest_research as ir
    txt = ir._factor_breakdown()
    assert txt is not None
    for label in ("VIX", "TERM", "PRICE", "BREADTH", "FED", "PUT-CALL"):
        assert label in txt
    assert "R1.3" in txt or "档位边界" in txt


def test_factors_api_shape():
    """/api/factors 响应结构：date + fg_index + factors[](key/score/zone/zone_name/direction/weight)。"""
    from fg_system.dashboard.server import make_handler

    def get_features():
        return pd.read_csv("Data/features.csv")

    handler = make_handler(get_features, prices_path=None)
    client = handler.test_client()
    resp = client.get("/api/factors")
    assert resp.status_code == 200
    data = json.loads(resp.get_data(as_text=True))
    assert "factors" in data and len(data["factors"]) == 6
    f = data["factors"][0]
    for field in ("key", "score", "zone", "zone_name", "direction", "weight"):
        assert field in f
    # 档位与 score 自洽（非缺失时）
    if f["score"] is not None:
        assert f["zone"] == factor_zone(f["score"])
