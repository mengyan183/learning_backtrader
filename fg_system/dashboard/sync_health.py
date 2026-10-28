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
import os
import re
import time

HOME = os.path.expanduser("~")
OC = os.path.join(HOME, ".openclaw")
BYPASS_IN = os.path.join(OC, "tmp", "fg-sync-bypass-in")
SHARD_IN = os.path.join(OC, "tmp", "fg-sync-in")
SEND_FAIL = os.path.join(SHARD_IN, "send-fail.log")
GW_LOG = os.path.join(HOME, "Library", "Logs", "openclaw", "gateway.log")

#: 分片文件名约定：`sync_<包>_<序号>.md`（见 skills/fg-sync/scripts/fg-sync-watcher.py）
_SHARD_RE = re.compile(r"^(?P<pkg>.+)_(?P<seq>\d+)\.md$")

#: 半收滞留多久算「卡住」（秒）—— 与 watcher 的 INCOMPLETE_NOTIFY_SEC 同值
STUCK_SEC = 600


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


def collect():
    """返回体检结果（纯读，不写任何文件，不联网）。"""
    now = time.time()
    oc_ok = os.path.isdir(OC)
    pkgs = _packages(now) if oc_ok else []
    bypass_files = _list_md(BYPASS_IN) if oc_ok else []
    send_fail = _stat(SEND_FAIL)
    gw = _stat(GW_LOG)
    last = _last_ingest(now)

    # ---- 判定（顺序即优先级：越靠前越严重）----
    verdict, hint = "idle", "链路空闲：没有滞留分片，也没有进行中的包"
    if not oc_ok:
        verdict = "unknown"
        hint = ("本机没有 ~/.openclaw ⇒ 不是 Mac（Windows 侧正常现象）"
                "或 OpenClaw 未安装 ✗")
    elif bypass_files and not pkgs:
        verdict = "bypass_stuck"
        hint = ("%d 个文件已落到插件层，但分片目录为空 ⇒ **bypass 没被调用** ✗"
                "（worker 未消费，与 2026-10-28 事故同型）" % len(bypass_files))
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
    elif last is not None and (last["age_min"] or 999) <= 24 * 60:
        verdict, hint = "ok", "最近一次入库在 %d 分钟前 ✓" % last["age_min"]
    elif pkgs:
        verdict, hint = "ok", "有 %d 个包在收，未到滞留阈值" % len(pkgs)

    return {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "verdict": verdict,
        "hint": hint,
        "packages": pkgs,
        "bypass_in": {"count": len(bypass_files),
                      "files": sorted(bypass_files)[:5]},
        "last_ingest": last,
        "send_fail": {"exists": send_fail["exists"], "size": send_fail["size"],
                      "age_min": _age_min(send_fail["mtime"], now)},
        "gateway_log": {"exists": gw["exists"],
                        "age_min": _age_min(gw["mtime"], now)},
        "paths": {"bypass_in": BYPASS_IN, "shard_in": SHARD_IN,
                  "send_fail": SEND_FAIL, "gateway_log": GW_LOG},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
