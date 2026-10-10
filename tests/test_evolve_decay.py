# -*- coding: utf-8 -*-
"""WT-08 `scripts/evolve_decay.py` 测试。

**不读真实 evolution/**：用 monkeypatch 把 FM / HM / OUT 指到 tmp_path。
"""
import importlib.util
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "evolve_decay.py")

FACTORS_HEAD = (
    "| 编号 | 日期 | 名称 | 方向 | 方法 | 门槛 | 状态 | 备注 |\n"
    "|---|---|---|---|---|---|---|---|\n"
)
HYP_HEAD = (
    "| 编号 | 日期 | 名称 | 方向 | 方法 | 状态 | 备注 |\n"
    "|---|---|---|---|---|---|---|\n"
)


def _load():
    spec = importlib.util.spec_from_file_location("evolve_decay", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ed = _load()


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------ argparse
def test_help_runs(monkeypatch, capsys):
    """`--help` 可运行且退出码 0（验收标准）。"""
    monkeypatch.setattr("sys.argv", ["evolve_decay.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        ed.main()
    assert exc.value.code == 0
    assert "--write" in capsys.readouterr().out


# ------------------------------------------------------------------ 纯函数
def test_parse_factor_rows_handles_escaped_pipe():
    text = ("| F-001 | 2026-10-02 | 名称 | 逆向 | 方法 | \\|ICIR\\|>=0.5 | draft | 备注 5 日近窗衰减 |\n")
    rows = ed.parse_factor_rows(text)
    assert len(rows) == 1
    assert rows[0]["id"] == "F-001"
    assert rows[0]["status"] == "draft"          # 未被 \| 转义拆裂
    assert rows[0]["note"] == "备注 5 日近窗衰减"


def test_parse_factor_rows_skips_short_rows():
    text = "| F-002 | 2026-10-02 | 名称 |\n"      # 列数不足 8 ⇒ 跳过
    assert ed.parse_factor_rows(text) == []


def test_decay_horizons_counts_and_lists():
    n, hits = ed.decay_horizons("5/10 日近窗衰减、40 日近窗衰减")
    assert n == 2
    assert hits == ["5/10", "40"]
    assert ed.decay_horizons("无衰减标记")[0] == 0


def test_classify_accumulating():
    row = {"id": "F-003", "status": "draft", "note": "样本不足，积累中"}
    status, why = ed.classify(row)
    assert status == "accumulating"
    assert "积累中" in why


def test_classify_decayed_when_two_or_more_horizons():
    row = {"id": "F-004", "status": "draft",
           "note": "5/10 日近窗衰减、40 日近窗衰减"}
    status, why = ed.classify(row)
    assert status == "decayed"
    assert "近窗衰减 2/4" in why


def test_classify_keeps_status_when_one_horizon():
    row = {"id": "F-005", "status": "verified", "note": "仅 5 日近窗衰减"}
    status, why = ed.classify(row)
    assert status == "verified"                   # 保留原状态
    assert "维持观察" in why


def test_classify_no_marker_keeps_status():
    row = {"id": "F-006", "status": "draft", "note": "无标记"}
    status, why = ed.classify(row)
    assert status == "draft"
    assert why == "无近窗衰减标记，维持"


# ------------------------------------------------------------------ main 分支
def test_main_dry_run_prints_report_and_writes_nothing(monkeypatch, tmp_path, capsys):
    """默认 dry-run：打印报告但不写回 factors.md。"""
    fm = _write(tmp_path, "factors.md",
                FACTORS_HEAD + "| F-001 | 2026-10-02 | n | 逆向 | m | \\|ICIR\\|>=0.5 | draft | 无 |\n")
    hm = _write(tmp_path, "hypotheses.md",
                HYP_HEAD + "| H-001 | 2026-10-02 | n | 逆向 | m | verifying | 观察 |\n")
    monkeypatch.setattr(ed, "FM", fm)
    monkeypatch.setattr(ed, "HM", hm)
    monkeypatch.setattr(ed, "OUT", str(tmp_path / "decay-report.md"))
    monkeypatch.setattr("sys.argv", ["evolve_decay.py"])
    ed.main()
    out = capsys.readouterr().out
    assert "因子/假说绩效衰减降级报告" in out
    assert "dry-run" in out and "未写回" in out
    assert not (tmp_path / "decay-report.md").exists()      # 未生成报告
    # factors.md 未被改写（内容不变）
    assert (tmp_path / "factors.md").read_text(encoding="utf-8") == (
        FACTORS_HEAD + "| F-001 | 2026-10-02 | n | 逆向 | m | \\|ICIR\\|>=0.5 | draft | 无 |\n")


def test_main_write_updates_status_and_writes_report(monkeypatch, tmp_path, capsys):
    """--write：写回 factors.md 状态列 + 生成 decay-report.md。"""
    fm = _write(tmp_path, "factors.md",
                FACTORS_HEAD + "| F-001 | 2026-10-02 | n | 逆向 | m | \\|ICIR\\|>=0.5 | draft | 5/10 日近窗衰减、40 日近窗衰减 |\n")
    hm = _write(tmp_path, "hypotheses.md",
                HYP_HEAD + "| H-001 | 2026-10-02 | n | 逆向 | m | adopted | 观察 |\n")
    out_path = tmp_path / "decay-report.md"
    monkeypatch.setattr(ed, "FM", fm)
    monkeypatch.setattr(ed, "HM", hm)
    monkeypatch.setattr(ed, "OUT", str(out_path))
    monkeypatch.setattr("sys.argv", ["evolve_decay.py", "--write"])
    ed.main()
    assert out_path.exists()
    assert "decayed" in out_path.read_text(encoding="utf-8")
    # 状态列 draft → decayed 已写回
    assert "| decayed |" in (tmp_path / "factors.md").read_text(encoding="utf-8")
