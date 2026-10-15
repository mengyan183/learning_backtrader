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

HOME = os.path.expanduser("~")
IN_DIR = os.path.join(HOME, ".openclaw", "tmp", "fg-sync-in")
REPO = "/Users/xingguo/learning_backtrader"
FG_RE = re.compile(r"###FG:([^:#\n]+):(\d+)/(\d+)###([\s\S]*?)###FG:end###")


def _load_bypass():
    """加载 fg-sync-bypass.py 复用 send_feishu / ingest_package。"""
    path = os.path.join(REPO, "skills", "fg-sync", "scripts", "fg-sync-bypass.py")
    spec = importlib.util.spec_from_file_location("fg_bypass_w", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


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
        d["recv"] = len([s for s in d["recv"] if s <= (total or 1 << 30)])
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
            continue  # 未收齐，静默等待
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
        # 仅确认入库成功（rc=0，或"无变更可提交"=已入库过同内容）才写 done 并清理；
        # 失败（rc=2/3 或白名单拒绝）保留分片供排查、不写 done，允许重发重试。
        if rc == 0 or "可能无变更可提交" in out:
            with open(marker, "w", encoding="utf-8") as f:
                f.write(cur)
            for i in range(1, total + 1):
                fp = os.path.join(IN_DIR, f"sync_{pkg}_{i}.md")
                if os.path.exists(fp):
                    os.remove(fp)
            if os.path.exists(sync_file):
                os.remove(sync_file)
            bypass.send_feishu(
                f"✅ {pkg} 已收齐 {total} 片，开始入库…\n{out}",
                "oc_a9306b326943821490184d073dae9a65",
            )
            handled += 1
        else:
            bypass.send_feishu(
                f"⛔ {pkg} 入库失败（rc={rc}），分片已保留待排查：\n{out}",
                "oc_a9306b326943821490184d073dae9a65",
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
