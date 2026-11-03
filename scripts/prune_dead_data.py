#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**删除死数据文件** ✓（2026-11-03 用户裁定）。

【什么是「死文件」】
  `scripts/audit_data_files.py` 的判定：
    ① **无人读**（代码里没有任何 `read_csv` / `load_prices` 引用）
    ② **无人写**（代码里没有任何 `to_csv` / `writer` 引用）
  ⇒ 两头都没有 ⇒ 它既不产生价值也不更新 ✗ 纯占空间 ✗

【为什么可以安全删】
  - `Data/raw/` 已进 `.gitignore` ✓ ⇒ 删除**不影响 git** ✓
  - 删除前会**先备份**到 `dist/pruned/` ✓（万一误判可恢复 ✓）
  - 只删 `Data/raw/` 下明确列出的文件 ✓ 不递归扫 ✗

【17 个死文件**不在**此列表，请先跑 audit 确认】
  本列表是 2026-11-03 的审计快照 ✗ 数据/代码会变 ⇒ 定期重跑 audit ✓

用法：
  .venv/bin/python scripts/prune_dead_data.py            # 只看（dry-run）
  .venv/bin/python scripts/prune_dead_data.py --apply    # 真删（先备份）
  .venv/bin/python scripts/prune_dead_data.py --apply --no-backup
"""
import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data" / "raw"
BACKUP = REPO / "dist" / "pruned"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

#: 2026-11-03 审计出的**死文件** ✓（无人读 + 无人写）
#: ⚠️ 加新条目必须**先跑 audit** 确认 ✗ 别凭印象加 ✗
DEAD = (
    # --- putcall 原始分项（只被 `putcall.csv` 汇总使用，分项本身无人读 ✗）
    "equitypc.csv", "equitypcarchive.csv", "etppc.csv",
    "indexpc.csv", "indexpcarchive.csv", "pcratioarchive.csv",
    "spxpc.csv", "totalpc.csv", "totalpcarchive.csv", "vixpc.csv",
    # --- putcall 日快照（已废弃 ✗ 最新 `putcall.csv` 才是唯一来源）
    "putcall_daily_1.csv", "putcall_daily_2.csv", "putcall_daily_latest.csv",
    # --- FRED 已停抓且无人读
    "fred_DCOILBRENTEU.csv", "fred_DCOILWTICO.csv", "fred_T10Y2Y.csv",
    # --- 其他
    "fedwatch.csv", "fng_altme.csv", "sp500_cape.csv", "crypto_fng.csv",
    "shoutu_history.csv", "splits.csv", "shoutu_etf_universe.csv",
)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="**真删** ✓（默认只 dry-run ✓）")
    ap.add_argument("--no-backup", action="store_true",
                    help="不备份（不推荐 ✗ 误判就找不回来了）")
    args = ap.parse_args(argv)

    present, missing = [], []
    for n in DEAD:
        p = DATA / n
        (present if p.exists() else missing).append(n)

    total = sum((DATA / n).stat().st_size for n in present) if present else 0
    print("# 死文件清理（%s）\n" % ("**真删** ✓" if args.apply else "dry-run ✗"))
    print("| 文件 | 大小 |")
    print("|---|---|")
    for n in present:
        sz = (DATA / n).stat().st_size
        print("| `%s` | %.1f KB |" % (n, sz / 1024.0))
    print("\n**共 %d 个，%.1f MB**（另有 %d 个已不存在 ✓）"
          % (len(present), total / 1024.0 / 1024.0, len(missing)))

    if not args.apply:
        print("\n⇒ 只 dry-run ✓ 加 `--apply` 才真删 ✗")
        return 0
    if not present:
        print("\n✓ 无需清理")
        return 0

    if not args.no_backup:
        BACKUP.mkdir(parents=True, exist_ok=True)
        for n in present:
            shutil.copy2(DATA / n, BACKUP / n)
        print("\n✓ 已备份到 `%s`（%d 个）"
              % (BACKUP.relative_to(REPO).as_posix(), len(present)))

    ok = 0
    for n in present:
        try:
            (DATA / n).unlink()
            ok += 1
        except OSError as exc:
            print("✗ 删 %s 失败：%s" % (n, exc))
    print("✓ 已删除 %d / %d 个" % (ok, len(present)))
    print("\n⚠️ `Data/raw/` 已 gitignore ✓ 所以 **git 不会有任何改动** ✗")
    print("   若误删：从 `dist/pruned/` 拷回即可 ✓")
    return 0 if ok == len(present) else 1


if __name__ == "__main__":
    sys.exit(main())
