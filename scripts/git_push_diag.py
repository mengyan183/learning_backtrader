#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断 Mac 的 git push 链路（2026-11-26）。

【背景：同步链】
    windows → 飞书 → mac → **github** → gitee → windows
    ⇒ `mac → github` 一断，**代码到不了 gitee ⇒ Windows 拉不到** ✗

【本次故障】
    Mac 回执：`⚠️ push 失败（已提交 0f41e3e，未推送）：fatal: unable to access
              'https://github.com/mengyan183/learning_backtrader':
              LibreSSL SSL_connect: SSL_ERROR_SYSCALL in connection to github.com:443`
    实测：gitee 上 `git branch -r --contains 0f41e3e` ⇒ **malformed object name** ✗
    ⇒ 确认该提交**没到 gitee** ⇒ 后续所有「已入库」判断都要打问号 ✗

【本脚本查什么（全部只读 + 一次 dry-run push）】
  ① `git remote -v` —— 到底有几个 remote、各自指向哪
  ② `git status -sb` —— 本地是否领先 origin（未推送的提交）
  ③ 代理环境变量 —— `SSL_ERROR_SYSCALL` 常见于代理未生效
  ④ `git push --dry-run` —— **只预演不真推**，看是否仍然 SSL 失败
  ⑤ 逐 remote 测连通性（`git ls-remote --heads`）

⚠️ **绝不真推** —— `--dry-run` 只连服务器、不改远端 ✓
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(*args, timeout=60, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        r = subprocess.run(["git", "-C", ROOT] + list(args),
                           capture_output=True, text=True, timeout=timeout,
                           env=e)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT(%ss)" % timeout


def main():
    print("=== ① remote 配置 ===")
    _rc, so, se = _git("remote", "-v")
    print(so or se or "（无 remote）")

    print("\n=== ② 本地 vs 远端 ===")
    _rc, so, se = _git("status", "-sb")
    for ln in (so or se).splitlines()[:6]:
        print("  " + ln)

    print("\n=== ③ 代理环境变量 ===")
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        v = os.environ.get(k)
        if v:
            print("  %-12s = %s" % (k, v))
    print("  git config 代理：")
    for key in ("http.proxy", "https.proxy"):
        _rc, so, _ = _git("config", "--get", key)
        print("    %-14s = %s" % (key, so or "（未设）"))

    print("\n=== ④ push --dry-run（**不真推**）===")
    rc, so, se = _git("push", "--dry-run", "origin", "HEAD:main", timeout=90)
    print("  rc = %s" % rc)
    out = (so + "\n" + se).strip()
    print("  " + (out[:600] if out else "（无输出）"))

    print("\n=== ⑤ 逐 remote 连通性（ls-remote）===")
    _rc, remotes, _ = _git("remote")
    for rm in (remotes or "").split():
        rc, so, se = _git("ls-remote", "--heads", rm, timeout=45)
        ok = "✅" if rc == 0 else "❌"
        first = (so.splitlines()[0] if so else (se[:120] or ""))
        print("  %s %-10s rc=%-3s %s" % (ok, rm, rc, first))

    print("\n判读：")
    print("  · ④ rc≠0 且 ⑤ 全 ❌ ⇒ Mac 到 github 网络不通（需代理/换 remote）")
    print("  · ④ rc≠0 但 ⑤ gitee ✅ ⇒ 可临时把 origin 指向 gitee 打通链路")
    print("  · ② 显示 'ahead N' ⇒ 有 N 个提交**卡在 Mac 上没推出去** ✗")
    return 0


if __name__ == "__main__":
    sys.exit(main())
