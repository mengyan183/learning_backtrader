#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描「**每次跑都变**」的噪声文件 ✓（2026-11-03）。

【为什么需要】

`git status` 长期被这类文件污染 ✗ 掩盖真正的改动 ✗
已发现并处理的 5 个：
  - `Data/freshness_warning.txt`     数据新鲜度告警（含「距今 N 天」✗）
  - `Data/last_brief_check.json`     简报检查时间戳 ✗
  - `Data/brief_check_history.jsonl` 检查历史（追加型 ✗）
  - `Data/realtime_state.json`       实时价格快照（改动 15 次 ✗）
  - `Data/raw/fedwatch_session.json` CME 抓取会话 ID ✗

【判据】（重要 ✗ 别一刀切）

    内容会不会因为「今天跑了一次」而变？
        会 + 只是快照/会话/时间戳   ⇒ **应 ignore** ✗
        会 + 是业务状态（熔断/弹药/持仓）⇒ **保留入库** ✓
        不会                        ⇒ 保留 ✓

  ⚠️ `Data/state.json` 就是「会变但必须入库」的例外 ✓
     —— 熔断/弹药状态**跨机必须一致** ✗ 否则一边熔断一边不熔断 ✗

【检测方式】

  ① **已追踪**的文件：查最近 N 次提交里的改动次数
     改动 ≥ 阈值 且 文件名命中「噪声词」⇒ 可疑 ✗
  ② **未追踪**的文件（`git status` 的 `??`）：直接列出 ✓

用法：
  .venv/bin/python scripts/check_untracked_noise.py
  .venv/bin/python scripts/check_untracked_noise.py --commits 30
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

#: 文件名里出现这些词 ⇒ 大概率是运行时快照 ✗
#: ⚠️ **别用 `history` / `log`** ✗ —— 实测误报：
#:    `Data/raw/vix_history.csv` / `shoutu_history.csv` 是**原始数据** ✓
#:    `Data/trade_log.csv` 是**交易记录** ✓
#:    它们常变是因为「每天有新数据」✓ 不是噪声 ✗
NOISE_WORDS = ("warning", "check", "session", "realtime", "cache", "tmp")
#: **白名单**：会变但必须入库 ✓（业务状态）
KEEP = {
    "Data/state.json",              # 熔断/弹药，跨机必须一致 ✓
    "Data/crypto_state.json",       # 加密状态 ✓
    "Data/positions.csv",           # 持仓快照（业务数据 ✓）
    "Data/accounts.csv",            # 账户快照（业务数据 ✓）
}
#: 只扫这些目录（别把 `Data/raw/` 的历史数据算进来 ✗）
SCAN_DIRS = ("Data", "evolution")
#: **排除**这些前缀 ✓ —— 原始数据/业务数据必然常变 ✓ 不是噪声 ✗
EXCLUDE_PREFIX = ("Data/raw/", "Data/kb/")


def _run(cmd):
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                           timeout=120)
        return r.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _tracked():
    out = _run(["git", "ls-files"])
    return [x for x in out.splitlines() if x.strip()]


def _commit_count(rel, limit):
    """最近 `limit` 次提交里，`rel` 被改了几次 ✓。"""
    out = _run(["git", "log", "--format=%h", "-%d" % limit, "--", rel])
    return len([x for x in out.splitlines() if x.strip()])


def _untracked():
    out = _run(["git", "status", "--porcelain"])
    return [x[3:].strip() for x in out.splitlines() if x.startswith("??")]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--commits", type=int, default=20,
                    help="看最近多少次提交（默认 20）")
    ap.add_argument("--min-changes", type=int, default=3,
                    help="改动次数阈值（默认 3）")
    ap.add_argument("--existing-only", action="store_true",
                    help="**只扫本机实际存在的文件** ✓（跳过「索引有但本地没有」✗）")
    args = ap.parse_args(argv)

    print("# 噪声文件扫描（最近 %d 次提交；阈值 ≥%d 次改动）\n"
          % (args.commits, args.min_changes))

    # ---------- ① 已追踪但频繁改动 ----------
    suspects = []
    for rel in _tracked():
        if rel in KEEP:
            continue
        if not rel.startswith(SCAN_DIRS):
            continue
        if rel.startswith(EXCLUDE_PREFIX):
            continue
        if not rel.endswith((".json", ".jsonl", ".txt", ".csv")):
            continue
        # 🔴 `--existing-only` ✓（2026-11-03 用户要求）：
        #    索引里有但**本地不存在**的文件（另一台机器提交的 ✗）
        #    扫了没意义 ✗ —— 本机看不到内容、也不知道是否还在用 ✗
        if args.existing_only and not (REPO / rel).exists():
            continue
        n = _commit_count(rel, args.commits)
        if n < args.min_changes:
            continue
        low = rel.lower()
        hit = [w for w in NOISE_WORDS if w in low]
        suspects.append((n, rel, hit))

    print("## ① 已追踪 · 改动频繁（**候选 ignore** ✗）\n")
    if not suspects:
        print("（无 ✓）\n")
    else:
        print("| 改动次数 | 文件 | 命中噪声词 | 建议 |")
        print("|---|---|---|---|")
        for n, rel, hit in sorted(suspects, reverse=True):
            advice = ("**建议 ignore** ✗" if hit
                      else "人工判断（无噪声词 ✗）")
            print("| %d | `%s` | %s | %s |"
                  % (n, rel, "、".join(hit) or "—", advice))
        print("\n⚠️ 判据不是「改动多」✗ 而是「**会不会因为跑了一次就变**」✓")
        print("   业务状态（熔断/弹药/持仓）即使常变也**保留入库** ✓\n")

    # ---------- ② 未追踪文件 ----------
    un = [x for x in _untracked() if x.startswith(SCAN_DIRS)]
    print("## ② 未追踪（`git status` 的 `??`）\n")
    if not un:
        print("（无 ✓）\n")
    else:
        print("| 文件 | 建议 |")
        print("|---|---|")
        for rel in un[:30]:
            low = rel.lower()
            hit = [w for w in NOISE_WORDS if w in low]
            advice = ("**应 ignore** ✗" if hit
                      else "确认后入库或 ignore")
            print("| `%s` | %s |" % (rel, advice))
        if len(un) > 30:
            print("| …（共 %d 个）| — |" % len(un))
        print()

    # ---------- ③ 白名单 ----------
    print("## ③ 白名单（会变但**必须入库** ✓）\n")
    for rel in sorted(KEEP):
        exists = (REPO / rel).exists()
        print("- `%s`%s" % (rel, "" if exists else "  ← ⚠️ 本地不存在"))

    n_bad = len(suspects) + len([x for x in un
                                 if any(w in x.lower() for w in NOISE_WORDS)])
    print("\n⇒ 共 %d 个可疑文件%s"
          % (n_bad, " ✓" if n_bad == 0 else " ✗ 建议逐个确认"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
