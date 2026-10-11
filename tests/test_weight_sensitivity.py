# -*- coding: utf-8 -*-
"""M2.3 权重敏感性：扰动归一 + 输出结构 + 模板敏感性表。"""
import json

import pytest

from scripts.weight_sensitivity import perturb, render

BASE_W = {"vix": 0.27, "term": 0.135, "price": 0.225,
          "breadth": 0.135, "fed": 0.135, "putcall": 0.10}


def test_perturb_rescales_to_one():
    for f in BASE_W:
        for d in (+0.10, -0.10):
            w = perturb(BASE_W, f, d)
            assert sum(w.values()) == pytest.approx(1.0, abs=1e-12)
            assert w[f] == pytest.approx(BASE_W[f] * (1 + d) /
                                         (1 + d * BASE_W[f]), abs=1e-6)


def test_perturb_preserves_others_ratio():
    w = perturb(BASE_W, "vix", +0.10)
    # 非扰动因子保持相对比例
    assert w["term"] / w["price"] == pytest.approx(
        BASE_W["term"] / BASE_W["price"], rel=1e-9)


def test_perturb_direction():
    assert perturb(BASE_W, "vix", +0.10)["vix"] > BASE_W["vix"]
    assert perturb(BASE_W, "vix", -0.10)["vix"] < BASE_W["vix"]


def test_render_contains_sensitivity_table():
    base = {"annual_return": 0.3766, "max_drawdown": -0.2607, "sharpe": 1.2565}
    results = [{
        "factor": "vix", "delta": 0.10,
        "fg_delta_max": 1.22, "fg_delta_mean": 0.36,
        "zone_flip_days": 792, "target_flip_days": 1651,
        "portfolio_oos": {"annual_return": 0.4623, "max_drawdown": -0.297,
                          "sharpe": 1.33},
        "buyhold_oos": {"annual_return": 0.7545, "max_drawdown": -0.617,
                        "sharpe": 1.00},
    }]
    md = render(results, BASE_W, base, 0.10)
    assert "基准 WEIGHTS" in md and "vix" in md
    assert "| 因子 | 扰动 |" in md
    assert "只测量不改参" in md
    assert json.dumps(BASE_W, ensure_ascii=False) in md
