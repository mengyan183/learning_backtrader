# -*- coding: utf-8 -*-
"""P-FW（2026-10-13）FedWatch 预期迁移信号测试。

覆盖 fg_system/fed.py 新增字段：
- fw_curve（近端 vs 远端加息预期差）
- fw_migrate（|Δ1w|≥10pp 短期迁移 / |Δm|≥15pp 路径陡峭标记）
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import fg_system.fed as fed_mod
from fg_system import config


def _fake_fedwatch(monkeypatch, hike, wk_hike, m_hike):
    import pandas as pd
    rows = [{
        "date": "2026-10-13", "meeting": "2026-10-28",
        "ease_pct": 0.0, "hold_pct": 78.4, "hike_pct": hike,
        "now_hold_pct": 78.4, "now_hike_pct": hike,
        "wk_hold_pct": 77.9, "wk_hike_pct": wk_hike,
        "m_hold_pct": 51.0, "m_hike_pct": m_hike,
        "src": "cmefedwatch-quikstrike",
    }]
    df = pd.DataFrame(rows)
    tmpdir = tempfile.mkdtemp()
    csv_path = os.path.join(tmpdir, "fedwatch.csv")
    df.to_csv(csv_path, index=False)
    monkeypatch.setattr(fed_mod.config, "RAW_DIR", tmpdir)
    return csv_path


def test_fw_curve_present_when_m_hike_loaded(monkeypatch):
    """m_hike_pct 存在时 fw_curve = fw_hike − m_hike_pct。"""
    p = _fake_fedwatch(monkeypatch, hike=21.6, wk_hike=22.1, m_hike=42.5)
    try:
        ctx = fed_mod.fed_context(today=__import__("datetime").date(2026, 10, 13))
        assert ctx["fw_curve"] == pytest.approx(21.6 - 42.5, abs=1e-6)
    finally:
        os.unlink(p)


def test_fw_migrate_curve_steep_flagged(monkeypatch):
    """|fw_curve| ≥ 15pp → 触发路径陡峭迁移标记。"""
    p = _fake_fedwatch(monkeypatch, hike=21.6, wk_hike=22.1, m_hike=42.5)
    try:
        ctx = fed_mod.fed_context(today=__import__("datetime").date(2026, 10, 13))
        assert ctx["fw_migrate"] is not None
        assert "路径陡峭" in ctx["fw_migrate"]
    finally:
        os.unlink(p)


def test_fw_migrate_short_term_delta1w_flagged(monkeypatch):
    """|fw_delta_1w| ≥ 10pp 优先触发短期迁移标记。"""
    p = _fake_fedwatch(monkeypatch, hike=35.0, wk_hike=20.0, m_hike=42.5)
    try:
        ctx = fed_mod.fed_context(today=__import__("datetime").date(2026, 10, 13))
        assert ctx["fw_delta_1w"] == pytest.approx(15.0, abs=1e-6)
        assert ctx["fw_migrate"] is not None
        assert "一周" in ctx["fw_migrate"] and "回升" in ctx["fw_migrate"]
    finally:
        os.unlink(p)


def test_fw_migrate_absent_when_quiet(monkeypatch):
    """|Δ1w| < 10pp 且 |Δm| < 15pp → 无迁移标记。"""
    p = _fake_fedwatch(monkeypatch, hike=21.6, wk_hike=22.1, m_hike=30.0)
    try:
        ctx = fed_mod.fed_context(today=__import__("datetime").date(2026, 10, 13))
        assert ctx["fw_migrate"] is None
    finally:
        os.unlink(p)


def test_brief_includes_migrate_text(monkeypatch):
    """简报文本包含迁移标记。"""
    p = _fake_fedwatch(monkeypatch, hike=21.6, wk_hike=22.1, m_hike=42.5)
    try:
        ctx = fed_mod.fed_context(today=__import__("datetime").date(2026, 10, 13))
        text = fed_mod.fed_brief_text(ctx)
        assert "预期路径陡峭" in text
    finally:
        os.unlink(p)
