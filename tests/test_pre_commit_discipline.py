# -*- coding: utf-8 -*-
"""提交前**纪律门禁**的测试（`scripts/pre-commit-discipline.sh`）。

【为什么需要（§8 文档先行）】`docs/trading-discipline.md` 第 8 条要求
「文档 → 代码 → 回测 → 验证」顺序不可颠倒，而规则代码（`fg_system/signal/`、
`fg_system/models/`、`fg_system/config.py`）的改动会直接影响仓位与信号。
2026-10-27 起 Mac 侧要接 AI agent，Mac 又是**唯一能 push 的端** ⇒
「改了规则代码却没改文档」必须被机制拦住，不能只靠记录教训。

⚠️ 测试用**显式传参**模式（不依赖 git 暂存区）—— 脚本只做路径匹配，
不需要文件真实存在，所以不建临时文件。
"""
import os
import subprocess

from fg_system import config

HOOK = os.path.join(config.ROOT, "scripts", "pre-commit-discipline.sh")


def _run(*paths):
    # Windows 上 text=True 会用 GBK 解码 ⇒ 钩子中文输出解不开 ✗
    return subprocess.run(["bash", HOOK, *paths], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          cwd=config.ROOT)


def test_rule_code_without_docs_is_rejected():
    """**核心守卫**：只改规则代码、没改 docs ⇒ 拒绝（退出码 1）。"""
    r = _run("fg_system/signal/market_signal.py")
    assert r.returncode == 1, r.stdout
    assert "纪律门禁" in r.stdout
    assert "第 8 条" in r.stdout, "拒绝时必须指出依据，否则用户不知道找哪条纪律"


def test_config_py_counts_as_rule_code():
    """§8.3：参数改动与规则改动同等对待 ⇒ `config.py` 也受管。"""
    r = _run("fg_system/config.py")
    assert r.returncode == 1, r.stdout


def test_rule_code_with_docs_passes():
    """规则代码 + docs 变更 ⇒ 放行（退出码 0）。"""
    r = _run("fg_system/signal/market_signal.py", "docs/trading-discipline.md")
    assert r.returncode == 0, r.stdout


def test_models_dir_is_guarded():
    """`fg_system/models/` 同属规则代码。"""
    r = _run("fg_system/models/hmm.py")
    assert r.returncode == 1, r.stdout


def test_non_rule_code_passes():
    """非规则代码（看板/文档/测试）不受此门约束。"""
    assert _run("fg_system/dashboard/report.py").returncode == 0
    assert _run("tests/dashboard/test_report.py").returncode == 0
    assert _run("docs/NEXT-SESSION-windows.md").returncode == 0
