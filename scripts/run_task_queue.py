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
import json
import os
import subprocess
import sys
import time

#: 🔴 动作侧基础设施在 `queue_core.py` ✓（2026-11-19 第三轮抽出）
#:   下一步按 8 个包拆 action 时，包与调度器共用这一层，避免互相 import 成环 ✓
#:   这里用**别名导入** ⇒ `q._run` / `q._safe_rel` 等旧名字仍然可用（测试靠它 patch）✓
#: ⚠️ 看板是 `from scripts import run_task_queue` 导入的 ✗ —— 那种方式下
#:   `scripts/` 不一定在 `sys.path` ⇒ `import queue_core` 会 ModuleNotFoundError ✗
#:   ⇒ 先把自己所在目录塞进去，两种 import 方式都成立 ✓


_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import queue_core as _qc                                          # noqa: E402
from queue_core import (ROOT, BSK_BIN, READ_ALLOW as _READ_ALLOW,  # noqa: E402
                        run as _run, safe_rel as _safe_rel,
                        allow_json as _allow_json, rel_ok as _rel_ok,
                        script_allowed as _script_allowed,
                        tail_logs as _tail_logs,
                        task_outputs as _task_outputs,
                        ACTION_ENV, env_for as _env_for,
                        scoped_env as _scoped_env)
from queue_actions.futu import ACTIONS as _FUTU_ACTIONS          # noqa: E402
#: `agent_status` / `install_agent` **不是 action**（看板调的）✓
#: ⇒ re-export 保持 `from scripts import run_task_queue` 的调用方不变 ✓
from queue_actions.launchd import (ACTIONS as _LAUNCHD_ACTIONS,   # noqa: E402
                                   agent_status, install_agent)
from queue_actions.diag import ACTIONS as _DIAG_ACTIONS          # noqa: E402
from queue_actions.git import ACTIONS as _GIT_ACTIONS            # noqa: E402
from queue_actions.data import ACTIONS as _DATA_ACTIONS          # noqa: E402
from queue_actions.research import ACTIONS as _RESEARCH_ACTIONS  # noqa: E402
from queue_actions.diag2 import ACTIONS as _DIAG2_ACTIONS      # noqa: E402
from queue_actions.files import ACTIONS as _FILES_ACTIONS      # noqa: E402
#: 🔴 队列**文件 IO** 在 `queue_store.py` ✓（第十一轮抽出）
#:   `QUEUE` 的**唯一来源**也搬过去了 ⇒ 测试重定向队列目录时要 patch
#:   `queue_store.QUEUE` ✗（只 patch `run_task_queue.QUEUE` 不影响读写）
from queue_store import (QUEUE, KEEP_TASKS,                     # noqa: E402
                         _load_pending, _write_result, _mark_running,
                         _clear_running, _prune_queue,
                         _archive_stale_pending, _collect_reinstall,
                         _task_ids, _auto_clean)


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


#: 需要 `_tid` 的动作 ✓ —— 只有「结果要延迟回写」的才需要知道自己是哪个任务
#: （`install_daily_plist` 的游离 shell 要把结果写成 `<tid>.reinstall.json` ✓）
NEEDS_TID = {"install_daily_plist"}


ACTIONS = {
    # 🔴 动作包（2026-11-19 第四轮起按 8 个包拆）✓ —— 注册表仍是**唯一入口** ✗
    #    包只导出 `ACTIONS` 字典，调度器在这里合并 ⇒ 不改装饰器/自动发现 ✓
    **_FUTU_ACTIONS,
    **_LAUNCHD_ACTIONS,
    **_DIAG_ACTIONS,
    **_GIT_ACTIONS,
    **_DATA_ACTIONS,
    **_RESEARCH_ACTIONS,
    **_DIAG2_ACTIONS,
    **_FILES_ACTIONS,
}


#: 标记超过这么久 ⇒ 视为**残留**（进程已死），看板不再显示执行中 ✓
RUNNING_STALE_SEC = 1200


#: 补推节流：launchd 每 10s 一轮，失败时别把日志刷爆 ✗
_PUSH_RETRY = {"ts": 0.0}


def _try_push_pending(interval=300):
    """有未推送提交就顺手补推一次 ✓ —— 上次推送失败后**自愈** ✓。

    动机（2026-10-29 实测 ✗）：launchd 的 PATH 里没有 `/opt/homebrew/bin` ✗
    ⇒ 凭据助手 `gh auth git-credential` 找不到 gh ✗ ⇒ `git push` rc=128 ✗
    ⇒ 任务结果提交了却推不上去，只能等别的进程捎带 ✗（结果总是「晚到」✗）。
    """
    now = time.time()
    if now - _PUSH_RETRY["ts"] < interval:
        return
    _PUSH_RETRY["ts"] = now
    try:
        r = _run(["git", "rev-list", "--count", "@{u}..HEAD"], 30)
        if r.returncode != 0:
            return                      # 没有上游 / 不是仓库 ⇒ 静默跳过 ✓
        if int((r.stdout or "0").strip() or 0) <= 0:
            return                      # 没有待推提交 ✓
        p = _run(["git", "push", "origin", "HEAD"], 180)
        if p.returncode == 0:
            print("[push] 补推成功（之前失败的提交已同步）")
        else:
            print("[warn] 补推仍失败（rc=%s）：%s"
                  % (p.returncode, (p.stderr or "").strip()[-200:]))
    except (subprocess.SubprocessError, OSError, ValueError):
        pass


def run_once(commit=True):
    """跑一轮。返回 [(id, status), ...]。"""
    _try_push_pending()
    # 上一轮「延迟重装」的结果在这轮收 ✓（顺带把结果并进任务结果文件 ✓）
    reinstalled = _collect_reinstall()
    auto = _auto_clean()
    if auto and auto.get("moved"):
        print("[auto-clean] 已归档 %d 个插件层文件 -> %s"
              % (auto["moved"], auto.get("dest")))
    # 🔴 2026-11-10：先把「超时无回执」的失效任务归档 ✓
    #    否则它们每轮都被当新任务重跑，新任务永远排不上 ✗
    _moved = _archive_stale_pending()
    done = []
    for spec in _load_pending():
        action = str(spec.get("action") or "")
        fn = ACTIONS.get(action)
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        spec["_t0"] = time.time()
        if fn is None:
            # 未知 action ⇒ 明确失败，不静默跳过 ✓（否则下发方以为在排队）
            # 🔴 2026-11-02 实测：最常见的原因是**代码还没入库** ✗ ——
            # 任务 json 和代码分两个包发，若任务 id 早于代码包入库时间，
            # 队列会先用**旧版** `ACTIONS` 跑 ⇒ 报「未知 action」✗
            # （`t-20261102-152253-bsk_status` 就是这么失败的 ✗）
            # ⇒ 提示里必须写清这条，否则看起来像「动作名拼错」✗
            _write_result(spec, "failed", -1,
                          "未知 action：%s（白名单：%s）\n"
                          "⚠️ 若该动作**刚加进代码**：多半是**代码包还没入库** ✗ "
                          "—— 任务 json 与代码分两个包发时，"
                          "必须**先确认代码入库**再下发任务 ✓"
                          % (action, ", ".join(sorted(ACTIONS))),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "failed"))
            continue
        # 2026-10-29：执行期打「运行中」旁路标记 ✓ —— 否则 8 分钟的简报任务
        # 在看板上一直显示「排队中」，用户以为卡住了 ✗
        try:
            # ⚠️ `_mark_running` 放 try 里 ✓ —— 原来在 try 外，若它抛
            #    OSError（磁盘满/权限），异常会冒出循环 ⇒ **整轮死** ✗
            #    且 `.running` 标记残留（看板一直显示执行中）✗
            _mark_running(spec["id"])
            # `_tid` 只给**声明需要**的动作（见 `NEEDS_TID`）✓ —— 全局注入会污染
            # 其它动作的 params（有测试锁着「动作收到的就是下发的那份」✗）
            _params = dict(spec.get("params") or {})
            # 🔴 2026-11-19：**先无条件清掉**任务 JSON 里的 `_tid` ✗
            #    实测 `test_tid_cannot_be_overridden` 暴露：只在
            #    `if action in NEEDS_TID` 分支里覆盖 ⇒ 其他 action 拿到的
            #    仍是任务 JSON 里的**恶意值**（`"../../evil"`）✗
            #    ⇒ 先 pop 掉，再按需注入 ✓
            _params.pop("_tid", None)
            if action in NEEDS_TID:
                # 🔴 2026-11-19：**必须覆盖，不能用 `setdefault`** ✗
                #    原写法：任务 JSON 里预先塞 `"_tid": "任意值"` ⇒
                #    `setdefault` 不覆盖 ⇒ 攻击者控制 `_tid` ✗
                #    （`_tid` 用于生成文件名/日志路径 ⇒ 可路径穿越）
                _params["_tid"] = spec["id"]
            # 🔴 2026-11-02：**环境变量白名单** ✓ —— 执行期间 `os.environ`
            # 被收窄成该动作声明的集合 ✗ ⇒ 动作读不到无关密钥 ✓
            with _scoped_env(action):
                r = fn(_params)
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
        finally:
            _clear_running(spec["id"])

    # 只有重装结果回写、没有新任务时也要提交 ✓（否则结果永远留在 Mac 本地 ✗）
    # 🔴 2026-11-10：**归档也要提交** ✗ —— 原来只在 `done or reinstalled` 时提交 ✗
    #    ⇒ 归档只发生在 Mac 本地 ⇒ origin 上任务 json 还在 ⇒ 两边分叉 ✗
    #    （实测：Mac 显示「待执行 0」，origin 上仍有 2 个）
    if commit and (done or reinstalled or _moved):
        if done:
            # 2026-10-29：顺带瘦身 ✓ —— 每个任务两个 json 永不清理会无限涨 ✗
            dropped = _prune_queue()
            if dropped:
                print("[prune] 清理 %d 个旧任务文件（只留最近 %d 个）"
                      % (len(dropped), KEEP_TASKS))
        _git_commit(done
                    or [(t, "reinstall") for t in reinstalled]
                    or [("stale", "archived%d" % len(_moved))])
    return done


#: 🔴 任务产物白名单已外置到 `scripts/queue_allow/task_outputs.json` ✓
#: （`{"dirs": [...], "files": [...]}` —— 加产物路径只改 json ✓）
# 🔴 2026-11-03 移除：`Data/raw/sp500_pe.csv` / `sp500_cape.csv` /
#    `fred_DGS10.csv` 曾在这里 ✗（2026-10-30 为让 Windows 看到 C2 数据 ✗）
#    但 2026-11-03 用户裁定「数据不入库」⇒ `Data/raw/` 已进 `.gitignore` ✗
#    ⇒ 别再把 `Data/raw/*` 加回 `task_outputs.json` ✗ —— 会被 git 拒绝
#       （`_git_commit` 已改为逐个 add，不会整体失败，但会刷一堆 warn ✓）


def _git_commit(done):
    """提交 `docs/task-queue/` + **任务产物目录** ✓ —— 不碰其他脏文件 ✗。"""
    try:
        try:
            out_dirs, out_files = _task_outputs()
        except (OSError, ValueError) as exc:
            # 白名单坏了 ⇒ 只提交任务结果，别把整个提交搞丢 ✗
            print("[warn] 产物白名单读取失败（本轮只提交任务结果）：%s" % exc)
            out_dirs, out_files = [], []
        paths = ["docs/task-queue"] + [
            d for d in out_dirs
            if os.path.isdir(os.path.join(ROOT, d))] + [
            f for f in out_files
            if os.path.isfile(os.path.join(ROOT, f))]
        # 🔴 2026-11-03：**不能 `check=True`** ✗ —— 只要有一个路径被
        #    `.gitignore` 拒绝（如 `Data/raw/*` ✗），git 就**整体失败** ✗
        #    ⇒ 连 `docs/task-queue` 的结果都提交不了 ✗
        #    ⇒ 改为：**逐个 add** ✓ 失败的单独报警但不中断 ✓
        bad = []
        for pth in paths:
            r = _run(["git", "add", "--", pth], 60)
            if r.returncode != 0:
                bad.append((pth, (r.stderr or "").strip()[:120]))
        if bad:
            print("[warn] 以下路径 add 失败（其余照常提交 ✓）：")
            for pth, err in bad:
                print("   %s —— %s" % (pth, err))
        msg = "task: %s" % "; ".join("%s=%s" % (i, s) for i, s in done)
        r = _run(["git", "commit", "-m", msg], 120)
        if r.returncode != 0:          # 无变更可提交 ⇒ 不是错误 ✓
            return
        p = _run(["git", "push", "origin", "HEAD"], 180)
        # 🔴 推送失败**必须留痕** ✗ —— 原来 `except: pass` 把一切吞掉 ⇒
        # 结果文件只躺在 Mac 本地，Windows 端永远看不到任务结果 ✗
        # （2026-10-28 实测：`t-…-clean_sync_partial.result.json` 至今没进 gitee ✗）
        # 日志落在 plist 的 StandardOutPath `/tmp/fg_task_queue.log` ✓。
        if p.returncode != 0:
            print("[warn] 结果已提交但**推送失败**（rc=%s）：%s"
                  % (p.returncode, (p.stderr or "").strip()[-200:]))
    except (subprocess.SubprocessError, OSError) as exc:
        # 失败不影响任务本身的结果文件 ✓，但必须可查 ✗
        print("[warn] 结果提交/推送失败：%s" % exc)


def _acquire_lock():
    """`flock` 排他锁 ✓ —— 防止 launchd **每 10 秒起一个实例**并发抢同一任务 ✗。

    🔴 2026-11-10 实测事故（用户反馈「任务一直显示排队中」）：
       plist 是 `StartInterval = 10` ✗ 而 `run_once()` **没有并发保护** ✗
       ⇒ 只要某个任务跑超过 10 秒（`test_futu_fed` 要 90 秒 ✗），
         launchd 就会**再起一个实例** ⇒ 多个进程同时 `_load_pending()` 抢同一个
         task json ⇒ `.running` 标记互相覆盖、结果文件互相覆盖 ✗
       ⇒ 更糟：多个实例**同时调 futu SDK** ⇒ 直接加重 OpenD 重连循环 ✗
    拿不到锁就**直接退出**（本次跳过，10 秒后自然重试 ✓），不阻塞 ✓
    """
    try:
        import fcntl
    except ImportError:                    # 非 POSIX ⇒ 退化为无锁 ✓
        return object()
    p = os.path.join(QUEUE, ".queue.lock")
    try:
        fh = open(p, "w")
    except OSError:
        return object()
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mac 侧任务队列执行器")
    ap.add_argument("--no-commit", action="store_true", help="只执行不提交（调试）")
    args = ap.parse_args(argv)
    # 🔴 2026-11-12 用户告警「fg-task-queue 日志 39280 秒没动静 ⇒ 疑似卡死」是**误报** ✗
    #    本脚本是 `StartInterval` **定时一次性**任务，不是常驻 ✗
    #    没任务可做时什么都不打印 ⇒ `/tmp/fg_task_queue.log` 的 mtime 不动 ✗
    #    ⇒ 每次运行都 **touch 一个心跳文件**（只改 mtime，不写内容，不涨体积）✓
    #    放在 `_acquire_lock` **之前**：上一轮还在跑也算「活着」✓
    try:
        os.makedirs(QUEUE, exist_ok=True)
        _hb = os.path.join(QUEUE, ".heartbeat")
        with open(_hb, "a"):
            os.utime(_hb, None)
    except OSError:
        pass
    lock = _acquire_lock()
    if lock is None:
        print("[skip] 上一轮仍在执行（flock 未释放）⇒ 本轮跳过")
        return 0
    done = run_once(commit=not args.no_commit)
    for i, s in done:
        print("%s -> %s" % (i, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
