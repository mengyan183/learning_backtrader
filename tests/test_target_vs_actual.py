# -*- coding: utf-8 -*-
"""S-5：模型目标仓位 vs 实盘偏离度（只报事实，不给指令）。"""
from fg_system import risk


def test_over():
    r = risk.target_vs_actual(0.08, 100.0, 100.0)
    assert r["side"] == "over"
    assert r["gap_pp"] == 92.0


def test_under():
    r = risk.target_vs_actual(0.65, 100.0, 30.0)
    assert r["side"] == "under"
    assert round(r["gap_pp"], 2) == -35.0


def test_on_target_within_1pp():
    r = risk.target_vs_actual(0.50, 100.0, 50.5)
    assert r["side"] == "on_target"


def test_missing_inputs_return_none():
    assert risk.target_vs_actual(None, 100.0, 50.0) is None
    assert risk.target_vs_actual(0.5, 0.0, 50.0) is None
    assert risk.target_vs_actual(1.5, 100.0, 50.0) is None
    assert risk.target_vs_actual(0.5, None, 50.0) is None


def test_no_imperative_wording():
    """只报事实：返回里不得出现祈使词。"""
    r = risk.target_vs_actual(0.08, 100.0, 100.0)
    blob = repr(r)
    for w in ("应", "该", "建议", "必须", "减仓", "加仓"):
        assert w not in blob
