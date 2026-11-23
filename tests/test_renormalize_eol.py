# -*- coding: utf-8 -*-
"""`scripts/renormalize_eol.py` 的路径白名单（2026-11-23）。

为什么要有：这个脚本会在 Mac 上执行 `git add` + `git commit` + `git push` ✗
若路径校验被绕过，等于给了一个「任意提交」的出口 ✗
⇒ 必须锁住「只动 docs/ 下的 .md」这条边界 ✓
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import renormalize_eol as rn  # noqa: E402


def test_accepts_docs_md():
    ok, why = rn.valid_path("docs/trading-discipline.md")
    assert ok, why


def test_rejects_non_docs_prefix():
    for p in ("fg_system/config.py", "scripts/run_task_queue.py",
              "tests/test_x.py", ".codebuddy/WORK-CONVENTIONS.md"):
        ok, why = rn.valid_path(p)
        assert ok is False and "docs/" in why, (p, why)


def test_rejects_non_md_extension():
    ok, why = rn.valid_path("docs/mac-tasks.txt")
    assert ok is False and ".md" in why, why


def test_rejects_traversal_and_absolute():
    for p in ("../docs/x.md", "docs/../fg_system/config.py", "/etc/passwd"):
        ok, _ = rn.valid_path(p)
        assert ok is False, p


def test_dirty_files_never_block(monkeypatch):
    """**任何**脏文件都不得挡住 renormalize ✓。

    🔴 2026-11-23 实测两轮失败：
       ① 先撞 `Data/`（简报索引 / chroma / 实时 state）
       ② 再撞 `docs/decision-log.md` + `evolution/memory/*` + `portfolio-oos.*`
       这些都是**每日链自动写**的 ⇒ 常态为脏 ⇒ 拒绝逻辑让脚本永远跑不了 ✗
    ⇒ 且提交已用 **pathspec**（`git commit -m msg -- <path>`）⇒ 别的脏文件
       本来就进不了这次提交 ⇒ 守卫纯属多余 ✗
    """

    # ⚠️ `_git` 返回的是 `(rc, stdout, stderr)` **三元组**（不是对象）✗
    monkeypatch.setattr(
        rn, "_git",
        lambda *a, **k: (0, " M scripts/other.py\n M docs/decision-log.md\n"
                            " M evolution/memory/2026-10-20.md\n"
                            " M Data/crypto_state.json\n", ""))
    res = rn.main(["--dry-run"])
    assert res.get("ok") is True, res


def test_default_path_is_discipline_doc(monkeypatch):
    """**无参数**调用必须默认规范化 `trading-discipline.md` ✓。

    🔴 2026-11-23 实测：`run_script` 的 `args` **必须是数组** ✗，而
       `dispatch_task.py --param` 只能传字符串 ⇒ 传参必然 rc=1 失败 ✗
       ⇒ 队列只能用「无参数」方式调用，默认值必须就是目标行为 ✓
    """
    seen = {}

    def _vp(p):
        seen["p"] = p
        return False, "stop-here"

    monkeypatch.setattr(rn, "valid_path", _vp)
    rn.main(["--dry-run"])
    assert seen["p"] == "docs/trading-discipline.md", seen


def test_rejects_missing_file():
    ok, why = rn.valid_path("docs/__not_exist__.md")
    assert ok is False and "不存在" in why, why
