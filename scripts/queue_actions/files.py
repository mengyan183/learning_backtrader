# -*- coding: utf-8 -*-
"""文件 / 仓库杂务 action ✓ —— 读尾巴、清理遗留、跑脚本/测试、同步运行副本。

【边界】
  · 只依赖 `queue_core`（`ROOT` / `run` / `safe_rel` / `READ_ALLOW` /
    `script_allowed` / `tail_logs`）+ 标准库 ✓
  · **不碰队列状态** ✗ —— `QUEUE` / `run_once` / flock 在调度器里
  · `_LEGACY_FILES`（`rm_legacy` 的删除白名单）随包走 ✓
"""
import os
import subprocess
import sys

from queue_core import (ROOT, READ_ALLOW as _READ_ALLOW, run as _run,
                        safe_rel as _safe_rel, script_allowed as _script_allowed,
                        tail_logs as _tail_logs)


def _act_cleanup_backlog(params):
    """把插件层 30 分钟前的历史文件挪进 archive（见 sync_health.archive_backlog）。"""
    from fg_system.dashboard import sync_health
    r = sync_health.archive_backlog()
    # 「没有够老的文件」= **成功**（无事可做）✓；「目录不存在」才是失败 ✗
    ok = bool(r.get("moved")) or "没有超过" in str(r.get("reason") or "")
    return dict(r, ok=ok)
#: 允许删除的**遗留文件白名单** ✓（防任意路径删除 ✗）


_LEGACY_FILES = {
    # 🔴 2026-11-13 用户确认：hermes 已改付费 `deepseek-flash`，
    #    `our-free-model` 这个免费模型目录整体废弃 ✗
    #    ⇒ 该文件不再刷新是**预期**，之前被误当成 `dsh.web` 的心跳 ✗
    "free_model_availability": "~/.dsh/our-free-model/availability.json",
}


def _act_rm_legacy(params):
    """删除**白名单内**的遗留文件 ✓（2026-11-13 用户要求）

    🔴 为什么需要：`~/.dsh/our-free-model/availability.json` 是
       免费模型时代的遗留 ✗ —— hermes 已改付费 `deepseek-flash` ✓
       它留在磁盘上会被误当成「服务心跳」，之前就害得 `dsh.web` 误报 ✗

    ⚠️ **只允许 `_LEGACY_FILES` 白名单** ✗ —— 不接受任意路径 ✓
    """
    import glob as _g
    key = str(params.get("key") or "free_model_availability")
    rel = _LEGACY_FILES.get(key)
    if not rel:
        return {"ok": False,
                "error": "未知 key `%s`（白名单：%s）"
                         % (key, "、".join(sorted(_LEGACY_FILES)))}
    p = os.path.expanduser(rel)
    out = {"key": key, "path": p, "steps": {}}
    try:
        if os.path.exists(p):
            os.remove(p)
            out["steps"]["removed"] = True
        else:
            out["steps"]["removed"] = False
            out["steps"]["note"] = "文件本来就不存在 ✓"
    except OSError as exc:
        return {"ok": False, "error": "删除失败：%s: %s"
                                     % (type(exc).__name__, str(exc)[:200])}
    # 目录若已空 ⇒ 一并删掉（`our-free-model` 整个模块都废弃了）
    d = os.path.dirname(p)
    try:
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            out["steps"]["dir_removed"] = d
    except OSError:
        pass
    # 附带确认：还有没有别的残留
    out["steps"]["leftover"] = [os.path.basename(x) for x in
                                _g.glob(os.path.join(d, "*"))][:10]
    out["ok"] = True
    return out


def _act_run_script(params):
    """跑**白名单内**的 `scripts/*.py` 并回传 stdout/stderr ✓。

    参数：
      - `script`：脚本文件名（必须在 `_SCRIPT_ALLOWED` 里）
      - `args`：字符串数组，原样传给脚本（可选）
      - `timeout`：秒数（默认 900，最大 1800）

    🔴 安全边界 ✗：
      · 脚本名必须在白名单 ⇒ 不能跑任意路径 ✗
      · `cwd=ROOT` ⇒ 脚本的相对路径行为与手动跑一致 ✓
      · 用 `sys.executable`（队列自己的 venv）⇒ 依赖一致 ✓
      · **不拼接 shell** ⇒ `args` 原样传参，无注入面 ✓
    """
    script = str(params.get("script") or "").strip()
    allowed = _script_allowed()
    if script not in allowed:
        return {"ok": False,
                "error": "不允许的脚本：`%s` ✗（白名单 = scripts/queue_allow/*.py：%s）"
                         % (script, ", ".join(sorted(allowed)))}
    path = os.path.join(ROOT, "scripts", script)
    if not os.path.isfile(path):
        return {"ok": False, "error": "脚本不存在：%s" % path}
    raw_args = params.get("args") or []
    if not isinstance(raw_args, list):
        return {"ok": False, "error": "`args` 必须是数组 ✗"}
    args = [str(a) for a in raw_args]
    try:
        timeout = min(int(params.get("timeout") or 900), 1800)
    except (TypeError, ValueError):
        timeout = 900
    try:
        r = _run([sys.executable, path] + args, timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 %d 秒未完成" % timeout}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "script": script, "args": args,
            "stdout": (r.stdout or "")[-3000:],
            "stderr": (r.stderr or "")[-3000:]}


def _act_read_tail(params):
    """读文件末尾 N 行 ✓（2026-11-17 用户要求）

    🔴 背景：`fetch_putcall.py` 只报「无新数据」**不打印内容** ✗
       而本地 `putcall_daily_latest.csv` 只到 2026-10-12（Windows 不同步）✗
       ⇒ 无法验证简报的 `PUT-CALL 64.4` 是否合理 ✗
       ⇒ 需要能在 Mac 上「看一眼数据」的通用动作 ✓

    ⚠️ **白名单**：只允许 `Data/raw/`、`Data/features.csv`、`evolution/`、
       `docs/task-queue/` ✗ —— **刻意排除** `Data/accounts.csv` 和
       `Data/positions.csv`（含账户净值/持仓明细，不该出现在任务回执里）✗

    参数：
      - `path`：相对路径（必填）
      - `lines`：末尾行数（默认 10，上限 100）
    """
    rel = str(params.get("path") or "").strip().lstrip("/")
    if not rel:
        return {"ok": False, "error": "`path` 必填"}
    # 🔴 2026-11-19：改用 `_safe_rel`（原 `startswith` 可被 `..` 绕过 ✗）
    try:
        full = _safe_rel(rel, _READ_ALLOW)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        n = int(params.get("lines") or 10)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(n, 100))

    if not os.path.exists(full):
        return {"ok": False, "error": "文件不存在：%s" % rel}
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            alll = f.readlines()
    except OSError as exc:
        return {"ok": False, "error": "读取失败：%s" % str(exc)[:150]}

    tail = [x.rstrip("\n") for x in alll[-n:]]
    return {"ok": True, "path": rel, "total_lines": len(alll),
            "returned": len(tail), "lines": tail}


def _act_sync_runtime(params):
    """把仓库版 bypass 覆盖到运行时副本（见 sync_health.sync_runtime_copy）。"""
    from fg_system.dashboard import sync_health
    return sync_health.sync_runtime_copy()


def _act_daily_log_tail(params):
    """回传某个运行日志的尾巴 ✓。

    动机（2026-10-29）：简报连续两天没发，只能靠 `/tmp/fg_daily.log` 定位 ✗ ——
    而「让用户去 Mac 上敲命令」违反「Mac 侧操作一律走队列」✗。
    `which` 走白名单，`lines` 上限 200 ✓。
    """
    which = str(params.get("which") or "daily")
    try:
        logs = _tail_logs()
    except (OSError, ValueError) as exc:
        return {"ok": False, "reason": "读不到白名单 tail_logs.json：%s" % exc}
    path = logs.get(which)
    if not path:
        return {"ok": False,
                "reason": "未知日志 %r（可选：%s）" % (which, ", ".join(sorted(logs)))}
    try:
        n = max(1, min(int(params.get("lines") or 60), 200))
    except (TypeError, ValueError):
        n = 60
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tail = fh.readlines()[-n:]
    except OSError as exc:
        return {"ok": False, "reason": "读不到 %s：%s" % (path, exc)}
    return {"ok": True, "which": which, "path": path,
            "lines": len(tail), "tail": "".join(tail)}


def _act_run_pytest(params):
    """跑指定测试文件并回传尾部输出 ✓（参数 `files`，逗号分隔，默认全量）。"""
    files = [x.strip() for x in str(params.get("files") or "tests/").split(",")
             if x.strip()]
    try:
        r = _run([sys.executable, "-m", "pytest"] + files + ["-q"], 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "pytest 超过 900 秒"}
    tail = (r.stdout or "").strip().splitlines()[-40:]
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "failed": [ln for ln in tail if ln.startswith("FAILED")],
            "tail": "\n".join(tail)}

ACTIONS = {
    "run_script": _act_run_script,
    "rm_legacy": _act_rm_legacy,
    "read_tail": _act_read_tail,
    "daily_log_tail": _act_daily_log_tail,
    "run_pytest": _act_run_pytest,
    "cleanup_backlog": _act_cleanup_backlog,
    "sync_runtime": _act_sync_runtime,
}
