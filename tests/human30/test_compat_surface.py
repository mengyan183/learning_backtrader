# -*- coding: utf-8 -*-
"""兼容面守卫：fg_system.human30 必须暴露 v1 的全部名字。

评审 C-4：v1 文件与 v2 包同名 ⇒ 迁移时若 re-export 漏名，
会静默回归（调用点拿到 AttributeError）。本测试把"漏名"变成红灯。
"""
import pytest

V1_NAMES = [
    "DATA_PATH", "QUADRANTS", "LABELS", "LEVELS", "QUESTIONS", "LIKERT_SCORES",
    "answers_to_scores", "record_from_answers", "record", "latest", "history",
    "aggregate", "advice", "brief_line", "days_since_last", "window_stats",
    "to_csv", "insight_summary",
    "_load", "_save",
]


@pytest.mark.parametrize("name", V1_NAMES)
def test_v1_surface_present(name):
    from fg_system import human30
    assert hasattr(human30, name), "兼容面缺失：%s" % name


def test_human30_is_package_not_module():
    """迁移后 human30 必须是包（有 __path__），否则说明还是 v1 单文件。"""
    from fg_system import human30
    assert hasattr(human30, "__path__"), "human30 仍是单文件模块 ⇒ 迁移未完成"


def test_data_path_is_repo_root_Data_dir():
    """数据路径必须是 <repo_root>/Data/human30.json。

    锚定**独立不变量**（仓库根的特征），而非与实现同构的 dirname 链 ——
    否则"实现改层数、测试跟着改层数"会双绿但双错。
    """
    import os
    from fg_system import human30

    p = os.path.abspath(human30.DATA_PATH)
    assert os.path.basename(p) == "human30.json"
    data_dir = os.path.dirname(p)
    assert os.path.basename(data_dir) == "Data"
    repo_root = os.path.dirname(data_dir)
    assert os.path.isdir(os.path.join(repo_root, "fg_system"))
    assert os.path.isfile(os.path.join(repo_root, ".gitignore"))


def test_gitignore_is_non_empty():
    """守卫弱点修正（P1 评审）：只查 .gitignore 存在不够 —— 空文件也能过。

    这里改为断言它**非空**且含 Data 相关忽略项。
    """
    import os
    from fg_system import human30
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(human30.__file__))))
    gi = os.path.join(repo_root, ".gitignore")
    assert os.path.isfile(gi)
    with open(gi, encoding="utf-8") as f:
        text = f.read()
    assert len(text.strip()) > 0, ".gitignore 为空 ✗"
    assert "Data/" in text, ".gitignore 未忽略 Data/ ✗"


def test_assess_surface_present():
    """P2 新增：assess 的公开名必须可从包访问。"""
    from fg_system import human30
    assert hasattr(human30, "assess"), "包未 re-export assess"
    for name in ("judge_level", "judge_all", "judge_phase",
                 "judge_traits", "phase_label"):
        assert hasattr(human30.assess, name), "assess 缺：%s" % name
