# -*- coding: utf-8 -*-
"""控制台编码守卫。

【背景（2026-09-23 实测踩到）】
Windows 控制台默认 **GBK**，而本系统大量用 `✅` / `❌` / `⚠️` 做输出标记 ——
这三个字符 **GBK 编不了**，一 `print` 就 `UnicodeEncodeError` 把进程打挂：

    $ python scripts/check_deploy_set.py
    UnicodeEncodeError: 'gbk' codec can't encode character '\\u26a0'

实测波及 **13 个文件**，含每天要跑的 `serve_dashboard.py`。
修法在 `fg_system/__init__.py` 的 `_make_console_safe()`。
"""
import os
import subprocess
import sys

import pytest

from fg_system import config

# GBK 编不了的符号 —— 正是会崩的那几个（✅ ❌ ⚠️）
DANGEROUS = "\u2705\u274c\u26a0\ufe0f"


def test_dangerous_symbols_really_are_gbk_unsafe():
    """**前提校验**：这些符号确实编不了 GBK。

    若哪天控制台全变 UTF-8，这条会失败 —— 那说明本守卫的**前提没了**，
    应当删掉整个文件，而不是留一堆永不触发的空测试。
    """
    for ch in DANGEROUS:
        with pytest.raises(UnicodeEncodeError):
            ch.encode("gbk")


def _run(code, encoding):
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)          # 别让外部设置把问题掩盖掉
    env["PYTHONIOENCODING"] = encoding
    return subprocess.run([sys.executable, "-c", code], cwd=config.ROOT,
                          capture_output=True, env=env)


def test_prints_symbols_under_gbk_console():
    """**核心守卫**：GBK 控制台下 print ✅/❌/⚠️ **不得崩**。

    这正是用户实际踩到的崩法 —— 复现它，保证不再回归。
    """
    out = _run("import fg_system; print('\u2705 \u274c \u26a0\ufe0f \u4e2d\u6587')\n",
               "gbk")
    assert out.returncode == 0, (
        "GBK 控制台下崩了：\n%s" % out.stderr.decode("utf-8", "replace"))


def test_gbk_console_without_import_still_crashes():
    """**对照**：不 import `fg_system` 时应当**照旧崩**。

    证明上一条的通过确实来自我们的修复，而不是这个环境本来就不还原问题。
    没有对照组，上一条可能只是"恰好没崩"。
    """
    out = _run("print('\u26a0\ufe0f')\n", "gbk")
    assert out.returncode != 0, "对照没崩 —— 说明本环境不还原该问题，守卫是假的"


def test_utf8_console_unaffected():
    """UTF-8 控制台下符号要**原样保留** —— 不能被降级成 `?`。"""
    out = _run("import fg_system; print('\u2705 \u4e2d\u6587')\n", "utf-8")
    assert out.returncode == 0
    assert "\u2705 \u4e2d\u6587" in out.stdout.decode("utf-8")


def test_importing_fg_system_does_not_break_stdout():
    """修复不能有副作用：正常输出照旧。"""
    import fg_system  # noqa: F401
    print("正常输出")
    assert sys.stdout is not None
