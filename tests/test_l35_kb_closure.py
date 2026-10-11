# -*- coding: utf-8 -*-
"""L3.5 知识库闭环增强测试（invest_research --kb + human30 规则化洞察）。"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system import human30


def _seed(records):
    import json
    p = human30.DATA_PATH if hasattr(human30, "DATA_PATH") else \
        os.path.join(REPO, "Data", "human30.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"records": records}, f, ensure_ascii=False)
    return p


class TestHuman30InsightSummary:
    def _mk(self, date, mind, body, spirit, vocation):
        return {"date": date, "mind": mind, "body": body, "spirit": spirit,
                "vocation": vocation, "note": ""}

    def test_no_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h30.json"))
        _seed([])
        out = human30.insight_summary(days=7, today="2026-10-11")
        assert out == ["窗口内无打卡记录，暂无可提炼洞察。"]

    def test_rules_extracted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h30.json"))
        recs = []
        for i, (d, s) in enumerate([("2026-10-05", 30), ("2026-10-06", 35),
                                    ("2026-10-07", 38), ("2026-10-08", 45),
                                    ("2026-10-09", 50)]):
            recs.append(self._mk(d, s, 50, 60, 40))
        _seed(recs)
        out = human30.insight_summary(days=7, today="2026-10-11")
        assert any("打卡纪律" in o and "5/7" in o for o in out)      # 纪律率
        assert any("主导水平" in o and "2.0 段" in o for o in out)    # 主导水平
        assert any("短板聚焦" in o and "心/认知" in o for o in out)  # 最弱象限
        assert any("趋势" in o and "上升" in o for o in out)          # 前半→后半上升
        assert len(out) == 4

    def test_streak_trend_flat(self, tmp_path, monkeypatch):
        monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h30.json"))
        recs = [self._mk(f"2026-10-0{i}", 50, 50, 50, 50) for i in range(5, 10)]
        _seed(recs)
        out = human30.insight_summary(days=7, today="2026-10-11")
        assert any("趋势" in o and "持平" in o for o in out)


class TestInvestResearchKb:
    def test_kb_context_empty_on_no_kb(self):
        from scripts import invest_research as ir
        assert ir._kb_context(None) == ""

    def test_stage_attribution_accepts_kb(self, monkeypatch):
        """kb 参数传入不改签名/不抛错；无 key 时按降级路径返回 None。"""
        from scripts import invest_research as ir
        monkeypatch.setattr(ir, "_read_nim_key", lambda: "")
        monkeypatch.setattr(ir, "_chat", lambda *a, **k: "归因正文")
        monkeypatch.setattr(ir, "_clean_attribution", lambda s: s)
        monkeypatch.setattr(ir, "snapshot_text", lambda s: "持仓快照(测试)")
        snap = {"date": "2026-10-11"}
        out = ir.stage_attribution("", snap, kb=None)
        assert out == "归因正文"

    def test_kb_context_includes_source(self, monkeypatch):
        from scripts import invest_research as ir
        fake_rows = [{"channel": "BenFelix", "title": "Leveraged ETF risk",
                      "date": "20260101", "score": 0.9,
                      "snippet": "risk management matters"}]
        from scripts import kb_search as kb_mod
        monkeypatch.setattr(kb_mod, "search_results", lambda q, n=3: fake_rows)
        out = ir._kb_context("杠杆ETF", n=1)
        assert "知识库观点参考" in out
        assert "BenFelix《Leveraged ETF risk》" in out
        assert "不构成信号" in out
