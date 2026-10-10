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
    out = review(days=7, host="http://127.0.0.1:1")   # 模型不可达 → 确定性事实句 + 确定性建议
    assert out.startswith(PREFIX)
    assert "mind=70" in out            # 确定性事实句永不漂移
    assert "建议降级为确定性规则" in out
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


def test_build_data_lines_kv_format(tmp_path, monkeypatch):
    """数据行必须键值对（字段名=值），防 3b 模型列序错位。"""
    from human30_review import _build_data_lines
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "h.json"))
    human30.record(100, 100, 60, 60, when="2026-10-10",
                   market={"fg_index": 60.5, "zone": 3})
    lines = _build_data_lines(7)
    assert lines.startswith("日期=2026-10-10 | mind=100 | body=100 | spirit=60 | vocation=60")
    assert "均分=80.0" in lines and "fg_index=60.5" in lines and "zone=3" in lines


def test_guard_filters_greed_suggestion():
    from human30_review import _guard_filter
    assert "行动" in _guard_filter("仍然需要关注市场快照中的信息，避免过度贪婪。")
    assert "行动" in _guard_filter("避免贪婪，保持纪律。")
