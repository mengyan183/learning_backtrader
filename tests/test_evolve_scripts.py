#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C 系列编排脚本 smoke 测试：确保脚本可导入、解析函数行为正确（不写文件、不跑全量回测）。

覆盖：
  - evolve_decay.parse_factor_rows：正确处理 \| 转义（防分列错位回归）
  - evolve_approve.scan_pending：扫描未审批提案
  - execution_confirm.build_rows：持仓→动作映射
  - attribution_check / evolve_weekly：主模块可导入（语法与 import 路径正确）
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")


def test_evolve_decay_parse(tmp_path=None):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evolve_decay", os.path.join(SCRIPTS, "evolve_decay.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = ("| F-001 | 2026-10-02 | 名称 | 逆向 | 方法 | \\|ICIR\\|>=0.5 | draft | 备注 5 日近窗衰减⚠ |\n")
    rows = mod.parse_factor_rows(text)
    assert len(rows) == 1
    assert rows[0]["id"] == "F-001"
    assert rows[0]["status"] == "draft"   # 未被 \| 转义拆裂
    assert rows[0]["note"] == "备注 5 日近窗衰减⚠"
    assert mod.decay_horizons(rows[0]["note"])[0] == 1


def test_evolve_approve_scan():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evolve_approve", os.path.join(SCRIPTS, "evolve_approve.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pend = mod.scan_pending()
    # V-H7 三份提案应已审批（本脚本运行后），不再出现在 pending
    for p in pend:
        assert "审批记录：" not in open(p["path"], encoding="utf-8").read()
    assert isinstance(pend, list)


def test_execution_confirm_rows():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "execution_confirm", os.path.join(SCRIPTS, "execution_confirm.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.build_rows()
    assert isinstance(rows, list) and len(rows) > 0
    for r in rows:
        assert r["sym"]
        assert "action" in r
        assert "pnl" in r


def test_scripts_importable():
    for name in ("attribution_check", "evolve_weekly", "evolve_walkforward"):
        r = subprocess.run(
            [sys.executable, "-c",
             "import importlib.util as u, os;"
             "s=u.spec_from_file_location('%s', os.path.join(%r, '%s.py'));"
             "m=u.module_from_spec(s); s.loader.exec_module(m); print('ok')"
             % (name, SCRIPTS, name)],
            capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, "%s import 失败: %s" % (name, r.stderr[-500:])
        assert "ok" in r.stdout


# ------------------------- evolve_verify 写回表格（2026-10-19 修 3 个 bug 的回归）
_HDR = ("| id | 日期 | 假设 | 判据 | 数据 | 状态 | 备注 |\n"
        "|---|---|---|---|---|---|---|\n")


def _load_verify():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evolve_verify", os.path.join(SCRIPTS, "evolve_verify.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_evolve_verify_escaped_pipe_keeps_columns(tmp_path, monkeypatch):
    """备注含 `\\|` 时不得索引错位（旧实现用朴素 split ⇒ 状态会写进备注列 ✗）。"""
    vh = _load_verify()
    p = tmp_path / "hypotheses.md"
    p.write_text(_HDR + "| H-999 | 2026-10-01 | 假设 | 取 \\|x\\|=1 | 数据 | open | 旧备注 |\n",
                 encoding="utf-8")
    monkeypatch.setattr(vh, "HYP", str(p))
    vh.update_hypotheses([{"id": "H-999", "status": "falsified",
                           "evidence": "实测", "note": ""}])
    cells = vh._row_cells(p.read_text(encoding="utf-8").splitlines()[-1])
    assert len(cells) == vh.HYP_COLS
    assert cells[5] == "falsified"        # 状态列
    assert "旧备注" in cells[6]            # 备注列
    assert vh.check_table_structure() == 0


def test_evolve_verify_bare_pipe_in_evidence_is_escaped(tmp_path, monkeypatch):
    """证据里的裸 `|`（如 `|均值|`）写前必须转义，否则切坏表格 ✗。"""
    vh = _load_verify()
    p = tmp_path / "hypotheses.md"
    p.write_text(_HDR + "| H-999 | 2026-10-01 | 假设 | 判据 | 数据 | open | 备注 |\n",
                 encoding="utf-8")
    monkeypatch.setattr(vh, "HYP", str(p))
    vh.update_hypotheses([{"id": "H-999", "status": "adopted",
                           "evidence": "BTC 日收益|均值|=0.0127", "note": ""}])
    body = p.read_text(encoding="utf-8").splitlines()[-1]
    assert len(vh._row_cells(body)) == vh.HYP_COLS
    assert "\\|均值\\|" in body
    assert vh.check_table_structure() == 0


def test_evolve_verify_same_day_overwrites_note(tmp_path, monkeypatch):
    """同一日期重跑 ⇒ 覆盖当日条目（旧实现「写过就锁死」⇒ 日报永远是第一次的数字 ✗）。"""
    vh = _load_verify()
    p = tmp_path / "hypotheses.md"
    p.write_text(_HDR + "| H-998 | 2026-10-01 | 假设 | 判据 | 数据 | open | 备注 |\n",
                 encoding="utf-8")
    monkeypatch.setattr(vh, "HYP", str(p))
    for ev in ("第一次", "第二次"):
        vh.update_hypotheses([{"id": "H-998", "status": "adopted",
                               "evidence": ev, "note": ""}])
    body = p.read_text(encoding="utf-8").splitlines()[-1]
    assert "第二次" in body
    assert "第一次" not in body
    assert body.count("验证：") == 1


def test_evolve_verify_current_status_reads_table(tmp_path, monkeypatch):
    """`current_status` 供 main() 跳过已归档/已判伪（避免日报传播过时理由 ✗）。"""
    vh = _load_verify()
    p = tmp_path / "hypotheses.md"
    p.write_text(_HDR
                 + "| H-997 | 2026-10-01 | 假设 | 判据 | 数据 | archived | 备注 |\n"
                 + "| H-996 | 2026-10-01 | 假设 | 判据 | 数据 | open（修订口径） | 备注 |\n",
                 encoding="utf-8")
    monkeypatch.setattr(vh, "HYP", str(p))
    st = vh.current_status()
    assert st["H-997"] == "archived"
    assert st["H-996"] == "open"
