# -*- coding: utf-8 -*-
"""队列**文件 IO** ✓ —— 任务 json 的读写、`.running` 旁路标记、过期归档、瘦身。

【边界】
  · 本模块**持有 `QUEUE`** ✓ —— 队列目录就是它的状态
    （调度器的 `_acquire_lock` / `main` / `install_daily_plist` 都从这里 import）
  · **不跑 action** ✗、不碰 launchd / git / 网络 ✓
  · 测试重定向队列目录时要 **patch `queue_store.QUEUE`** ✗ —— 只 patch
    `run_task_queue.QUEUE` 不会影响本模块 ✓
"""
import glob
import json
import os
import shutil
import time

from queue_core import ROOT

QUEUE = os.path.join(ROOT, "docs", "task-queue")


#: **优先执行**的 action（重启类）—— 见 `_load_pending` 的排序说明。


PRIORITY_ACTIONS = ("restart_dashboard", "restart_queue")
#: 待执行任务超过这么久还没回执 ⇒ 视为**失效**，自动归档 ✓（2026-11-10）
#: 🔴 事故：11-09 那批任务（`deepseek_probe` / `git_state` ×3 / `clean_sync_partial`）
#:    的 json 留在队列里、但 `.result.json` 在 `git reset` 时被丢了 ✗
#:    ⇒ `_load_pending` 每一轮都把它们当新任务**重跑** ✗
#:    ⇒ 队列每 10 秒的窗口全被老任务吃掉 ⇒ 新任务看起来「一直排队中」✗
#: ⚠️ 阈值 **6 小时**（曾改 24，已改回）✓
#:    24h 的问题：11-09 那批僵尸任务才 18 小时 ⇒ 逃过归档 ✗ 继续每轮重跑 ✗
#:    6h 当初误伤「刚下发」的原因不是阈值，而是**判据用了 mtime** ✗
#:    ⇒ 判据改成 `created_at`（见 `_archive_stale_pending`）后，6h 是安全的 ✓


STALE_PENDING_HOURS = 6


def _archive_stale_pending(hours=STALE_PENDING_HOURS):
    """把**超时仍无回执**的任务 json 挪进 `_stale/` ✓（不删，可人工恢复）。

    判据：json 的 mtime 早于 `hours` 前，且**没有**同名 `.result.json`。
    ⚠️ 只挪 `docs/task-queue/*.json`，不碰 `.result.json` / `.running` ✓
    """
    import shutil
    dst = os.path.join(QUEUE, "_stale")
    moved = []
    try:
        names = sorted(os.listdir(QUEUE))
    except OSError:
        return moved
    cutoff = time.time() - hours * 3600
    for name in names:
        if not name.endswith(".json") or name.endswith(".result.json"):
            continue
        p = os.path.join(QUEUE, name)
        tid = name[:-len(".json")]
        if os.path.exists(os.path.join(QUEUE, tid + ".result.json")):
            continue
        try:
            # 🔴 2026-11-10 实测事故：**只看 mtime 会把刚到的新任务归档掉** ✗
            #    （13:49 下发的 `test_futu_fed` 在 13:53 就被归档 ✗）
            #    原因：文件是 fg-sync **重新检出**的，mtime 可能被刷新成旧值/不一致 ✗
            #    ⇒ 改用 `created_at`（任务 json 里的权威字段）+ mtime，**取较新者** ✓
            t_created = 0.0
            try:
                with open(p, encoding="utf-8") as _fh:
                    _spec = json.load(_fh)
                _c = str(_spec.get("created_at") or "")
                if _c:
                    t_created = time.mktime(time.strptime(_c, "%Y-%m-%dT%H:%M:%S"))
            except (OSError, ValueError, KeyError):
                t_created = 0.0
            # 🔴 2026-11-10 第二次修正：**只用 `created_at`**（权威）✓
            #    上一版用 `max(created_at, mtime)` ✗ —— 老任务被重新检出后
            #    mtime 变新 ⇒ 看起来像新任务 ⇒ 永远归档不掉 ✗
            #    （实测：11-09 那批 5 个任务在 11-10 15:20 仍 pending ✗）
            #    `created_at` 缺失时才退回 mtime ✓
            _age_base = t_created or os.path.getmtime(p)
            _age_h = (time.time() - _age_base) / 3600.0
            # 🔴 2026-11-11 用户要求：**「有 .running 才归档」** ✓
            #    事故：11-10 17:27 下发的 `autostart_list` 因为队列卡住没跑成 ✗
            #    到 11-11 09:02（15.5 小时 > 6h 阈值）被**静默归档** ✗
            #    ⇒ 用户以为它执行了，其实压根没轮到 ✗
            #    ⇒ 分两档：
            #      ① 有 `.running` 残留 ⇒ 说明**尝试过但卡死** ⇒ 6 小时就归档 ✓
            #      ② 没有 `.running` ⇒ 说明**压根没轮到** ⇒ 要 **24 小时**才归档 ✓
            #    （24h 是为了兜住 11-09 那批 result 丢了的真僵尸 ✓）
            _has_running = os.path.exists(os.path.join(QUEUE, tid + ".running"))
            if _has_running:
                if _age_base > cutoff:            # 6h
                    continue
            elif _age_h < 24:
                continue
            os.makedirs(dst, exist_ok=True)
            shutil.move(p, os.path.join(dst, name))
            moved.append(name)
            print("[stale]   %s（%.1f 小时，%s）"
                  % (name, _age_h,
                     "有 .running 残留" if _has_running else "从未执行过"))
        except OSError:
            continue
    if moved:
        print("[stale] 已归档 %d 个超时无回执的任务 -> _stale/" % len(moved))
        for m in moved:
            print("   %s" % m)
    return moved


def _load_pending():
    """列出待执行任务（status=pending）：**重启类优先**，其余按 id 升序。"""
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
        except (OSError, ValueError) as exc:
            # 🔴 2026-10-29 实测：一个被写坏的 json（文件末尾粘了 patch 头 ✗）
            # 会被**每轮静默跳过** ✗ ⇒ 任务永久饿死、且没人知道 ✗
            # ⇒ 打一行警告并改名成 `.broken`（不再匹配 *.json，不再空转）✓
            print("[warn] 任务文件读不出，已隔离为 .broken：%s（%s）"
                  % (name, exc))
            try:
                os.replace(p, p + ".broken")
            except OSError:
                pass
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
    # 🔴 2026-10-29：按 **id** 排序（先进先出）✗ —— id 是
    # `t-YYYYmmdd-HHMMSS-<action>`，字典序**恒等于**时间序 ✓；
    # 而 `created_at` 可能缺失/手写错误（缺失会排最前，抢跑 ✗）。
    # 🔴 2026-11-06：**重启类提到队首** ✓ —— 队列是串行的，而 `fetch_prices`
    #    的 timeout 是 1800 秒 ✗ ⇒ 排在它后面的 `restart_dashboard` 白等 16 分钟 ✗
    #    （实测：12:40 下发，13:55 才执行 ✗）。重启只要几秒且决定页面能不能用 ✓
    out.sort(key=lambda s: (0 if str(s.get("action") or "") in PRIORITY_ACTIONS
                            else 1, str(s.get("id") or "")))
    return out


def _write_result(spec, status, rc, output, started, finished):
    rec = {
        "id": spec["id"],
        "action": spec.get("action"),
        "params": spec.get("params") or {},
        "status": status,
        "rc": rc,
        # 🔴 2026-11-03：2000 → **8000** ✗ —— 实测 `audit_data` 的 JSON
        #    在 2000 处被**从中间切断** ⇒ `json.loads` 直接失败 ✗
        #    ⇒ 结果「看得见但解析不了」✗（`ok: None` 就是这个症状 ✗）
        #    ⚠️ 仍有上限 ✗ —— 超长输出请让动作**自己精简** ✓（见 `_act_audit_data`）
        "output": output[-8000:],
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
#: 队列里只留最近这么多个**已完成**任务 ✓（每个任务两个 json，不清理会无限涨 ✗）


KEEP_TASKS = 10


def _task_ids():
    """`{id: [文件路径…]}` —— 一个任务是 `<id>.json` + `<id>.result.json` 两个文件 ✓。"""
    out = {}
    for p in glob.glob(os.path.join(QUEUE, "*.json")):
        base = os.path.basename(p)
        tid = (base[:-len(".result.json")] if base.endswith(".result.json")
               else base[:-len(".json")])
        out.setdefault(tid, []).append(p)
    return out
#: 「正在执行」标记后缀 —— **旁路文件，不写回任务 json** ✗
#: 为什么不在 json 里写 status=running：进程若中途被杀，json 会永远停在 running ✗
#: ⇒ `_load_pending` 再也不认领它 ⇒ 任务永远不执行 ✗（比显示不准严重得多 ✗）。
#: 旁路标记最坏只是看板显示「执行中」到超时 ✓。


RUNNING_SUFFIX = ".running"


def _running_path(tid):
    return os.path.join(QUEUE, tid + RUNNING_SUFFIX)


def _mark_running(tid):
    try:
        with open(_running_path(tid), "w", encoding="utf-8") as fh:
            json.dump({"started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, fh)
    except OSError:
        pass


def _clear_running(tid):
    try:
        os.remove(_running_path(tid))
    except OSError:
        pass


def _prune_queue(keep=KEEP_TASKS):
    """只留最近 `keep` 个**已完成**任务 ✓，返回被删文件名列表。

    🔴 未完成的任务（没有 `.result.json`）**一律不删** ✗ —— 删了就永远不会执行 ✗。
    id 形如 `t-YYYYmmdd-HHMM-<action>` ⇒ 字典序即时间序 ✓。
    """
    ids = _task_ids()
    pending = {t for t, ps in ids.items()
               if not any(p.endswith(".result.json") for p in ps)}
    done = sorted((t for t in ids if t not in pending), reverse=True)
    dropped = []
    for tid in done[max(0, keep - len(pending)):]:
        for p in ids[tid]:
            try:
                os.remove(p)
                dropped.append(os.path.basename(p))
            except OSError:
                pass
    return dropped


def _collect_reinstall():
    """把「延迟重装」的结果并回任务结果 ✓，返回被更新的任务 id 列表。

    2026-10-29：`install_daily_plist` 对队列作业只能**延迟 8 秒**重装（当场 bootout
    会把自己杀掉 ✗）⇒ 它返回的 `ok:true` 只代表**拷贝成功**，重装成没成无人回收 ✗。
    现在那个游离 shell 把结果写进 `<tid>.reinstall.json` ✓，这里下一轮读回来：
    ① 打印一行到 `/tmp/fg_task_queue.log`；② 回写进 `<tid>.result.json` 的
    `reinstall` 字段（看板可见 ✓）；③ 删掉标记 ✓。
    """
    changed = []
    if not os.path.isdir(QUEUE):
        return changed
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".reinstall.json"):
            continue
        tid = name[:-len(".reinstall.json")]
        mp = os.path.join(QUEUE, name)
        try:
            with open(mp, encoding="utf-8") as fh:
                mark = json.load(fh)
        except (OSError, ValueError):
            mark = {"ok": False, "reason": "标记文件读不出"}
        rp = os.path.join(QUEUE, tid + ".result.json")
        try:
            with open(rp, encoding="utf-8") as fh:
                res = json.load(fh)
            res["reinstall"] = mark
            with open(rp, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=2)
            changed.append(tid)
            print("[reinstall] %s %s（rc=%s）"
                  % (tid, "重装成功 ✓" if mark.get("ok") else "重装**失败** ✗",
                     mark.get("rc")))
        except (OSError, ValueError) as exc:
            print("[warn] 重装结果回写失败（%s）：%s" % (tid, exc))
        try:
            os.remove(mp)
        except OSError:
            pass
    return changed
