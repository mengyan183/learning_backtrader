#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_guarded：给每日链的**每一步**套一个硬超时（2026-10-29）。

【为什么】每日链是 `com.xingguo.fg-daily.plist` 里**一整条 `;` 串行**的 shell
字符串（约 20 条命令）✗ —— 任何一步卡住，**后面全部不执行** ✗。
2026-10-28 实测：富途 SDK 无界重连，把 05:30 起的链卡到 08:27 再无声息 ✗
⇒ 排在后面的 `invest_research.py`（投研简报）根本没轮到 ✗，用户两天没收到 ✗。

逐脚本加 `signal.alarm` 要改 10+ 个文件 ✗ ⇒ 这里做**一个通用包装器** ✓，
plist 里把每条命令套一层即可 ✓。

用法：
    .venv/bin/python scripts/run_guarded.py 600 .venv/bin/python scripts/foo.py --bar
    .venv/bin/python scripts/run_guarded.py 600 .venv/bin/python -c "print(1)"

退出码：**原样透传子进程退出码** ✓；超时 ⇒ `124`（与 coreutils `timeout` 一致）✓。
`start_new_session` + 杀**整个进程组** ✓ —— 子进程再派生的孙进程也一起收掉 ✗
（富途 SDK 的重连线程就是这样躲过 `proc.kill()` 的 ✗）。
"""
import os
import signal
import subprocess
import sys
import time


def _kill_tree(proc):
    """杀整个进程组；Windows 无 `killpg` ⇒ 退回单进程 `kill` ✓。"""
    if hasattr(os, "killpg"):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run(limit, cmd):
    """跑 `cmd`，最多 `limit` 秒。返回退出码（超时 124）。"""
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, start_new_session=True)
    except OSError as exc:
        print("[guard] 启动失败：%s" % exc, file=sys.stderr)
        return 127
    try:
        rc = proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        print("[guard] ⏱ %s 超过 %g 秒 ⇒ 已强杀（rc=124）"
              % (os.path.basename(cmd[0]), limit), file=sys.stderr)
        return 124
    print("[guard] %s rc=%d %.1fs" % (os.path.basename(cmd[0]), rc,
                                      time.time() - t0))
    return rc


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) < 3:
        print("用法: run_guarded.py <秒> <命令> [参数...]", file=sys.stderr)
        return 2
    try:
        limit = float(argv[1])
    except ValueError:
        print("[guard] 超时必须是数字：%r" % argv[1], file=sys.stderr)
        return 2
    if limit <= 0:
        print("[guard] 超时必须 > 0：%r" % argv[1], file=sys.stderr)
        return 2
    return run(limit, argv[2:])


if __name__ == "__main__":
    sys.exit(main())
