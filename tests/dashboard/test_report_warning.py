# -*- coding: utf-8 -*-
"""G-1 守卫：数据停更告警**必须在看板顶部展示**。

背景（WT-12 代码审查 G-1）：`docs/system-boundary.md` §5 原文「警告存在时，
简报/看板顶部必须展示，不得假装数据是最新的」。简报侧已做到
（`scripts/invest_research.py::_freshness_block`），看板侧此前**没有**
⇒ 手机看板在数据停更时仍显示"最新"，正是该条明令禁止的行为。

不读真实 Data/：config.DATA_DIR 指到 tmp_path（与 test_freshness.py 同法）。
"""
import pandas as pd

from fg_system.dashboard import report

WARN_TEXT = "指数数据 2026-09-29 距今天已 11 天未更新（正常 ≤3）"


def _features(n=100):
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame({"fg_index": 50.0, "zone": 2, "target_position": 0.4},
                        index=idx)


def test_warning_banner_shown_when_file_nonempty(tmp_path, monkeypatch):
    """**守卫**：告警文件非空 ⇒ HTML 必须含告警文本。"""
    monkeypatch.setattr(report.config, "DATA_DIR", str(tmp_path))
    (tmp_path / "freshness_warning.txt").write_text(WARN_TEXT, encoding="utf-8")

    html = report.render_html(_features())

    assert "数据停更风险" in html, "告警存在却未在看板展示 ⇒ 违反 system-boundary §5"
    assert "距今天已 11 天未更新" in html, "告警条必须带上具体原因，不能只说'有问题'"


def test_no_banner_when_file_missing_or_empty(tmp_path, monkeypatch):
    """文件缺失/为空 ⇒ 不得出现告警条（天天报警等于没有信号）。"""
    monkeypatch.setattr(report.config, "DATA_DIR", str(tmp_path))
    assert "数据停更风险" not in report.render_html(_features())

    (tmp_path / "freshness_warning.txt").write_text("  \n", encoding="utf-8")
    assert "数据停更风险" not in report.render_html(_features())


def test_warning_text_is_escaped(tmp_path, monkeypatch):
    """告警文本要转义后再插入 —— 模板是 autoescape=False，直接拼会破页。"""
    monkeypatch.setattr(report.config, "DATA_DIR", str(tmp_path))
    (tmp_path / "freshness_warning.txt").write_text(
        "a<b>&c", encoding="utf-8")

    html = report.render_html(_features())

    assert "a&lt;b&gt;&amp;c" in html
