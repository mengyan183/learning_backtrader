# -*- coding: utf-8 -*-
"""富途 OpenD 连接健康：**端口预检 + 硬超时 + 状态落盘**（2026-10-29）。

【为什么】2026-10-28 每日链卡死在 futu SDK 的**自动重连循环**里 ✗ ——
`/tmp/fg_daily.log` 每 30 秒一条 `open_context_base.py:408 _init_connect_sync:
init connect fail`，从 05:30 连刷到 08:27 再无声息 ✗ ⇒ 链是 `;` 串行 ⇒
后面的 `invest_research.py`（投研简报）**根本没轮到** ✗，用户连续两天收不到 ✗。

SDK 的重连不受我们代码控制 ✗（`MAX_RETRY` 只管单次查询），所以三道防线：

1. `preflight()` —— 先用 **2 秒 socket** 探 OpenD 端口 ✓，连不上就**立刻退出** ✓
   （绝不进 SDK ✗，一进就是死循环 ✗）；
2. `guard()` —— `signal.alarm` **硬超时** ✓，到点直接 `os._exit(0)`，
   不陪 SDK 线程耗 ✗；
3. `write_status()` —— 状态落盘 ✓，`invest_research.py` 读它在简报里明说 ✓
   （「连接有问题」必须**被看见**，而不是安静地少一段 ✗）。
"""
import datetime as dt
import json
import os
import socket

from fg_system import config

OPEND_HOST = "127.0.0.1"
OPEND_PORT = 11111
STATUS_PATH = os.path.join(config.DATA_DIR, "health", "futu.json")
#: 单步硬超时（秒）—— 富途正常查询一次 < 5s，180s 足够跑完整段
MAX_SECONDS = 180


def preflight(timeout=2.0):
    """OpenD 端口通不通。**不 import futu、不建 context** ✓。

    :returns: ``(ok, 说明)``
    """
    addr = "%s:%d" % (OPEND_HOST, OPEND_PORT)
    try:
        sock = socket.create_connection((OPEND_HOST, OPEND_PORT), timeout)
        sock.close()
        return True, "OpenD %s 可连" % addr
    except OSError as exc:
        return False, "OpenD %s 连不上（%s）" % (addr, exc)


def write_status(ok, reason, step=""):
    """状态落盘（简报据此说明数据源是否可信）✓。"""
    rec = {"ok": bool(ok), "reason": reason, "step": step,
           "at": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
        with open(STATUS_PATH, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return rec


def read_status():
    """读上次落盘的状态；没有则返回 None ✓（简报按「未知」处理 ✓）。"""
    try:
        with open(STATUS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def guard(seconds=MAX_SECONDS, step=""):
    """`signal.alarm` 硬超时：到点落盘 + `os._exit(0)`，**不拖死整条链** ✓。

    非 POSIX（Windows）没有 `signal.alarm` ⇒ 返回 False，调用方照常跑 ✓。
    """
    import signal
    try:
        signal.signal(signal.SIGALRM, _make_boom(seconds, step))
        signal.alarm(int(seconds))
        return True
    except (AttributeError, ValueError, OSError):
        return False


def _make_boom(seconds, step):
    def _boom(signum, frame):                      # noqa: ARG001
        write_status(False, "超过 %d 秒未完成（疑似 SDK 重连循环）" % seconds, step)
        print("[futu] ⏱ 超过 %d 秒仍未完成 ⇒ 放弃本步（已记入健康状态）" % seconds)
        # 🔴 直接退，不等 SDK 的后台线程 ✓ —— 它会一直重连，join 就是卡死 ✗
        os._exit(0)
    return _boom


def done():
    """取消定时器（正常跑完时调用）✓。"""
    import signal
    try:
        signal.alarm(0)
    except AttributeError:
        pass
