#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `evolution/hypotheses.md` 备注列里的**每日验证记录**搬到独立文件 ✓。

【为什么】
    2026-11-18 用户要求治理膨胀：备注列用 `<br>` 每日追加，
    实测 H-002 累积 35 条（2026-10-19 ~ 11-17）⇒ 单行几百字、diff 噪音大 ✗

【做什么】
    ① 备份 `hypotheses.md` → `.bak-<时间戳>`
    ② 逐行拆备注列的 `<br>` 片段：
         · 含「验证：」的 ⇒ 追加到 `evolution/verify-log/<H-ID>.md`
         · 不含的（原始登记说明）⇒ 保留在表格里
    ③ 表格备注列 = 原始说明 + **最新一条验证** + 「明细见 …」链接
    ④ 幂等：再跑一次不会有变化（已迁移的条目不含 `<br>` 验证块）

【用法】
    py -3.10 scripts/migrate_verify_log.py --dry-run   # 先看会改什么
    py -3.10 scripts/migrate_verify_log.py             # 真跑
"""
import argparse
import os
import re
import shutil
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts"))

from evolve_verify import (HYP, HYP_COLS, VERIFY_LOG_DIR,  # noqa: E402
                           _append_verify_log, _row_cells)

VER_RE = re.compile(r"^\d{4}-\d{2}-\d{2} 验证：")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(HYP, encoding="utf-8") as f:
        lines = f.readlines()

    moved = kept_total = 0
    out = []
    for ln in lines:
        if not ln.startswith("| H-"):
            out.append(ln)
            continue
        cells = _row_cells(ln)
        if len(cells) != HYP_COLS:
            out.append(ln)
            continue
        hid = cells[0].strip()
        parts = [s.strip() for s in cells[6].split("<br>") if s.strip()]
        notes = [s for s in parts if VER_RE.match(s)]
        keep = [s for s in parts if not VER_RE.match(s)]
        if not notes:
            out.append(ln)
            continue

        # 最新一条按日期字符串排序（ISO 日期可直接比较）
        notes.sort(key=lambda s: s[:10])
        latest = notes[-1]
        moved += len(notes)
        kept_total += len(keep)

        if not args.dry_run:
            for n in notes:
                _append_verify_log(hid, n)
        link = "明细见 `evolution/verify-log/%s.md`" % hid
        cells[6] = "<br>".join(keep + [latest, link])
        out.append("| " + " | ".join(cells) + " |\n")

    print("将迁移 %d 条验证记录；保留原始说明 %d 条" % (moved, kept_total))
    if args.dry_run:
        print("（--dry-run，未写入）")
        return 0
    if not moved:
        print("无需迁移 ✓")
        return 0

    bak = HYP + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(HYP, bak)
    print("已备份 → %s" % os.path.basename(bak))
    with open(HYP, "w", encoding="utf-8") as f:
        f.writelines(out)
    print("已写入 %s" % HYP)
    print("归档目录：%s" % VERIFY_LOG_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
