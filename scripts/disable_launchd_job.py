#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**停用**一个 launchd 定时任务（bootout + 可选移走 plist）✓（2026-11-25）。

【为什么需要】
  队列里只有 `restart_queue`（bootout + bootstrap，**重启**）✗
  没有「**停止**」动作 ⇒ 想停掉一个僵尸任务只能手工上机 ✗
  首个用例：`com.fg.shoutu-history` —— 服务端 `stock_emotion/history`
  已对**全部 8 只**返回 `data: []`（实测 2026-11-24），
  而 `shoutu_history_daily.sh` 是「失败静默 rc=0」设计 ⇒
  **每天白跑、不产出、无告警，已持续 41 天** ✗

【安全设计】
  · label 必须以 `com.fg.` 或 `com.xingguo.` 开头 ✓（防误停系统服务）
  · **默认 dry-run**，必须 `--apply` 才真停 ✓
  · `--remove-plist` 才把 plist 移走（改名 `.disabled`），**不删除** ✓
  · 执行前后各打印一次 `launchctl print` 的存在性 ✓
  · 恢复方式写进输出：`--restore` 把 `.disabled` 改回来并 bootstrap ✓

用法（Mac，经队列）：
    python scripts/disable_launchd_job.py --label com.fg.shoutu-history
    python scripts/disable_launchd_job.py --label com.fg.shoutu-history --apply --remove-plist
    python scripts/disable_launchd_job.py --label com.fg.shoutu-history --apply --restore
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

ALLOWED_PREFIX = ("com.fg.", "com.xingguo.")
LAUNCH_AGENTS = os.path.expanduser("~/Library/LaunchAgents")


def _run(*args, timeout=60):
    r = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _domain():
    return "gui/%d" % os.getuid()


def _loaded(label):
    rc, so, _ = _run("launchctl", "print", "%s/%s" % (_domain(), label))
    return rc == 0


def _plist_path(label):
    for p in (os.path.join(LAUNCH_AGENTS, label + ".plist"),
              os.path.join(LAUNCH_AGENTS, label + ".plist.disabled")):
        if os.path.exists(p):
            return p
    hits = glob.glob(os.path.join(LAUNCH_AGENTS, label + ".plist*"))
    return hits[0] if hits else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--remove-plist", action="store_true",
                    help="把 plist 改名为 .disabled（不删除）")
    ap.add_argument("--restore", action="store_true",
                    help="反向操作：改回 .plist 并 bootstrap")
    args = ap.parse_args(argv)

    if not args.label.startswith(ALLOWED_PREFIX):
        return {"ok": False,
                "error": "label 必须以 %s 开头：%s"
                         % (" 或 ".join(ALLOWED_PREFIX), args.label)}

    out = {"label": args.label, "apply": args.apply,
           "loaded_before": _loaded(args.label),
           "plist": _plist_path(args.label), "steps": {}}

    if not args.apply:
        out["ok"] = True
        out["note"] = ("**dry-run**：loaded=%s，plist=%s。确认后加 `--apply` ✓"
                       % (out["loaded_before"], out["plist"]))
        return out

    # ── restore 分支 ───────────────────────────────────────────
    if args.restore:
        p = out["plist"] or ""
        if p.endswith(".disabled"):
            new_p = p[:-len(".disabled")]
            os.rename(p, new_p)
            rc, _, se = _run("launchctl", "bootstrap", _domain(), new_p)
            out["steps"]["restore"] = {"plist": new_p, "rc": rc, "stderr": se[:200]}
            out["ok"] = rc == 0
            out["note"] = ("✅ 已恢复并 bootstrap ✓" if out["ok"]
                           else "⚠️ bootstrap 失败：%s" % se[:200])
        else:
            out["ok"] = False
            out["error"] = "找不到 .disabled 文件：%s" % p
        out["loaded_after"] = _loaded(args.label)
        return out

    # ── 停止分支 ───────────────────────────────────────────────
    if out["loaded_before"]:
        rc, _, se = _run("launchctl", "bootout", "%s/%s" % (_domain(), args.label))
        out["steps"]["bootout"] = {"rc": rc, "stderr": se[:200]}
    else:
        out["steps"]["bootout"] = {"rc": 0, "note": "本来就没加载 ✓"}

    if args.remove_plist and out["plist"] and not out["plist"].endswith(".disabled"):
        new_p = out["plist"] + ".disabled"
        os.rename(out["plist"], new_p)
        out["steps"]["plist_renamed"] = new_p

    out["loaded_after"] = _loaded(args.label)
    out["ok"] = not out["loaded_after"]
    out["note"] = ("✅ 已停止（loaded=False）✓" if out["ok"]
                   else "⚠️ 仍处于加载状态，请检查 ✗")
    out["restore_hint"] = ("python scripts/disable_launchd_job.py "
                           "--label %s --apply --restore" % args.label)
    return out


if __name__ == "__main__":
    _out = main()
    print(json.dumps(_out, ensure_ascii=False, indent=2))
    sys.exit(0 if isinstance(_out, dict) and _out.get("ok") else 1)
