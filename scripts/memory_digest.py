#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总 `evolution/memory/` 的现状与最近内容 ✓（2026-11-24 用户要求）。

【为什么需要】
  同步工具**只提交包内文件**（`fg_sync_ingest.py:623-625` 刻意不用 `git add -A`），
  而 `evolve_review.py` / 每日链写出的 `evolution/memory/YYYY-MM-DD.md`
  **不在任何包里** ⇒ 只留在 Mac 本地 ⇒ Windows 侧完全看不到 ✗
  实测：origin 上该目录最新只到 **2026-11-12**（缺 12 天）✗

⇒ 本脚本把「有哪些文件 / 最新几篇写了什么」一次性打到 stdout，
  经 `run_script` 回执带回来 ✓ 不改仓库、不写盘 ✓

用法（Mac，经队列）：
    python scripts/memory_digest.py
"""
from __future__ import annotations

import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEM = os.path.join(REPO, "evolution", "memory")


def _tail_lines(path, n):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()[-n:]
    except OSError as e:
        return ["<读取失败：%s>" % e]


def main():
    if not os.path.isdir(MEM):
        print("目录不存在：%s" % MEM)
        return 1

    files = sorted(glob.glob(os.path.join(MEM, "*.md")))
    dated = [os.path.basename(f)[:10] for f in files
             if re.match(r"^\d{4}-\d{2}-\d{2}", os.path.basename(f))]
    print("目录：%s" % os.path.relpath(MEM, REPO))
    print("文件数：%d（其中日期命名 %d 个）" % (len(files), len(dated)))
    if dated:
        print("日期范围：%s → %s" % (dated[0], dated[-1]))
        # 列出最近 10 个日期，看有没有断档
        print("最近 10 个：%s" % ", ".join(dated[-10:]))

    # 最近 2 篇的尾部 —— 足够看出「跑没跑 / 报什么错」
    for f in files[-2:]:
        print("\n" + "=" * 60)
        print("## %s" % os.path.basename(f))
        for ln in _tail_lines(f, 40):
            print(ln)

    # 失败痕迹单独捞一遍（跨全部文件，只看最近 5 篇）
    print("\n" + "=" * 60)
    print("## 失败痕迹（最近 5 篇里含「失败 / ✗」的行）")
    hit = 0
    for f in files[-5:]:
        for ln in _tail_lines(f, 400):
            if ("失败" in ln) or ("✗" in ln and "evolve_review" in ln):
                print("%s | %s" % (os.path.basename(f), ln.strip()[:200]))
                hit += 1
    if not hit:
        print("（无）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
