# -*- coding: utf-8 -*-
"""WT-08 `scripts/evolve_weekly.py` 测试。

**不读真实 evolution/ 与 Data/**：用 monkeypatch 把 REPO / EVO / WEEKLY_DIR
指到 tmp_path；`main` 全程在 tmp_path 内读写；绝不触发 `--push`。
"""
import importlib.util
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "evolve_weekly.py")


def _load():
    spec = importlib.util.spec_from_file_location("evolve_weekly", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ew = _load()


@pytest.fixture
def patched(monkeypatch, tmp_path):
    evo = tmp_path / "evolution"
    evo.mkdir()
    monkeypatch.setattr(ew, "REPO", str(tmp_path))
    monkeypatch.setattr(ew, "EVO", str(evo))
    monkeypatch.setattr(ew, "WEEKLY_DIR", str(evo / "weekly"))
    return tmp_path


# ------------------------------------------------------------------ argparse
def test_help_runs(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["evolve_weekly.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        ew.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--push" in out and "--days" in out


# ------------------------------------------------------------------ 纯函数
def test_parse_md_rows_filters_prefix_and_min_cols(tmp_path):
    p = tmp_path / "h.md"
    p.write_text(
        "| H-001 | 2026-10-01 | 名称 | 方向 | 方法 | verifying |\n"
        "| H-002 | 2026-10-01 | 短行 |\n"       # 列数 <6 ⇒ 跳过
        "| 非表头 | x |\n",
        encoding="utf-8")
    rows = ew.parse_md_rows(str(p), "H-")
    assert len(rows) == 1
    assert rows[0][0] == "H-001"


def test_parse_md_rows_missing_file(tmp_path):
    assert ew.parse_md_rows(str(tmp_path / "nope.md"), "H-") == []


def test_iso_week_format():
    assert re.fullmatch(r"\d{4}-W\d{2}", ew.iso_week())


# ------------------------------------------------------------------ main
def test_main_writes_weekly_file_with_all_sections(patched, monkeypatch):
    evo = patched / "evolution"
    (patched / "docs").mkdir()
    (evo / "proposals").mkdir()
    (patched / "Data").mkdir()
    # 用当天日期使「本周」过滤命中
    today = ew.dt.date.today().isoformat()
    (evo / "hypotheses.md").write_text(
        "| H-001 | %s | 名称 | 方向 | 方法 | verifying |\n" % today,
        encoding="utf-8")
    (evo / "factors.md").write_text(
        "| F-001 | %s | 名称 | 方向 | 方法 | 门槛 | draft |\n" % today,
        encoding="utf-8")
    (evo / "proposals" / ("proposal_TQQQ_V-H1_%s.md" % today)).write_text(
        "# 提案\n**提案候选（OOS 不劣化）**\n", encoding="utf-8")
    (patched / "docs" / "decision-log.md").write_text(
        "## %s 审批（C-3）\n- 提案：x\n" % today, encoding="utf-8")
    (patched / "docs" / "blocked-registry.md").write_text(
        "| C-3 | 某某缺口可实施 | x |\n", encoding="utf-8")
    (patched / "Data" / "features.csv").write_text(
        "date,fg_index,zone,extra,extra2,extra3,extra4,circuit_breaker\n"
        "%s,50,2,0,0,0,0,false\n" % today, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["evolve_weekly.py"])
    ew.main()

    out_files = list((evo / "weekly").glob("weekly-*.md"))
    assert len(out_files) == 1
    text = out_files[0].read_text(encoding="utf-8")
    assert "进化周报" in text
    assert "本周假说状态变更" in text
    assert "H-001" in text                              # 本周假说命中
    assert "TQQQ_V-H1" in text                          # 本周提案（名称去掉 proposal_/.md）
    assert "C-3" in text                                # 数据缺口
    assert "指数尾行" in text                           # 风险快照


def test_main_empty_inputs_reports_none(patched, monkeypatch):
    """无任何 md 数据 ⇒ 各区块标「无…」，但仍生成周报文件，且不崩。"""
    (patched / "docs").mkdir()
    (patched / "evolution" / "proposals").mkdir()
    monkeypatch.setattr("sys.argv", ["evolve_weekly.py"])
    ew.main()
    files = list((patched / "evolution" / "weekly").glob("weekly-*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "无本周变更" in text
    assert "无本周提案" in text
    assert "无本周审批" in text


def test_main_days_window_excludes_old_rows(patched, monkeypatch):
    """--days 1：一年前的行不入周报。"""
    evo = patched / "evolution"
    (patched / "docs").mkdir()
    (evo / "proposals").mkdir()
    (evo / "hypotheses.md").write_text(
        "| H-001 | 2020-01-01 | 名称 | 方向 | 方法 | verifying |\n",
        encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["evolve_weekly.py", "--days", "1"])
    ew.main()
    text = list((evo / "weekly").glob("weekly-*.md"))[0].read_text(encoding="utf-8")
    assert "H-001" not in text                          # 旧行被窗口过滤
