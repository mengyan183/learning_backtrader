#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补齐 `https.proxy`（A 方案，2026-11-26）。

【问题】
  Mac 的 `git config`：
    `http.proxy  = http://127.0.0.1:7890`   ← 有
    `https.proxy = （未设）`                ← **没有** ✗
  而 `origin` 是 **https://github.com/...** ⇒ 走 https 代理 ✗
  ⇒ `git push` 报 `SSL_ERROR_SYSCALL in connection to github.com:443` ✗
  ⇒ 4 个提交卡在 Mac，`gitee` 收不到，Windows 拉不到 ✗

【本脚本做什么】
  ① 打印当前 `http.proxy` / `https.proxy`
  ② `--apply`：**仅在 `https.proxy` 未设时**，把它设成 `http.proxy` 的值 ✓
     （不覆盖已有配置；不设 `http.proxy` 本身）
  ③ 设完用 `git ls-remote origin` 验证连通（**只读，不 push**）✓
  ④ `--unset`：撤回本次设置（回到「未设」）

⚠️ **只动 `--global` 的 `https.proxy` 这一项**，不碰 remote、不碰其他配置 ✓
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(*args, timeout=60):
    try:
        r = subprocess.run(["git", "-C", ROOT] + list(args),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def _get(key, scope=None):
    """读配置项。`scope=None` ⇒ **不限层级**（local 优先于 global）✓

    🔴 2026-11-26 踩坑：上一版只查 `--global` ✗
       `git_push_diag` 读到 `http.proxy = 127.0.0.1:7890`，
       而本脚本查 `--global` 得到**空** ✗
       ⇒ 说明它配在**仓库级** `.git/config`，不是全局 ✓
       ⇒ 读必须不限层级；写要在**同一层级**写 ✓
    """
    args = ["config"]
    if scope:
        args.append(scope)
    args += ["--get", key]
    _rc, so, _ = _git(*args)
    return so or ""


def _scope_of(key):
    """判断某个配置项配在哪一层：`local` / `global` / `""`（都没有）。"""
    for sc in ("--local", "--global"):
        if _get(key, sc):
            return sc.lstrip("-")
    return ""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--unset", action="store_true")
    args = ap.parse_args()

    http_p = _get("http.proxy")
    https_p = _get("https.proxy")
    print("当前配置：")
    print("  http.proxy  = %s" % (http_p or "（未设）"))
    print("  https.proxy = %s" % (https_p or "（未设）"))

    if args.unset:
        if not https_p:
            print("\nhttps.proxy 本来就没设 ⇒ 无需撤回 ✓")
            return 0
        rc, _so, se = _git("config", "--global", "--unset", "https.proxy")
        print("\n撤回 https.proxy：rc=%s %s" % (rc, se[:120]))
        return 0 if rc == 0 else 1

    if not http_p:
        print("\n🔴 `http.proxy` 也是空的 ⇒ 无法推断该设什么值 ✗")
        print("   请手工指定：git config --global https.proxy <url>")
        return 1

    if https_p:
        print("\n✓ `https.proxy` 已设，无需改动 ✓")
        need = False
    else:
        need = True

    if not args.apply:
        print("\n**dry-run**：%s"
              % ("会把 https.proxy 设为 %s" % http_p if need else "无需改动"))
        print("确认后加 `--apply` ✓")
        return 0

    if need:
        # 🔴 在 `http.proxy` **所在的层级**写 ✓（实测它在仓库级）
        _sc = _scope_of("http.proxy") or "global"
        _flag = "--" + _sc
        rc, _so, se = _git("config", _flag, "https.proxy", http_p)
        print("\n写入层级：%s" % _flag)
        if rc != 0:
            print("\n🔴 设置失败：%s" % se[:200])
            return 1
        print("\n✅ 已设 https.proxy = %s" % http_p)

    # 验证（只读）
    print("\n验证连通性（`ls-remote`，不 push）：")
    rc, so, se = _git("ls-remote", "--heads", "origin", timeout=45)
    if rc == 0:
        print("  ✅ 连通（%d 个分支）" % len(so.splitlines()))
    else:
        print("  ❌ 仍失败：%s" % (se or so)[:300])
        print("     ⇒ 代理本身可能没运行，或需换 SSH 443（B 方案）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
