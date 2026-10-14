# -*- coding: utf-8 -*-
"""守卫：factor-screen-results.md 的段写入必须幂等（同一段标题只保留一份）。

背景：MT-10 段曾因 crude_factor_check.py 每次运行都无条件追加而重复两次
（evolution/factor-screen-results.md 出现两个 `## MT-10 ...` 标题）。
本测试用 tmp_path 构造输入，不碰真实产物。
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_module():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location(
        "crude_factor_check", REPO / "scripts" / "crude_factor_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TITLE = "## MT-10 原油候选因子实检（2026-10-14）"
SECTION = "\n".join([
    "---",
    "",
    TITLE,
    "",
    "按先验固定判据执行。",
    "",
    "**C-1 判定：未通过**",
    "",
])


def test_write_section_twice_keeps_single_copy(tmp_path):
    """同一输入连续写两次 ⇒ 文件里该标题只出现一次。"""
    mod = _load_module()
    path = tmp_path / "results.md"

    mod.write_section(str(path), SECTION, TITLE)
    mod.write_section(str(path), SECTION, TITLE)

    text = path.read_text(encoding="utf-8")
    assert text.count(TITLE) == 1, f"标题重复 {text.count(TITLE)} 次：\n{text}"


def test_write_section_rerun_replaces_old_content(tmp_path):
    """重跑时以最新结果替换旧段（不残留旧段）。"""
    mod = _load_module()
    path = tmp_path / "results.md"

    first = "---\n\n" + TITLE + "\n\n旧结果 A\n"
    second = "---\n\n" + TITLE + "\n\n新结果 B\n"
    mod.write_section(str(path), first, TITLE)
    mod.write_section(str(path), second, TITLE)

    text = path.read_text(encoding="utf-8")
    assert text.count(TITLE) == 1
    assert "新结果 B" in text
    assert "旧结果 A" not in text


def test_write_section_preserves_other_content(tmp_path):
    """写新段不得破坏文件中其它已有内容（如 factor_screen.py 的产出）。"""
    mod = _load_module()
    path = tmp_path / "results.md"
    path.write_text("# 因子库扩展初检\n\n已有内容 KEEP-ME\n", encoding="utf-8")

    mod.write_section(str(path), SECTION, TITLE)

    text = path.read_text(encoding="utf-8")
    assert "KEEP-ME" in text
    assert text.count(TITLE) == 1
