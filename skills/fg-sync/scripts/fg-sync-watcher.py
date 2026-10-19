#!/usr/bin/env python3
"""fg-sync watcher：分片目录常驻轮询，收齐自动入库（bypass 常驻化）。

由 launchd（com.xingguo.fg-sync-watcher，StartInterval=10s）周期调用。
行为（与 fg-sync-bypass.py 幂等语义一致）：
- 扫描 ~/.openclaw/tmp/fg-sync-in/ 下 `sync_<pkg>_<seq>.md` 分片
- 某包收齐（1..N 全在）且无 .done（或 hash 变化）→ 聚合到 sync_in.md → 跑
  fg_sync_tool.py --quick 入库 → 写 .done → 清该包分片 → 飞书回传
- 未收齐 → 静默等待（不回传，避免刷屏）
- 已入库同内容（.done hash 一致）→ 幂等跳过

调用：.venv/bin/python fg-sync-watcher.py
退出码：0 正常（无论是否处理）；非 0 异常
"""
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
IN_DIR = os.path.join(HOME, ".openclaw", "tmp", "fg-sync-in")
REPO = "/Users/xingguo/learning_backtrader"
FG_RE = re.compile(r"###FG:([^:#\n]+):(\d+)/(\d+)###([\s\S]*?)###FG:end###")
# 分片不齐且最早分片已滞留 ≥10 分钟 → 回一次「还缺第 X 片」提示（每包仅一次，不刷屏）
INCOMPLETE_NOTIFY_SEC = 600
CHAT_ID = "oc_a9306b326943821490184d073dae9a65"


def _load_bypass():
    """加载 fg-sync-bypass.py 复用 send_feishu / ingest_package。"""
    path = os.path.join(REPO, "skills", "fg-sync", "scripts", "fg-sync-bypass.py")
    spec = importlib.util.spec_from_file_location("fg_bypass_w", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _git(repo, *args):
    """在 repo 下跑一条 git 命令，失败一律返回空串（回执不应因 git 抖动而中断）。"""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _success_receipt(pkg, repo, rc, out):
    """构造 success 分支的回执文本（MT-40，2026-10-19）。

    为什么必须有：`sync_1019o` / `sync_1019p` 由本兜底路径入库成功 ✗，
    却**不发任何回执** ✗ ⇒ 对端只能人工来问「是不是没收到」✗。
    失败分支早有 ⛔ 回执 ✓，成功分支同样必须可观测 ✓（同 `21ddbab` 的纪律：
    成功与失败都不能静默 ✗）。回执带**每文件 blob hash** ⇒ 对端可与包内
    `index` 行自行核对，不必再来问 ✓。
    """
    if rc != 0:
        # "可能无变更可提交" = 同内容早已入库 ⇒ 无新提交，说明清楚即可
        return (f"✅ {pkg} 内容已在库（rc={rc}，无新提交）\n"
                f"{out[:300]}")
    sha = _git(repo, "rev-parse", "--short", "HEAD")
    subject = _git(repo, "log", "-1", "--format=%s")
    files = [f for f in _git(repo, "show", "--name-only", "--format=", "HEAD").split("\n")
             if f.strip()]
    lines = [f"✅ {pkg} 已入库并推送", f"提交 {sha}　{subject}",
             f"落地 {len(files)} 个文件："]
    for f in files[:20]:
        lines.append("· %s　%s" % (f, _git(repo, "hash-object", f)[:12]))
    if len(files) > 20:
        lines.append("… 其余 %d 个略（git show --stat %s）" % (len(files) - 20, sha))
    lines.append("（以上 blob hash 可与包内 index 行逐条核对）")
    return "\n".join(lines)


def scan_packages():
    """返回 {pkg: (recv_count, total)}，recv_count=磁盘分片数。"""
    if not os.path.isdir(IN_DIR):
        return {}
    pkgs = {}
    for name in os.listdir(IN_DIR):
        m = re.match(r"sync_([A-Za-z0-9_]+)_(\d+)\.md$", name)
        if m:
            pkg, seq = m.group(1), int(m.group(2))
            d = pkgs.setdefault(pkg, {"recv": set(), "total": None})
            d["recv"].add(seq)
    # total 从已收分片内的标记解析（任意一片的 2/12 即知 total=12）
    for pkg, d in pkgs.items():
        total = None
        for seq in sorted(d["recv"]):
            fp = os.path.join(IN_DIR, f"sync_{pkg}_{seq}.md")
            try:
                txt = open(fp, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for _, s, t, _ in FG_RE.findall(txt):
                total = int(t)
                break
            if total:
                break
        d["total"] = total
        d["seqs"] = sorted(s for s in d["recv"] if s <= (total or 1 << 30))
        d["recv"] = len(d["seqs"])
        d["missing"] = ([i for i in range(1, total + 1) if i not in set(d["seqs"])]
                        if total else [])
    return pkgs


def main():
    if not os.path.isdir(IN_DIR):
        return 0
    pkgs = scan_packages()
    if not pkgs:
        return 0
    bypass = _load_bypass()
    today = __import__("datetime").date.today().isoformat()
    handled = 0
    for pkg, d in pkgs.items():
        total = d["total"]
        if not total or d["recv"] < total:
            # 未收齐：超时一次性提示（每包只提示一次，不刷屏）——2026-10-19
            if total and d["seqs"]:
                oldest = min(
                    (os.path.getmtime(os.path.join(IN_DIR, f"sync_{pkg}_{i}.md"))
                     for i in d["seqs"]
                     if os.path.exists(os.path.join(IN_DIR, f"sync_{pkg}_{i}.md"))),
                    default=None,
                )
                flag = os.path.join(IN_DIR, f"sync_{pkg}.notified")
                if oldest is not None and time.time() - oldest >= INCOMPLETE_NOTIFY_SEC:
                    # 原子抢占：O_EXCL 创建成功者才发提示 ⇒ launchd 与手工调用并发时只发一次
                    try:
                        fd = os.open(flag, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    except FileExistsError:
                        pass  # 另一路径已提示过，静默
                    else:
                        with os.fdopen(fd, "w", encoding="utf-8") as f:
                            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
                        miss = "、".join(str(x) for x in d["missing"])
                        bypass.send_feishu(
                            f"⚠️ {pkg} 分片不齐：已收 {d['recv']}/{total} 片，"
                            f"还缺第 {miss} 片，请补发（最早分片已滞留超 "
                            f"{INCOMPLETE_NOTIFY_SEC // 60} 分钟）",
                            CHAT_ID,
                        )
            continue  # 未收齐，静默等待（仅超时补一次缺片提示）
        # 延迟兜底：分片刚落盘（最近分片 mtime < 60s）说明 bypass 主通道正在/即将
        # 处理（bypass 落盘后立即 ingest_package），本 tick 跳过，避免双路径并发跑
        # 同一 fg_sync_tool.py 导致 git 竞争/冲突误判与重复回传（2026-10-15）。
        # 只有分片滞留 ≥60s（bypass 未触发或失败）才兜底入库。
        newest = 0.0
        for i in range(1, total + 1):
            fp = os.path.join(IN_DIR, f"sync_{pkg}_{i}.md")
            if os.path.exists(fp):
                newest = max(newest, os.path.getmtime(fp))
        if time.time() - newest < 60:
            continue
        # 幂等：hash 一致且 .done 存在 → 跳过。
        # ⚠️ 标记文件名用完整包名（sync_ 前缀）——与 fg-sync-bypass.py 共用
        #    `sync_<包>.done`，否则双路径各写各的标记 ⇒ 同一包被处理两次（2026-10-15 修复）。
        marker = os.path.join(IN_DIR, f"sync_{pkg}.done")
        h = hashlib.sha256()
        for i in range(1, total + 1):
            fp = os.path.join(IN_DIR, f"sync_{pkg}_{i}.md")
            if os.path.exists(fp):
                h.update(open(fp, "rb").read())
        cur = h.hexdigest()
        if os.path.exists(marker) and open(marker).read().strip() == cur:
            # 已入库同内容：仅补清理残留分片
            for i in range(1, total + 1):
                fp = os.path.join(IN_DIR, f"sync_{pkg}_{i}.md")
                if os.path.exists(fp):
                    os.remove(fp)
            continue
        # 聚合分片 → sync_in.md → 入库
        parts = []
        for i in range(1, total + 1):
            fp = os.path.join(IN_DIR, f"sync_{pkg}_{i}.md")
            if os.path.exists(fp):
                parts.append(open(fp, encoding="utf-8", errors="replace").read().strip())
        if not parts:
            continue
        combined = "\n".join(parts)
        sync_file = os.path.join(IN_DIR, "sync_in.md")
        with open(sync_file, "w", encoding="utf-8") as f:
            f.write(combined)
        cmd = [
            os.path.join(REPO, ".venv", "bin", "python"),
            os.path.join(REPO, "scripts", "fg_sync_tool.py"),
            "-f", sync_file,
            "--commit", f"fg-sync: {pkg} 公司端同步 {today}",
            "--quick", "--brief",
        ]
        try:
            r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=180)
            out = (r.stdout + r.stderr).strip()
            rc = r.returncode
        except subprocess.TimeoutExpired:
            out = "⏳ 入库超时（180s），请稍后查收"
            rc = 3
        # 仅确认入库成功才写 done 并清理（2026-10-16 加固）：
        #   success = (rc==0 或"无变更可提交"=已入库过同内容) **且** out 不含 ⛔/❌。
        # 失败关键字优先：即使 out 混入"可能无变更可提交"（如 commit 无变更后 pytest 失败），
        # 只要含 ⛔/❌ ⇒ 判失败 ⇒ 不写 done、不清分片、允许重发重试（1016t/1016u 误判根因）。
        success = ((rc == 0 or "可能无变更可提交" in out)
                   and "⛔" not in out and "❌" not in out)
        if success:
            with open(marker, "w", encoding="utf-8") as f:
                f.write(cur)
            nflag = os.path.join(IN_DIR, f"sync_{pkg}.notified")
            if os.path.exists(nflag):
                try:
                    os.remove(nflag)
                except OSError:
                    pass
            for i in range(1, total + 1):
                fp = os.path.join(IN_DIR, f"sync_{pkg}_{i}.md")
                if os.path.exists(fp):
                    os.remove(fp)
            if os.path.exists(sync_file):
                os.remove(sync_file)
            handled += 1
            # MT-40：成功也必须可观测 ⇒ 与失败分支对称发回执。
            # send_feishu 内部已做重试 + 最终失败落 send-fail.log ⇒ 此处不再吞错。
            bypass.send_feishu(_success_receipt(pkg, REPO, rc, out), CHAT_ID)
        else:
            bypass.send_feishu(
                f"⛔ {pkg} 入库失败（rc={rc}），分片已保留待排查：\n{out}",
                CHAT_ID,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
