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


def test_clip_at_sentence_cuts_at_period():
    """超长文本必须在**句号处**收尾，不能砍半句（2026-11-10 实测）。"""
    body = "第一句讲归因。" * 30
    out = ir._clip_at_sentence(body, 1200)
    assert len(out) <= 1200
    assert out.endswith("。"), "截断点不在句号处"


def test_clip_at_sentence_keeps_short_text():
    assert ir._clip_at_sentence("很短的一句。", 1200) == "很短的一句。"


def test_clip_at_sentence_falls_back_when_no_period():
    """全篇没有句号 ⇒ 退化为 `…` 收尾，不硬切出半句感。"""
    out = ir._clip_at_sentence("啊" * 2000, 1200)
    assert len(out) <= 1201
    assert out.endswith("…")


def test_strip_removes_markdown_heading():
    """模型吐的 `## 一、逐标的归因` 必须去掉 `##`（飞书不解析 markdown）。"""
    raw = "## 一、逐标的归因\nAXTX 亏 92.5%。\n### 二、组合风险点\n现金 -884。"
    out = ir._strip_llm_artifacts(raw)
    assert "##" not in out
    assert "一、逐标的归因" in out
    assert "二、组合风险点" in out
