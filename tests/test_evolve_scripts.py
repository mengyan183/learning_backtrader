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
