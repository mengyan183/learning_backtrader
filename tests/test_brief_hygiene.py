# -*- coding: utf-8 -*-
"""简报卫生：剥 LLM 噪音行 + 模块→agent 路由（2026-11-09 用户要求）。"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import invest_research as ir  # noqa: E402


def test_strip_removes_pseudo_keys_and_selfcheck():
    """伪键名占位符 + 字数自检行必须剥掉，正文不动。"""
    raw = ("一、逐标的归因\n"
           "AXTX -92.5%，亏3930。\n"
           "explainer.file_mutation.header\n"
           "explainer.file_mutation.entry\n"
           "495字，符合上限。\n"
           "（498字，已按去空白字符核验）\n"
           "二、组合风险点\n")
    out = ir._strip_llm_artifacts(raw)
    assert "explainer.file_mutation" not in out
    assert "符合上限" not in out
    assert "已按去空白字符核验" not in out
    assert "AXTX -92.5%" in out
    assert "二、组合风险点" in out


def test_strip_keeps_legit_text_with_zi():
    """正常含「字」的正文不得被误删（只删 ≤30 字且带自检词的短行）。"""
    raw = "这一段的字面意思是杠杆损耗会累积，需要按逐日复利理解。"
    assert ir._strip_llm_artifacts(raw) == raw


def test_strip_removes_trailing_zi_suffix():
    """行尾的「（48字）」只削后缀，正文保留 ✓（2026-11-09 18:49 实测）。"""
    raw = "建议：每天固定20分钟写意义笔记，两周后对照精神分值。（48字）"
    out = ir._strip_llm_artifacts(raw)
    assert out.endswith("分值。")
    assert "48字" not in out


def test_strip_handles_none():
    assert ir._strip_llm_artifacts(None) is None


def test_agent_route_defaults_and_override(monkeypatch):
    """模块→agent 路由：默认回落现状，环境变量可覆盖。"""
    for k in ("FG_AGENT_SENTIMENT_URL", "FG_AGENT_SENTIMENT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    url, model = ir.agent_route("sentiment")
    assert url == ir.HERMES_URL and model == ir.HERMES_MODEL

    monkeypatch.setenv("FG_AGENT_SENTIMENT_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("FG_AGENT_SENTIMENT_MODEL", "other-agent")
    url, model = ir.agent_route("sentiment")
    assert url == "http://127.0.0.1:9999/v1" and model == "other-agent"


def test_agent_route_covers_three_modules():
    assert set(ir.AGENT_ROUTES) == {"sentiment", "attribution", "judge"}
