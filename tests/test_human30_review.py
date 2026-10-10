# -*- coding: utf-8 -*-
"""H-REV-001 AI 复盘测试：降级路径 + 前缀守卫 + 交易字眼过滤（LLM 调用用坏 host 触发降级）。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from fg_system import human30
from human30_review import review, PREFIX


def test_review_degrades_when_no_records(tmp_path, monkeypatch):
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h.json"))
    out = review(days=7, host="http://127.0.0.1:1")   # 不可达 host
    assert out.startswith(PREFIX)
    assert "尚无自评记录" in out


def test_review_degrades_on_llm_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h.json"))
    human30.record(70, 60, 65, 55, when="2026-10-10",
                   market={"fg_index": 54.9, "zone": 2})
    out = review(days=7, host="http://127.0.0.1:1")   # 模型不可达 → 降级确定性统计
    assert out.startswith(PREFIX)
    assert "降级确定性统计" in out
    assert "打卡 1 次" in out


def test_output_guard_filters_trade_words():
    from human30_review import _guard_filter
    assert "调整行动" == _guard_filter("调整交易策略")
    assert "及时调整自己的行动" == _guard_filter("及时调整自己的交易策略")
    assert "行动" in _guard_filter("建议加仓到 50%")


def test_build_data_lines_na(tmp_path, monkeypatch):
    from human30_review import _build_data_lines
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h.json"))
    human30.record(70, 60, 65, 55, when="2026-10-10")  # 无 market
    lines = _build_data_lines(7)
    assert lines and "N/A" in lines
