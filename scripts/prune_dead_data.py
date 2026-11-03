#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**删除死数据文件** ✓（2026-11-03 用户裁定）。

🔴 **2026-11-03 事故（必须记住）**：
   第一版删了 13 个「死文件」✗ 其中 **3 个是错的** ✗：
     - `fedwatch.csv`         ← 监控在读（用户当天收到「文件缺失」告警 ✗）
     - `shoutu_history.csv`   ← `check_freshness.py:34` 的 `REF_PRODUCTS` 在读 ✗
     - `fred_T10Y2Y.csv`      ← 同上，监控在读 ✗
   **根因**：`audit_data_files.py` 是**静态扫描** ✗ 它找「谁 read_csv 这个文件名」✗
   但监控脚本用的是**硬编码清单**（`REF_PRODUCTS` 里直接写路径 ✗）
   或**动态拼名**（`"%s.csv" % name` ✗）⇒ 静态扫描**永远抓不到** ✗
   ⇒ **教训：审计只能当「候选」✗ 删之前必须交叉核对监控清单 ✓**

【本脚本现在的三重保险】
   ① `--restore`：从 `dist/pruned/` **拷回** ✗（误删可恢复 ✓）
   ② **监控引用白名单** `MONITORED`：只要出现在监控清单里，**永不删** ✓
   ③ 默认 dry-run ✗ 必须 `--apply` 才真删 ✓

用法：
  .venv/bin/python scripts/prune_dead_data.py              # 只看
  .venv/bin/python scripts/prune_dead_data.py --apply      # 真删（先备份）
  .venv/bin/python scripts/prune_dead_data.py --restore    # **全部恢复** ✓
  .venv/bin/python scripts/prune_dead_data.py --restore fedwatch.csv shoutu_history.csv
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

#: 🔴 **监控引用白名单** ✓ —— 出现在这里的一律**不删** ✗
#: 来源：`scripts/check_freshness.py` 的 `REF_PRODUCTS` + 用户 2026-11-03 告警
#: ⚠️ 加监控时必须同步更新这里 ✗ 否则又会被误删 ✗
MONITORED = {
    "shoutu_history.csv",       # check_freshness.py:34 「守猪待兔」
    "fred_DGS10.csv",           # check_freshness.py:43 「10Y国债」
    "sp500_pe.csv",             # check_freshness.py:45
    "sp500_cape.csv",           # check_freshness.py:46
    "fedwatch.csv",             # 2026-11-03 告警：文件缺失
    "fred_T10Y2Y.csv",          # 2026-11-03 告警：文件缺失
    "sentiment.csv",            # 2026-11-03 告警：停更 22 天
    "putcall.csv",              # 2026-11-03 告警：停更 22 天
    "kalshi_fed.csv",           # 2026-11-03 告警：停更 20 天
    "funding_rate.csv",         # 2026-11-03 告警：停更 21 天
    "shoutu_fng.csv",           # 2026-11-03 告警：停更 21 天
    "news_sentiment.csv",       # 2026-11-03 告警：停更 21 天
    "stablecoin_usage.csv",     # 2026-11-03 告警：停更 23 天
    "fred_DFF.csv",             # 2026-11-03 告警：停更 26 天
}

#: 2026-11-03 审计出的**死文件** ✓（已剔除 `MONITORED` 里的 ✗）
DEAD = (
    # --- putcall 原始分项（只被 `putcall.csv` 汇总使用）
    "equitypc.csv", "equitypcarchive.csv", "etppc.csv",
    "indexpc.csv", "indexpcarchive.csv", "pcratioarchive.csv",
    "spxpc.csv", "totalpc.csv", "totalpcarchive.csv", "vixpc.csv",
    # --- putcall 日快照（已废弃）
    "putcall_daily_1.csv", "putcall_daily_2.csv", "putcall_daily_latest.csv",
    # --- FRED 已停抓且无人读
    "fred_DCOILBRENTEU.csv", "fred_DCOILWTICO.csv",
    # --- 其他
    "fng_altme.csv", "crypto_fng.csv",
    "splits.csv", "shoutu_etf_universe.csv",
)


def _restore(names):
    """从 `dist/pruned/` 拷回 ✓。"""
    if not BACKUP.exists():
        print("✗ 备份目录不存在：%s" % BACKUP)
        return 1
    pool = sorted(BACKUP.glob("*.csv"))
    if names:
        want = set(names)
        pool = [p for p in pool if p.name in want]
    if not pool:
        print("✗ 备份里没有匹配的文件")
        return 1
    print("## 恢复（%d 个）\n" % len(pool))
    ok = 0
    for p in pool:
        dest = DATA / p.name
        if dest.exists():
            print("· %s —— 已存在，跳过 ✓" % p.name)
            ok += 1
            continue
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            print("· %s —— ✓ 已恢复" % p.name)
            ok += 1
        except OSError as exc:
            print("· %s —— ✗ %s" % (p.name, exc))
    print("\n✓ 恢复 %d / %d" % (ok, len(pool)))
    return 0 if ok == len(pool) else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="**真删** ✓")
    ap.add_argument("--restore", nargs="*", metavar="FILE",
                    help="**从备份恢复** ✓（不给文件名 = 全恢复 ✓）")
    ap.add_argument("--no-backup", action="store_true", help="不备份（不推荐 ✗）")
    args = ap.parse_args(argv)

    if args.restore is not None:
        return _restore(args.restore)

    # 白名单过滤 ✓
    blocked = [n for n in DEAD if n in MONITORED]
    if blocked:
        print("⚠️ 以下文件在**监控白名单**里 ⇒ **不删** ✓：")
        for n in blocked:
            print("   · %s" % n)
        print()

    present, missing = [], []
    for n in DEAD:
        if n in MONITORED:
            continue
        p = DATA / n
        (present if p.exists() else missing).append(n)

    total = sum((DATA / n).stat().st_size for n in present) if present else 0
    print("# 死文件清理（%s）\n" % ("**真删** ✓" if args.apply else "dry-run ✗"))
    print("| 文件 | 大小 |")
    print("|---|---|")
    for n in present:
        print("| `%s` | %.1f KB |" % (n, (DATA / n).stat().st_size / 1024.0))
    print("\n**共 %d 个，%.1f MB**（另有 %d 个已不存在 ✓）"
          % (len(present), total / 1024.0 / 1024.0, len(missing)))

    if not args.apply:
        print("\n⇒ 只 dry-run ✓ 加 `--apply` 才真删 ✗")
        print("   误删恢复：`--restore`（备份在 `dist/pruned/` ✓）")
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
    print("   若误删：`--restore` 即可 ✓")
    return 0 if ok == len(present) else 1


if __name__ == "__main__":
    sys.exit(main())
