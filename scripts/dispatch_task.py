# -*- coding: utf-8 -*-
"""Windows 侧任务下发：生成 `docs/task-queue/<id>.json` → 打包 → 打印发送命令。

【为什么】（2026-10-28 用户拍板）看板上每来一个一次性需求就加一个按钮 ✗ ⇒
改成任务下发：本脚本写一个 json，走飞书送到 Mac，Mac 的 `run_task_queue.py`
执行白名单 action，结果写 `<id>.result.json` 再由 Mac push 回 gitee ✓。

用法：
    py -3.10 scripts/dispatch_task.py --action cleanup_backlog
    py -3.10 scripts/dispatch_task.py --action sync_runtime --no-pack
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "docs", "task-queue")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from run_task_queue import ACTIONS  # noqa: E402 —— 白名单单一来源 ✓


def _pkg_of(tid):
    """分片包名 ⇒ **只允许 [A-Za-z0-9_]** ✓。

    🔴 Mac 端标记正则是 `###FG:([A-Za-z0-9_]+):(\\d+)/(\\d+)###` ✗ ——
    `task-t-20261028-1935-clean_sync_partial` 带连字符 ⇒ **整包匹配不到** ✗
    ⇒ 分片被静默忽略、任务永远不执行（`pack_one.py` 同款坑）✗。
    """
    return ("task-" + tid).replace("-", "_")


def main(argv=None):
    ap = argparse.ArgumentParser(description="下发一个 Mac 侧任务")
    ap.add_argument("--action", required=True, choices=sorted(ACTIONS))
    ap.add_argument("--id", default=None, help="默认 t-<YYYYmmdd-HHMM>-<action>")
    ap.add_argument("--param", action="append", default=[],
                    metavar="K=V", help="附加参数，可重复")
    ap.add_argument("--no-pack", action="store_true", help="只写 json，不打包")
    args = ap.parse_args(argv)

    # 🔴 2026-10-29 实测：原来只到**分钟** ⇒ 同一分钟下发两个同名 action，
    # 第二个会**覆盖**第一个、任务静默丢失 ✗（一次下发两个模型探测时踩到 ✗）
    # ⇒ 加秒，并保证不与已存在文件撞名 ✓（字典序仍等于时间序 ✓）
    tid = args.id or ("t-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), args.action))
    if not args.id:
        base, n = tid, 2
        while os.path.exists(os.path.join(QUEUE, tid + ".json")):
            tid = "%s-%d" % (base, n)
            n += 1
    params = {}
    for kv in args.param:
        if "=" not in kv:
            sys.exit("--param 需要 K=V 形式：%s" % kv)
        k, v = kv.split("=", 1)
        params[k] = v

    spec = {"id": tid, "action": args.action, "params": params,
            "status": "pending",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    os.makedirs(QUEUE, exist_ok=True)
    p = os.path.join(QUEUE, tid + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    print("已写 %s" % os.path.relpath(p, ROOT))

    # pack_many 用 `git diff <base> -- <path>` ⇒ 新文件必须先 add 才能进 patch ✓
    subprocess.run(["git", "add", os.path.relpath(p, ROOT)], cwd=ROOT, check=True)
    if args.no_pack:
        print("下一步：py -3.10 scripts/pack_many.py <包名> %s --patch --base-ref origin/main"
              % os.path.relpath(p, ROOT))
        return 0

    pkg = _pkg_of(tid)
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "pack_many.py"), pkg,
         os.path.relpath(p, ROOT), "--patch", "--base-ref", "origin/main"],
        cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return r.returncode
    print("下一步：py -3.10 scripts/send_pkg.py %s" % pkg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
