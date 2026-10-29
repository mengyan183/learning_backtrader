# -*- coding: utf-8 -*-
"""同步链路体检（**在 Mac 本地读文件**，给看板一个可判读的结论）。

【为什么需要 —— 2026-10-28 事故】
`sync_1028a` 发出 32 片，Windows 侧 `--sent-status` 显示 **32/32 已发** ✓，
而 Mac 侧 **65 条消息全积压在 OpenClaw pending 队列**（worker 未认领 ✗）
⇒ bypass 没落盘 ⇒ 既没入库也没回执 ✗。
Windows 端只能看到「我发了」和「gitee 上有没有新提交」两头，**中间态完全黑箱** ✗
⇒ 本模块在 Mac 上把四段链路的状态读出来，让用户**在手机上就能看出卡在哪一段** ✓。

链路四段（对应四个可观测点）：
  1. 飞书插件落盘  `~/.openclaw/tmp/fg-sync-bypass-in/`   ← 消息到了插件层
  2. bypass 逐片落盘 `~/.openclaw/tmp/fg-sync-in/`          ← 分片到了 watcher 层
  3. watcher 入库   `~/.openclaw/tmp/fg-sync-in/*.done`     ← 成功标记
  4. 回执发送失败   `~/.openclaw/tmp/fg-sync-in/send-fail.log`

【诚实边界】覆盖不到「消息连 OpenClaw 网关都没收到」—— 那种情况上面四个点全是空的，
与「今天没人发东西」**无法区分** ✗。要区分得看 `~/Library/Logs/openclaw/gateway.log`
里有没有入站堆积，本模块只给出「网关日志是否可读 + 最后修改时间」作为线索 ✓。
"""
import hashlib
import os
import re
import shutil
import time

HOME = os.path.expanduser("~")
OC = os.path.join(HOME, ".openclaw")
BYPASS_IN = os.path.join(OC, "tmp", "fg-sync-bypass-in")
SHARD_IN = os.path.join(OC, "tmp", "fg-sync-in")
SEND_FAIL = os.path.join(SHARD_IN, "send-fail.log")
GW_LOG = os.path.join(HOME, "Library", "Logs", "openclaw", "gateway.log")

#: 运行时副本 vs 仓库版（2026-10-28）：飞书插件调的可能是 `~/.openclaw/workspace/` 下那份 ✗
#: ⇒ 改了仓库却「没生效」时，这里能直接看出来 ✓
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_BYPASS = os.path.join(REPO_ROOT, "skills", "fg-sync", "scripts", "fg-sync-bypass.py")
RUNTIME_BYPASS = os.path.join(OC, "workspace", "skills", "fg-sync", "scripts",
                              "fg-sync-bypass.py")

#: 分片文件名约定：`sync_<包>_<序号>.md`（见 skills/fg-sync/scripts/fg-sync-watcher.py）
_SHARD_RE = re.compile(r"^(?P<pkg>.+)_(?P<seq>\d+)\.md$")

#: 半收滞留多久算「卡住」（秒）—— 与 watcher 的 INCOMPLETE_NOTIFY_SEC 同值
STUCK_SEC = 600

#: 插件层落盘目录「多久内算新」（秒）。
#: 🔴 该目录**消费后不清理**（Mac 实测堆了 3939 个历史文件 ✗）⇒ 只能看新鲜度，
#: 不能看「目录是否非空」✗（2026-10-28 我的第一版就因此误报 bypass_stuck）
BYPASS_FRESH_SEC = 900

#: 插件层堆积多少个以上给提示 + 触发自动归档（只是卫生提示，不影响 verdict ✓）。
#: 2026-10-29 用户裁定 **200 → 100** ✓ —— 200 太高：实测积到 128 个时看板报「正常」，
#: 用户以为是没清理 ✗。配合 `ARCHIVE_KEEP_DAYS=3` 的归档轮转 ✓。
BACKLOG_WARN = 100


def _stat(p):
    try:
        st = os.stat(p)
        return {"path": p, "exists": True, "mtime": st.st_mtime, "size": st.st_size}
    except OSError:
        return {"path": p, "exists": False, "mtime": None, "size": 0}


def _age_min(mtime, now):
    return None if mtime is None else int((now - mtime) / 60)


def _list_md(d):
    """目录下的 .md 文件（不存在 ⇒ 空列表，不抛）。"""
    try:
        return [n for n in os.listdir(d) if n.endswith(".md")]
    except OSError:
        return []


def _packages(now):
    """按包聚合分片：已收序号 / 最老分片滞留分钟数。"""
    out = {}
    for name in _list_md(SHARD_IN):
        m = _SHARD_RE.match(name)
        if not m:
            continue
        pkg, seq = m.group("pkg"), int(m.group("seq"))
        e = out.setdefault(pkg, {"have": set(), "oldest": now})
        e["have"].add(seq)
        mt = _stat(os.path.join(SHARD_IN, name))["mtime"]
        if mt and mt < e["oldest"]:
            e["oldest"] = mt
    res = []
    for pkg, e in sorted(out.items()):
        have = sorted(e["have"])
        total = max(have) if have else 0
        missing = [i for i in range(1, total + 1) if i not in e["have"]]
        res.append({
            "pkg": pkg, "have": len(have), "total": total,
            "missing": missing, "oldest_min": _age_min(e["oldest"], now),
        })
    return res


def _last_ingest(now):
    """最近一次入库成功（`.done` 文件，watcher 写）。"""
    best = None
    try:
        names = [n for n in os.listdir(SHARD_IN) if n.endswith(".done")]
    except OSError:
        names = []
    for n in names:
        mt = _stat(os.path.join(SHARD_IN, n))["mtime"]
        if mt and (best is None or mt > best[1]):
            best = (n, mt)
    if not best:
        return None
    return {"name": best[0], "age_min": _age_min(best[1], now)}


def _bypass_stats(now):
    """插件层落盘目录的统计。

    🔴 2026-10-28 Mac 实测教训：该目录**消费后从不清理** ⇒ 已堆 3939 个历史文件 ✗。
    所以「目录非空」**不能**当作「没被消费」的证据 ✗ ——
    只有**近 15 分钟新落**的文件才说明「刚来过消息」✓。
    """
    names = _list_md(BYPASS_IN)
    if not names:
        return {"count": 0, "files": [], "newest_min": None,
                "oldest_min": None, "fresh": 0}
    mts = []
    for n in names:
        mt = _stat(os.path.join(BYPASS_IN, n))["mtime"]
        if mt:
            mts.append(mt)
    newest = max(mts) if mts else None
    oldest = min(mts) if mts else None
    fresh = sum(1 for m in mts if now - m <= BYPASS_FRESH_SEC)
    return {"count": len(names), "files": sorted(names)[:5],
            "newest_min": _age_min(newest, now), "oldest_min": _age_min(oldest, now),
            "fresh": fresh}


def _md5(p):
    try:
        with open(p, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except OSError:
        return None


def runtime_copy_status():
    """仓库版 vs 运行时副本（`~/.openclaw/workspace/skills/...`）是否同源。

    🔴 2026-10-28：飞书插件调的可能是**副本** ✗ —— 那样改了仓库也「没生效」，
    而且**没有任何报错**提示你 ✗ ⇒ 把这件事做成页面上一行 ✓。
    """
    a, b = _md5(REPO_BYPASS), _md5(RUNTIME_BYPASS)
    return {"repo": a is not None, "runtime": b is not None,
            "same": (a == b) if (a and b) else None}


def sync_runtime_copy():
    """把**仓库版** bypass 覆盖到运行时副本（先备份旧副本 ✓）。

    🔴 2026-10-28 实测：Mac 上两者 md5 不一致 ⇒ 仓库改动不生效 ✗，
    且无任何报错 ✗。与其让人进终端 `cp`，不如页面点一下 ✓。
    安全边界：源是**仓库里已被 review 的文件** ✓，目标是固定路径 ✓，
    不接受任何用户输入 ✓，覆盖前留 `.bak-<MMDD-HHMM>` ✓。
    """
    if not os.path.isfile(REPO_BYPASS):
        return {"ok": False, "reason": "仓库版 bypass 不存在"}
    if not os.path.isdir(os.path.dirname(RUNTIME_BYPASS)):
        return {"ok": False, "reason": "运行时目录不存在（本机不是 Mac / 未装 OpenClaw）"}
    backup = None
    try:
        if os.path.isfile(RUNTIME_BYPASS):
            backup = RUNTIME_BYPASS + ".bak-" + time.strftime("%m%d-%H%M")
            shutil.copy2(RUNTIME_BYPASS, backup)
        shutil.copy2(REPO_BYPASS, RUNTIME_BYPASS)
    except OSError as exc:
        return {"ok": False, "reason": "拷贝失败：%s" % exc}
    return {"ok": True, "backup": backup,
            "same": _md5(REPO_BYPASS) == _md5(RUNTIME_BYPASS)}


def collect():
    """返回体检结果（纯读，不写任何文件，不联网）。"""
    now = time.time()
    oc_ok = os.path.isdir(OC)
    pkgs = _packages(now) if oc_ok else []
    byp = _bypass_stats(now) if oc_ok else {"count": 0, "files": [], "fresh": 0,
                                           "newest_min": None, "oldest_min": None}
    send_fail = _stat(SEND_FAIL)
    gw = _stat(GW_LOG)
    last = _last_ingest(now)
    last_min = None if last is None else last["age_min"]
    # 近 15 分钟有没有成功入库（判断链路是否活着）
    recent_done = last_min is not None and last_min <= BYPASS_FRESH_SEC // 60

    # ---- 判定（顺序即优先级：越靠前越严重）----
    verdict, hint = "idle", "链路空闲：没有滞留分片，也没有进行中的包"
    if not oc_ok:
        verdict = "unknown"
        hint = ("本机没有 ~/.openclaw ⇒ 不是 Mac（Windows 侧正常现象）"
                "或 OpenClaw 未安装 ✗")
    elif byp["fresh"] and not pkgs and not recent_done:
        # 只有「**刚**来过消息 + 分片没产出 + 最近也没入库」才算真卡住 ✓
        verdict = "bypass_stuck"
        hint = ("近 %d 分钟有 %d 个文件落到插件层，但分片目录为空、"
                "且近 %d 分钟无入库 ⇒ **bypass 可能没被调用** ✗（worker 未消费）"
                % (BYPASS_FRESH_SEC // 60, byp["fresh"], BYPASS_FRESH_SEC // 60))
    elif any(p["missing"] and (p["oldest_min"] or 0) >= STUCK_SEC / 60 for p in pkgs):
        bad = [p for p in pkgs if p["missing"]]
        verdict = "shards_waiting"
        hint = "；".join("%s 收 %d/%d（滞留 %d 分钟，缺 %s）"
                        % (p["pkg"], p["have"], p["total"], p["oldest_min"],
                           ",".join(str(i) for i in p["missing"][:8]))
                        for p in bad)
    elif send_fail["exists"] and send_fail["size"] > 0:
        verdict = "receipt_failed"
        hint = ("入库可能已成功，但**回执发不出去**（send-fail.log %d 字节，%s 分钟前）"
                % (send_fail["size"], _age_min(send_fail["mtime"], now)))
    elif recent_done:
        verdict, hint = "ok", "最近一次入库在 %d 分钟前 ✓" % last_min
    elif last is not None and (last_min or 999) <= 24 * 60:
        verdict, hint = "ok", "最近一次入库在 %d 分钟前 ✓" % last_min
    elif pkgs:
        verdict, hint = "ok", "有 %d 个包在收，未到滞留阈值" % len(pkgs)

    # 堆积是**卫生问题**，不是链路故障 ⇒ 不参与 verdict，只做提示 ✓
    warning = None
    if byp["count"] >= BACKLOG_WARN:
        # 时间单位自适应 ✓ —— 「最老 0.0 天前」是废话 ✗（清理后剩下的都是分钟级 ✓）
        age = byp["oldest_min"] or 0
        age_txt = ("%d 分钟前" % age if age < 60
                   else "%.0f 小时前" % (age / 60) if age < 1440
                   else "%.1f 天前" % (age / 1440))
        warning = ("插件层已堆积 %d 个历史文件（最老 %s）—— 不影响链路，"
                   "但会让排查变慢，可点「清理堆积」挪进 archive 子目录"
                   % (byp["count"], age_txt))

    return {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "verdict": verdict,
        "hint": hint,
        "warning": warning,
        "packages": pkgs,
        "bypass_in": byp,
        "last_ingest": last,
        "send_fail": {"exists": send_fail["exists"], "size": send_fail["size"],
                      "age_min": _age_min(send_fail["mtime"], now)},
        "runtime_copy": runtime_copy_status(),
        "gateway_log": {"exists": gw["exists"],
                        "age_min": _age_min(gw["mtime"], now)},
        "paths": {"bypass_in": BYPASS_IN, "shard_in": SHARD_IN,
                  "send_fail": SEND_FAIL, "gateway_log": GW_LOG},
    }


#: 归档目录保留天数 ✓ —— 2026-10-29 用户口径「历史归档只保留最近 3 天」
ARCHIVE_KEEP_DAYS = 3


def _prune_archives(keep_days, now):
    """删掉超过 `keep_days` 天的 `archive_*` 目录 ✓ —— 归档**不轮转**会无限涨 ✗。

    目录名是 `archive_%m%d-%H%M`（**没有年份** ✗）⇒ 不能用名字算年龄，
    改用目录 mtime ✓（里面的文件都是同一批挪进去的）。

    ⚠️ 删除**不可恢复** ✓ —— 2026-10-29 用户明确裁定「可以接受」✓。
    里面的文件都是**已被消费过**的消息记录，删掉不影响入库 ✓。
    """
    if not keep_days or keep_days <= 0:
        return 0
    cutoff = now - keep_days * 86400
    removed = 0
    try:
        names = os.listdir(BYPASS_IN)
    except OSError:
        return 0
    for n in names:
        if not n.startswith("archive_"):
            continue
        p = os.path.join(BYPASS_IN, n)
        if not os.path.isdir(p):
            continue
        try:
            if os.path.getmtime(p) > cutoff:
                continue
            shutil.rmtree(p)
            removed += 1
        except OSError:
            pass                       # 单个删不掉不影响其余 ✓
    return removed


def archive_backlog(older_than_sec=1800, now=None, keep_days=ARCHIVE_KEEP_DAYS):
    """把插件层的历史文件挪进 `archive_<MMDD-HHMM>/` —— **不删** ✓，可回滚 ✓。

    为什么挪**文件**而不是整个目录：插件按固定路径写盘，
    整个目录被 mv 走之后新写入会失败 ✗；只挪文件则目录始终在 ✓。
    为什么只挪 30 分钟前的：避免打断正在处理的那条 ✓。
    为什么只动 `fg-sync-bypass-in/`：`fg-sync-in/` 是 watcher 的待入库分片，
    动它会丢包 ✗（那个目录的清理由 watcher 自己负责 ✓）。
    """
    now = time.time() if now is None else now
    if not os.path.isdir(BYPASS_IN):
        return {"moved": 0, "dest": None, "reason": "插件层目录不存在（本机不是 Mac？）"}
    old = []
    for n in _list_md(BYPASS_IN):
        mt = _stat(os.path.join(BYPASS_IN, n))["mtime"]
        if mt and now - mt >= older_than_sec:
            old.append(n)
    if not old:
        return {"moved": 0, "dest": None,
                "reason": "没有超过 %d 分钟的文件" % (older_than_sec // 60)}
    dest = os.path.join(BYPASS_IN, "archive_" + time.strftime("%m%d-%H%M"))
    os.makedirs(dest, exist_ok=True)
    moved = 0
    for n in old:
        try:
            os.replace(os.path.join(BYPASS_IN, n), os.path.join(dest, n))
            moved += 1
        except OSError:
            pass                       # 单个文件挪不动就跳过，不影响其余 ✓
    # 2026-10-29：顺手轮转归档 ✓ —— 只挪不删的话磁盘会一直涨 ✗
    pruned = _prune_archives(keep_days, now)
    return {"moved": moved, "dest": dest, "reason": None,
            "pruned": pruned, "keep_days": keep_days}


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
