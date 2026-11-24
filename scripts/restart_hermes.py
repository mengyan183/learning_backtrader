#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测并尽力重启 Hermes（`127.0.0.1:8642`）✓（2026-11-24 用户要求）。

【背景】
  `evolve_review.py` 依赖 Hermes 的 `/v1/chat/completions` ✗
  实测 2026-11-24：`RuntimeError: Hermes(8642) 调用失败（2 次 × 90s）：timed out` ✗
  ⇒ 每日链白等 3 分钟，且假说登记/极端标记全部缺失 ✗

⚠️ **Hermes 是仓外服务**（配置在 `~/.hermes/.env`），本仓库**没有**它的启动入口 ✗
  ⇒ 本脚本只能：① 探端口 ② 在 `launchctl list` 里找 hermes 相关 label 并 kickstart
     ③ 找不到就**如实报告**，不猜启动命令 ✓

用法（Mac，经队列）：
    python scripts/restart_hermes.py
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time

HOST, PORT = "127.0.0.1", 8642


def _probe(timeout=3):
    """TCP 探端口 ⇒ (ok, 说明)。"""
    try:
        s = socket.create_connection((HOST, PORT), timeout=timeout)
        s.close()
        return True, "可连"
    except OSError as e:
        return False, "%s: %s" % (type(e).__name__, e)


def _http_probe(timeout=5):
    """真打一次 `/v1/models`（比 TCP 更能说明「服务活着」）✓。"""
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request("http://%s:%d/v1/models" % (HOST, PORT))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, "HTTP %s" % r.status
    except urllib.error.HTTPError as e:
        return True, "HTTP %s（服务在，可能需鉴权）" % e.code
    except Exception as e:                        # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:80])


def _launchd_labels():
    """`launchctl list` 里含 hermes 的 label ✓。"""
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True,
                           text=True, timeout=20)
        out = (r.stdout or "")
    except (subprocess.SubprocessError, OSError):
        return []
    return sorted({ln.split()[-1] for ln in out.splitlines()
                   if "hermes" in ln.lower() and ln.split()})


def _procs():
    """`ps aux` 里含 hermes 的进程（去掉 grep 自身）✓。"""
    try:
        r = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=20)
        out = (r.stdout or "")
    except (subprocess.SubprocessError, OSError):
        return []
    return [ln[:160] for ln in out.splitlines()
            if re.search(r"hermes", ln, re.I) and "grep" not in ln][:5]


def main():
    out = {"port": _probe()}
    if out["port"][0]:
        out["http"] = _http_probe()

    labels = _launchd_labels()
    out["launchd_labels"] = labels
    kicked = []
    if not out["port"][0]:
        for lb in labels:
            try:
                r = subprocess.run(
                    ["launchctl", "kickstart", "-k", "gui/%d/%s" % (os.getuid(), lb)],
                    capture_output=True, text=True, timeout=30)
                kicked.append({"label": lb, "rc": r.returncode,
                               "err": (r.stderr or "").strip()[:120]})
            except (subprocess.SubprocessError, OSError) as e:
                kicked.append({"label": lb, "rc": -1, "err": str(e)[:120]})
        out["kicked"] = kicked
        if kicked:
            time.sleep(5)
            out["port_after"] = _probe()

    out["procs"] = _procs()
    if not out["port"][0] and not labels:
        out["advice"] = ("找不到 hermes 的 launchd 任务 ⇒ 需手工启动 "
                         "（本仓库无启动入口，配置在 ~/.hermes/.env）")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if (out.get("port_after", out["port"])[0]) else 1


if __name__ == "__main__":
    sys.exit(main())
