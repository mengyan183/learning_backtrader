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
import json
import os
import signal
import subprocess
import sys
import time

#: 🔴 失败台账 ✓（2026-11-03 用户要求「每日链每步失败即告警」）
#: 为什么写文件而不是当场发飞书 ✗：
#:   ① 链是 `;` 串行 ✗ 某步失败时**后面还有 10 步** ✗ 当场发会刷屏 ✗
#:   ② `run_guarded` 不该耦合飞书 SDK ✗
#: ⇒ 写台账 ✓ 链末由 `report_daily_failures.py` **汇总发一条** ✓
FAIL_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Data", "daily_failures.jsonl")


def _label(cmd):
    """给命令起一个**可辨识**的短名 ✓（2026-11-03 修）。

    🔴 原实现用 `os.path.basename(cmd[0])` ✗ —— 而每日链的命令是
       `.venv/bin/python scripts/foo.py ...` 或 `.venv/bin/python -c "..."` ✗
       ⇒ basename 永远是 **`python`** ✗
       ⇒ 日志里全是 `[guard] python rc=2` ✗ **看不出是哪一步** ✗
       （2026-11-03 实测：21 个 `[guard]` 全是 `python` ✗ 完全无法定位 ✗）

    ⇒ 取**第一个 `.py` 参数** ✓；`-c` 则取代码前 40 字 ✓
    """
    for a in cmd[1:]:
        if a.endswith(".py"):
            return os.path.basename(a)
    if "-c" in cmd:
        i = cmd.index("-c")
        if i + 1 < len(cmd):
            return "-c " + cmd[i + 1][:40].replace("\n", " ")
    return os.path.basename(cmd[0]) if cmd else "?"


def _record_failure(rc, cmd, seconds, timeout=False):
    """把一次失败追加进台账 ✓ —— 写不进去也**不能让链挂** ✗。"""
    try:
        os.makedirs(os.path.dirname(FAIL_LOG), exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "cmd": " ".join(os.path.basename(c) if i == 0 else c
                            for i, c in enumerate(cmd))[:200],
            "rc": rc,
            "seconds": round(seconds, 1),
            "timeout": bool(timeout),
        }
        with open(FAIL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:                # noqa: BLE001
        print("[guard] 失败台账写不进去：%s" % exc, file=sys.stderr)


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
              % (_label(cmd), limit), file=sys.stderr)
        _record_failure(124, cmd, time.time() - t0, timeout=True)
        return 124
    secs = time.time() - t0
    print("[guard] %s rc=%d %.1fs" % (_label(cmd), rc, secs))
    # 🔴 2026-11-03：**非 0 退出就记台账** ✓ —— 原来只打印一行 ✗
    #    而 `prices.csv` 断流 22 天正是「每天 rc≠0 但没人看」✗
    if rc != 0:
        print("[guard] ⚠️ %s **失败** rc=%d（已记入 daily_failures.jsonl）"
              % (_label(cmd), rc), file=sys.stderr)
        _record_failure(rc, cmd, secs)
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
