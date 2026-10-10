# -*- coding: utf-8 -*-
"""WT-08 `scripts/evolve_approve.py` 测试。

**不写真实 evolution/ 与 docs/**：用 monkeypatch 把 PROPOSALS / DECISION_LOG /
TEXT_DIR 指到 tmp_path；push 走 --dry-run，绝不联网、绝不调 feishu_send。
"""
import importlib.util
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "evolve_approve.py")


def _load():
    spec = importlib.util.spec_from_file_location("evolve_approve", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ea = _load()


def _proposal(tmp_path, name, body="**提案候选（OOS 不劣化）**\n", approved=False):
    d = tmp_path / "proposals"
    d.mkdir(exist_ok=True)
    text = body
    if approved:
        text += "\n审批记录：Y 2026-10-08 10:00（采纳）\n"
    (d / name).write_text(text, encoding="utf-8")
    return d


@pytest.fixture
def patched(monkeypatch, tmp_path):
    """把三个模块级目录常量指到 tmp_path。"""
    props = tmp_path / "proposals"
    props.mkdir()
    monkeypatch.setattr(ea, "REPO", str(tmp_path))     # approve() 拼相对路径用 REPO
    monkeypatch.setattr(ea, "PROPOSALS", str(props))
    monkeypatch.setattr(ea, "DECISION_LOG", str(tmp_path / "docs" / "decision-log.md"))
    monkeypatch.setattr(ea, "TEXT_DIR", str(tmp_path / "text"))
    return tmp_path


# ------------------------------------------------------------------ argparse
def test_help_runs(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["evolve_approve.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        ea.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--approve" in out and "--push" in out


# ------------------------------------------------------------------ scan_pending
def test_scan_pending_lists_unapproved(patched):
    _proposal(patched, "proposal_TQQQ_V-H1_2026-10-08.md")
    pend = ea.scan_pending()
    assert len(pend) == 1
    assert pend[0]["sym"] == "TQQQ"
    assert pend[0]["vk"] == "V-H1"
    assert pend[0]["verdict"] == "提案候选"


def test_scan_pending_skips_approved(patched):
    _proposal(patched, "proposal_TQQQ_V-H1_2026-10-08.md", approved=True)
    assert ea.scan_pending() == []


def test_scan_pending_verdict_not_adopted(patched):
    _proposal(patched, "proposal_SOXL_V-H9_2026-10-08.md",
              body="**不采纳（OOS 未不劣化）**\n")
    pend = ea.scan_pending()
    assert pend[0]["verdict"] == "不采纳"


# ------------------------------------------------------------------ approve
def test_approve_appends_record(patched):
    _proposal(patched, "proposal_TQQQ_V-H1_2026-10-08.md")
    path = str(patched / "proposals" / "proposal_TQQQ_V-H1_2026-10-08.md")
    full, status, note = ea.approve(path, "Z", "观察")
    assert status == "Z"
    text = open(full, encoding="utf-8").read()
    assert "审批记录：" in text and "Z" in text and "（观察）" in text
    # 审批后再扫描 ⇒ 不再 pending
    assert ea.scan_pending() == []


def test_approve_missing_file_exits_1(patched, capsys):
    with pytest.raises(SystemExit) as exc:
        ea.approve(str(patched / "nope.md"), "Y")
    assert exc.value.code == 1
    assert "提案不存在" in capsys.readouterr().out


def test_approve_bad_status_exits_1(patched, capsys):
    _proposal(patched, "proposal_TQQQ_V-H1_2026-10-08.md")
    path = str(patched / "proposals" / "proposal_TQQQ_V-H1_2026-10-08.md")
    with pytest.raises(SystemExit) as exc:
        ea.approve(path, "X")
    assert exc.value.code == 1
    assert "Y（采纳）" in capsys.readouterr().out


def test_approve_duplicate_exits_1(patched, capsys):
    _proposal(patched, "proposal_TQQQ_V-H1_2026-10-08.md", approved=True)
    path = str(patched / "proposals" / "proposal_TQQQ_V-H1_2026-10-08.md")
    with pytest.raises(SystemExit) as exc:
        ea.approve(path, "Y")
    assert exc.value.code == 1
    assert "勿重复审批" in capsys.readouterr().out


# ------------------------------------------------------------------ log_decision
def test_log_decision_creates_file(patched):
    ea.log_decision(str(patched / "proposal_TQQQ_V-H1_2026-10-08.md"), "Y", "采纳")
    log = patched / "docs" / "decision-log.md"
    assert log.exists()
    text = log.read_text(encoding="utf-8")
    assert "审批（C-3）" in text and "（采纳）" in text


# ------------------------------------------------------------------ main 分支
def test_main_list_default(patched, monkeypatch, capsys):
    _proposal(patched, "proposal_TQQQ_V-H1_2026-10-08.md")
    monkeypatch.setattr("sys.argv", ["evolve_approve.py", "list"])
    ea.main()
    out = capsys.readouterr().out
    assert "未审批提案 1 份" in out and "TQQQ" in out


def test_main_list_when_none(patched, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["evolve_approve.py"])
    ea.main()
    assert "无未审批提案" in capsys.readouterr().out


def test_main_approve_without_status_exits_1(patched, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv",
                        ["evolve_approve.py", "--approve", "proposal_x.md"])
    with pytest.raises(SystemExit) as exc:
        ea.main()
    assert exc.value.code == 1
    assert "需提供审批状态" in capsys.readouterr().out


def test_main_approve_with_log(patched, monkeypatch):
    _proposal(patched, "proposal_TQQQ_V-H1_2026-10-08.md")
    monkeypatch.setattr("sys.argv",
                        ["evolve_approve.py", "--approve",
                         "proposals/proposal_TQQQ_V-H1_2026-10-08.md",
                         "--status", "Y", "--log"])
    ea.main()
    assert (patched / "docs" / "decision-log.md").exists()


# ------------------------------------------------------------------ push (dry-run)
def test_push_dry_run_writes_chunk_no_send(patched, capsys):
    _proposal(patched, "proposal_TQQQ_V-H1_2026-10-08.md")
    rc = ea.push_pending(dry_run=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "--dry-run" in out
    # 分片已写且含分片名 approve_<MMDD>-t001.txt
    chunks = list((patched / "text").glob("approve_*-t001.txt"))
    assert len(chunks) == 1
    assert "TQQQ" in chunks[0].read_text(encoding="utf-8")


def test_push_no_pending_returns_0(patched, capsys):
    assert ea.push_pending(dry_run=True) == 0
    assert "无需推送" in capsys.readouterr().out
