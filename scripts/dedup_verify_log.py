#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理 `evolution/verify-log/*.md` 里的**重复行** ✓。

【为什么】
    2026-11-19 实测：`H-002.md` 里 `2026-11-18 验证：...` 出现 **3 次** ✗
    原因：同一天手动 `run_script` 触发 2 次 + launchd 定时任务 1 次 ✗
    每次 `_apply` 都追加 ⇒ 归档文件里全是重复行 ✗
    （`_append_verify_log` 已加去重 ✓ 本脚本清历史遗留）

【做什么】
    只删**相邻完全相同**的行（历史重复都是相邻的 ✓）
    保留第一条，删掉后续重复 ✓
    ⚠️ 不删非相邻重复（避免误删「隔了几天又出现同样结论」的正常记录）

【用法】
    python3 scripts/dedup_verify_log.py --dry-run   # 先看会删多少
    python3 scripts/dedup_verify_log.py             # 真删
"""
import argparse
import glob
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE, "evolution", "verify-log")


def dedup_lines(lines):
    """去掉**相邻**完全相同的行 ✓，返回 (新行列表, 删除数)。"""
    out = []
    removed = 0
    for ln in lines:
        if out and ln == out[-1]:
            removed += 1
            continue
        out.append(ln)
    return out, removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(LOG_DIR):
        print("目录不存在：%s" % LOG_DIR)
        return 0

    files = sorted(glob.glob(os.path.join(LOG_DIR, "*.md")))
    total = 0
    changed = 0
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as e:
            print("  [skip] %s：%s" % (os.path.basename(p), e))
            continue
        new, removed = dedup_lines(lines)
        if not removed:
            continue
        total += removed
        changed += 1
        print("  %-12s 删 %d 行（%d → %d）"
              % (os.path.basename(p), removed, len(lines), len(new)))
        if args.dry_run:
            continue
        bak = p + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(p, bak)
            with open(p, "w", encoding="utf-8") as f:
                f.writelines(new)
        except OSError as e:
            print("  [warn] %s 写入失败：%s" % (os.path.basename(p), e))

    print()
    print("扫描 %d 个文件；%d 个有重复；共删 %d 行%s"
          % (len(files), changed, total,
             "（--dry-run，未写入）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
