# -*- coding: utf-8 -*-
"""`run_guarded.py`：每日链每一步的硬超时（2026-10-29）。

【背景】每日链是 plist 里一整条 `;` 串行的 shell 字符串 ✗ —— 任何一步卡住，
**后面全部不执行** ✗（2026-10-28 富途 SDK 无界重连，把投研简报拖停两天 ✗）。
逐脚本加 `signal.alarm` 要改 10+ 个文件 ✗ ⇒ 通用包装器 ✓。
"""
import importlib.util
import os
import sys
import time

from fg_system import config

_SPEC = os.path.join(config.ROOT, "scripts", "run_guarded.py")


def _load():
    spec = importlib.util.spec_from_file_location("run_guarded", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_timeout_kills_and_returns_124():
    """超时必须**强杀**并返回 124 ✓（与 coreutils `timeout` 一致）。"""
    rg = _load()
    t0 = time.time()
    rc = rg.run(0.5, [sys.executable, "-c", "import time; time.sleep(30)"])
    took = time.time() - t0
    assert rc == 124, "超时应返回 124，实际 %r ✗" % rc
    assert took < 10, "没有真的杀掉子进程（耗时 %.1fs）✗" % took


def test_exit_code_passes_through():
    """子进程退出码**原样透传** ✓（链上靠它判断成败）。"""
    rg = _load()
    assert rg.run(10, [sys.executable, "-c", "raise SystemExit(3)"]) == 3
    assert rg.run(10, [sys.executable, "-c", "print('ok')"]) == 0


def test_bad_args():
    """参数不对 ⇒ 2（不要静默当成功 ✗）。"""
    rg = _load()
    assert rg.main(["run_guarded.py"]) == 2
    assert rg.main(["run_guarded.py", "abc", "echo"]) == 2
    assert rg.main(["run_guarded.py", "0", "echo"]) == 2


def test_daily_plist_wraps_every_python_call():
    """每日链**每条** `.venv/bin/python` 调用都必须套上护栏 ✓。

    只包一部分等于没包 ✗ —— 没包的那步照样能把整条链拖死 ✗。
    """
    import plistlib
    with open(os.path.join(config.ROOT, "scripts",
                           "com.xingguo.fg-daily.plist"), "rb") as fh:
        cmd = plistlib.load(fh)["ProgramArguments"][-1]
    n_py = cmd.count(".venv/bin/python ")
    n_guard = cmd.count("run_guarded.py ")
    assert n_guard > 0, "每日链完全没套护栏 ✗"
    assert n_guard * 2 == n_py, \
        "有 %d 条命令没套护栏（调用 %d / 护栏 %d）✗" % (n_py - n_guard * 2, n_py, n_guard)
