# -*- coding: utf-8 -*-
"""Mac 侧任务队列执行器：读 `docs/task-queue/*.json` → 跑白名单 action → 写 result → 提交。

【为什么要有它 —— 2026-10-28 用户拍板】
看板上「清理堆积 / 同步运行副本」这类**一次性任务**不该各占一个按钮 ✗ ——
每下发一次任务就新增一个按钮，页面必然失控 ✗，而且点完没有执行历史 ✗。
⇒ 改成「任务下发」：

    Windows  写 docs/task-queue/<id>.json（status=pending）→ 飞书分片
    Mac      本脚本扫到 pending → 执行白名单 action → 写 <id>.result.json
             → git add/commit/push（docs/ 在白名单内 ✓）
    Windows  git fetch → 看板读 result 显示任务历史 ✓

🔴 白名单是 **action 名**，不是命令字符串 ✗ —— 后者等于把 RCE 开在飞书群里
   （MT-49 那类洞：任何能给飞书发消息的人都能在 Mac 上执行任意命令）。
   新增动作必须改本文件的 ACTIONS 并过 code review ✓。

用法（Mac）：
    .venv/bin/python scripts/run_task_queue.py            # 跑一次（launchd 每 10s 调）
    .venv/bin/python scripts/run_task_queue.py --no-commit  # 只执行不提交（调试）
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "docs", "task-queue")

#: launchd 定时器（本脚本每 10s 被调一次）—— 看板可一键安装 ✓
LABEL = "com.xingguo.fg-task-queue"
PLIST_SRC = os.path.join(ROOT, "scripts", LABEL + ".plist")
PLIST_DST = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                         LABEL + ".plist")


def agent_status():
    """定时器是否已安装 / 已加载（看板据此决定要不要显示安装按钮）。"""
    installed = os.path.isfile(PLIST_DST)
    loaded = False
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True,
                           text=True, timeout=15)
        loaded = LABEL in (r.stdout or "")
    except (subprocess.SubprocessError, OSError):
        pass
    return {"installed": installed, "loaded": loaded, "label": LABEL}


def install_agent():
    """把 plist 装进 `~/Library/LaunchAgents` 并 bootstrap（幂等，重复点会先 bootout）。

    🔴 为什么可以在页面上做：看板服务本身就跑在 Mac 本地、以用户身份运行 ✓，
    有写 `~/Library/LaunchAgents` 和执行 `launchctl` 的权限 ✓。
    安全边界：源是仓库里的固定 plist、目标是固定的 LaunchAgents 路径、无用户输入 ✓。
    """
    if sys.platform != "darwin":
        return {"ok": False, "reason": "只有 macOS 支持 launchd（当前 %s）" % sys.platform}
    if not os.path.isfile(PLIST_SRC):
        return {"ok": False, "reason": "仓库里没有 plist：%s" % PLIST_SRC}
    try:
        os.makedirs(os.path.dirname(PLIST_DST), exist_ok=True)
        shutil.copy2(PLIST_SRC, PLIST_DST)
    except OSError as exc:
        return {"ok": False, "reason": "拷贝 plist 失败：%s" % exc}

    dom = "gui/%d" % os.getuid()
    try:
        # 先卸再装（幂等）：未加载时 bootout 会报错，忽略即可 ✓
        subprocess.run(["launchctl", "bootout", dom + "/" + LABEL],
                       capture_output=True, timeout=30)
        r = subprocess.run(["launchctl", "bootstrap", dom, PLIST_DST],
                           capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "launchctl 执行失败：%s" % exc}
    st = agent_status()
    out = {"ok": bool(st["loaded"]) or r.returncode == 0,
           "stdout": (r.stdout or "")[-300:], "stderr": (r.stderr or "")[-300:]}
    out.update(st)
    return out

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _act_cleanup_backlog(params):
    """把插件层 30 分钟前的历史文件挪进 archive（见 sync_health.archive_backlog）。"""
    from fg_system.dashboard import sync_health
    r = sync_health.archive_backlog()
    # 「没有够老的文件」= **成功**（无事可做）✓；「目录不存在」才是失败 ✗
    ok = bool(r.get("moved")) or "没有超过" in str(r.get("reason") or "")
    return dict(r, ok=ok)


def _act_sync_runtime(params):
    """把仓库版 bypass 覆盖到运行时副本（见 sync_health.sync_runtime_copy）。"""
    from fg_system.dashboard import sync_health
    return sync_health.sync_runtime_copy()


def _act_clean_sync_partial(params):
    """删掉**指定包**的残留分片（`~/.openclaw/tmp/fg-sync-in/<pkg>_*.md`）✓。

    动机（MT-87，2026-10-28）：Windows 侧弃用的包永远收不齐 ✗ ⇒ bypass 每次同步
    都报「分片不齐，请补发」✗。只删 `pkg` 前缀的分片 ✓，不碰 `.done` / 其它包 ✗。
    """
    from fg_system.dashboard import sync_health
    pkg = str(params.get("pkg") or "")
    # 🔴 只允许 [A-Za-z0-9_] —— 挡住 `..`、`/`、`*` 这类会越出目录的写法 ✗
    if not pkg or any(not (c.isalnum() or c == "_") for c in pkg):
        return {"ok": False, "reason": "pkg 名非法（只允许 [A-Za-z0-9_]）：%r" % pkg}
    removed = []
    for p in sorted(glob.glob(os.path.join(sync_health.SHARD_IN, pkg + "_*.md"))):
        try:
            os.remove(p)
        except OSError as exc:
            return {"ok": False, "removed": removed,
                    "reason": "删 %s 失败：%s" % (os.path.basename(p), exc)}
        removed.append(os.path.basename(p))
    return {"ok": True, "removed": removed, "count": len(removed)}


#: 🔴 唯一可执行清单。键是**任务名**，值是固定函数 —— 不接受任何命令字符串 ✓
ACTIONS = {
    "cleanup_backlog": _act_cleanup_backlog,
    "sync_runtime": _act_sync_runtime,
    "clean_sync_partial": _act_clean_sync_partial,
}


def _load_pending():
    """列出待执行任务（status=pending），按 created_at 升序（先来先做）。"""
    out = []
    if not os.path.isdir(QUEUE):
        return out
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".json") or name.endswith(".result.json"):
            continue
        p = os.path.join(QUEUE, name)
        try:
            with open(p, encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError):
            continue
        if str(spec.get("status") or "pending") != "pending":
            continue
        spec["_path"] = p
        tid = str(spec.setdefault("id", name[:-5]))
        # 已有 result ⇒ 不再执行 ✓ —— 原任务文件里的 status 永远是 pending（我们不回写它），
        # launchd 每 10s 扫一次会**重复执行** ✗（2026-10-28 测试抓到的真 bug）
        if os.path.exists(os.path.join(QUEUE, tid + ".result.json")):
            continue
        out.append(spec)
    out.sort(key=lambda s: str(s.get("created_at") or ""))
    return out


def _write_result(spec, status, rc, output, started, finished):
    rec = {
        "id": spec["id"],
        "action": spec.get("action"),
        "params": spec.get("params") or {},
        "status": status,
        "rc": rc,
        "output": output[-2000:],       # 只留尾部，避免 result 文件膨胀
        "started_at": started,
        "finished_at": finished,
        "duration_s": round(time.time() - spec.get("_t0", time.time()), 2),
    }
    p = os.path.join(QUEUE, spec["id"] + ".result.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return p


def _auto_clean():
    """每轮顺手自愈：插件层堆积超阈值就归档（2026-10-28 A 方案）。

    为什么不做成「下发任务」：这是**周期性自愈**，不是一次性动作 ——
    每 10s 跑一次、超阈值才动，不需要人记得下发 ✓。
    为什么还要保留手动按钮：自愈是兜底，手动是「我现在就想清」。
    """
    try:
        from fg_system.dashboard import sync_health as sh
        if sh._bypass_stats(time.time())["count"] < sh.BACKLOG_WARN:
            return None
        return sh.archive_backlog()
    except Exception:
        return None            # 自愈失败绝不能影响正常任务 ✓


def run_once(commit=True):
    """跑一轮。返回 [(id, status), ...]。"""
    auto = _auto_clean()
    if auto and auto.get("moved"):
        print("[auto-clean] 已归档 %d 个插件层文件 -> %s"
              % (auto["moved"], auto.get("dest")))
    done = []
    for spec in _load_pending():
        action = str(spec.get("action") or "")
        fn = ACTIONS.get(action)
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        spec["_t0"] = time.time()
        if fn is None:
            # 未知 action ⇒ 明确失败，不静默跳过 ✓（否则下发方以为在排队）
            _write_result(spec, "failed", -1,
                          "未知 action：%s（白名单：%s）"
                          % (action, ", ".join(sorted(ACTIONS))),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "failed"))
            continue
        try:
            r = fn(spec.get("params") or {})
            ok = bool(r.get("ok")) if isinstance(r, dict) else True
            _write_result(spec, "done" if ok else "failed",
                          0 if ok else 1,
                          json.dumps(r, ensure_ascii=False),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "done" if ok else "failed"))
        except Exception as exc:      # noqa: BLE001 —— 任何异常都要留痕，不能静默 ✗
            _write_result(spec, "failed", -1,
                          "%s: %s" % (type(exc).__name__, exc),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "failed"))

    if done and commit:
        _git_commit(done)
    return done


def _git_commit(done):
    """只提交 `docs/task-queue/` ✓ —— 不碰其他脏文件（Mac 上常年有测试产物 ✗）。"""
    try:
        subprocess.run(["git", "add", "docs/task-queue"], cwd=ROOT,
                       check=True, capture_output=True, timeout=60)
        msg = "task: %s" % "; ".join("%s=%s" % (i, s) for i, s in done)
        r = subprocess.run(["git", "commit", "-m", msg], cwd=ROOT,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:          # 无变更可提交 ⇒ 不是错误 ✓
            return
        subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT,
                       capture_output=True, timeout=180)
    except (subprocess.SubprocessError, OSError):
        pass                           # 提交/推送失败不影响任务本身的结果文件 ✓


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mac 侧任务队列执行器")
    ap.add_argument("--no-commit", action="store_true", help="只执行不提交（调试）")
    args = ap.parse_args(argv)
    done = run_once(commit=not args.no_commit)
    for i, s in done:
        print("%s -> %s" % (i, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
