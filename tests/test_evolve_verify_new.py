#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WT-04 新假说验证骨架（H-030/H-031/H-033）测试。

覆盖：
  - `--help` 可运行（退出码 0，含用法说明）；
  - dry-run 退出码 0 且输出含「等待样本积累」；
  - 正常检：样本不足时退出码 0 且输出含「等待样本积累（n/阈值）」；
  - 不依赖绝对路径：脚本不得硬编码仓库绝对路径 / 绝对路径 read_csv；
  - 脚本自带 stdout utf-8 设置（§6.2 第 4 条）。
"""
import ast
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "evolve_verify_new.py")


def _run(*argv):
    return subprocess.run(
        [sys.executable, SCRIPT, *argv],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def test_help_runs():
    """`--help` 必须可运行且打印用法。"""
    r = _run("--help")
    assert r.returncode == 0, "反例输出：%s" % r.stderr[-500:]
    assert "usage" in r.stdout.lower() or "用法" in r.stdout
    assert "--dry-run" in r.stdout


def test_dry_run_exits_zero_and_waits_for_samples():
    """dry-run 退出码 0，且输出含「等待样本积累」。"""
    r = _run("--dry-run")
    assert r.returncode == 0, "反例输出：%s" % r.stderr[-500:]
    assert "等待样本积累" in r.stdout


def test_normal_run_exits_zero_with_n_over_threshold():
    """正常检：样本不足时 exit 0，并输出「等待样本积累（n/阈值）」。"""
    r = _run()
    assert r.returncode == 0, "反例输出：%s" % r.stderr[-500:]
    assert "等待样本积累" in r.stdout
    # 形状：n/阈值
    assert "/" in r.stdout


def test_all_three_hypotheses_covered():
    """一个骨架必须覆盖三条假说，而不是只处理一条。"""
    r = _run("--dry-run")
    for hid in ("H-030", "H-031", "H-033"):
        assert hid in r.stdout, "输出缺少 %s" % hid


def test_no_absolute_path_literals_or_read_csv_absolute():
    """脚本不得硬编码绝对路径，也不得用绝对路径 read_csv。

    判据：AST 字符串常量中不出现盘符路径（如 `C:\\` / `D:/`）或仓库绝对根路径。
    另：不得存在 `read_csv(<绝对路径>)` 调用。
    """
    src = open(SCRIPT, encoding="utf-8").read()
    tree = ast.parse(src)
    lits = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for s in lits:
        assert not os.path.isabs(s), "脚本硬编码了绝对路径：%r" % s
        # Windows 盘符路径（正斜杠写法，os.path.isabs 在非 Windows 收集机不认）
        assert not (len(s) >= 3 and s[1] == ":" and s[2] in ("/", "\\")), \
            "脚本硬编码了盘符路径：%r" % s
    # read_csv / open 不得直接吃到绝对路径字面量做数据读取
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name in ("read_csv", "read_excel"):
                first = node.args[0]
                assert not (isinstance(first, ast.Constant)
                            and isinstance(first.value, str)
                            and os.path.isabs(first.value)), \
                    "read_csv 收到绝对路径字面量"


def test_data_paths_come_from_config():
    """数据路径必须来自 fg_system.config 常量。"""
    src = open(SCRIPT, encoding="utf-8").read()
    assert "from fg_system import config" in src
    assert "config.RAW_DIR" in src or "config.DATA_DIR" in src, \
        "数据路径必须取自 config 常量"


def test_forces_utf8_stdout():
    """§6.2 第 4 条：脚本自带 stdout utf-8 设置。"""
    src = open(SCRIPT, encoding="utf-8").read()
    assert "reconfigure" in src, "脚本没有把 stdout 固定为 UTF-8"
    assert 'encoding="utf-8"' in src, "reconfigure 必须显式指定 utf-8"


def test_states_documented_in_source():
    """状态机注释齐全（open → verifying → adopted/falsified）。"""
    src = open(SCRIPT, encoding="utf-8").read()
    for state in ("open", "verifying", "adopted", "falsified"):
        assert state in src, "状态机注释缺少 %s" % state
