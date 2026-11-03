#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**数据文件审计** ✓（2026-11-03 用户要求）。

【回答三个问题】
  ① 每个 `Data/raw/*.csv` 是**谁写的**（生产者）✓
  ② 是**谁读的**（消费者）✓
  ③ 据此判断：**在用** / **孤儿**（无人读 ✗）/ **无生产者**（只读不写 ✗）

【为什么用静态扫描而不是跑一遍】
  Windows 侧 `Data/raw/` 是旧快照 ✗ 跑不出真实结论 ✗
  但「谁读谁写」是**代码结构**问题 ✓ 与数据新旧无关 ✓
  ⇒ 静态扫描在两边都成立 ✓

【判据】
  - 有消费者 + 有生产者 ⇒ **在用** ✓
  - 有消费者 + 无生产者 ⇒ **只读**（数据从别处来 ✗ 或抓取代码缺失 ✗）
  - 无消费者 ⇒ **孤儿**（可删 ✗）

用法：
  .venv/bin/python scripts/audit_data_files.py
  .venv/bin/python scripts/audit_data_files.py --json out.json
"""
import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data" / "raw"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

#: 🔴 **监控引用白名单** ✓ —— 出现在这里的一律判「**监控依赖**」✗
#: 不参与「孤儿/死文件」判定 ✓
#: 事故（2026-11-03）：审计把 `fred_T10Y2Y.csv` / `sp500_cape.csv` 判成死文件 ✗
#:   而它们是 `check_freshness.py` 的 `REF_PRODUCTS`（硬编码完整路径 ✗）
#:   静态扫描抓不到 ⇒ 用户收到「文件缺失」告警 ✗
#: ⚠️ 加监控时必须同步更新这里 ✗
MONITORED = {
    "shoutu_history.csv", "fred_DGS10.csv", "sp500_pe.csv", "sp500_cape.csv",
    "fedwatch.csv", "fred_T10Y2Y.csv", "sentiment.csv", "putcall.csv",
    "kalshi_fed.csv", "funding_rate.csv", "shoutu_fng.csv",
    "news_sentiment.csv", "stablecoin_usage.csv", "fred_DFF.csv",
    # 以下由因子代码动态拼名读取（静态扫描也抓不到 ✗）
    "fred_BAA10Y.csv", "fred_baa10y_avail.csv",
}

#: 扫哪些代码目录
SCAN_DIRS = ("scripts", "fg_system", "tests")
#: 写入的标志（**上下文窗口内**出现这些 ⇒ 视为生产者 ✓）
#: ⚠️ 2026-11-03 补：`csv.writer` / `DictWriter` / `.write(` / `w.writerow`
#:    —— 实测 `fetch_stablecoin_usage.py` 是
#:    `dest = DATA_DIR / "stablecoin_usage.csv"` ✗ 然后 `w = csv.writer(f)` ✗
#:    ⇒ 只匹配「同一行」会漏掉生产者 ✗
WRITE_HINTS = ("to_csv", "write_text", "open(", "dump", "savefig",
               "csv.writer", "DictWriter", ".write(", "writerow",
               "writerows")
#: 只读不写的标志
READ_HINTS = ("read_csv", "load_prices", "close_series", "csv.reader")
#: 上下文窗口（前后各几行）✓
CTX = 2


def _py_files():
    out = []
    for d in SCAN_DIRS:
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            out.append(p)
    return out


def _scan(files):
    """返回 `{filename: {"writers": [..], "readers": [..]}}` ✓。"""
    names = [os.path.basename(p) for p in glob.glob(str(DATA / "*.csv"))]
    # 也覆盖 `Data/raw/putcall/` 子目录 ✗
    for sub in ("putcall",):
        d = DATA / sub
        if d.is_dir():
            names += [os.path.basename(p) for p in glob.glob(str(d / "*.csv"))]
    names = sorted(set(names))

    out = {n: {"writers": [], "readers": []} for n in names}
    for p in files:
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:                   # noqa: BLE001
            continue
        rel = str(p.relative_to(REPO)).replace("\\", "/")
        lines = txt.splitlines()
        for ln_no, line in enumerate(lines, 1):
            for n in names:
                # 🔴 2026-11-03 修：`fetch.py` 用**动态拼名** ✗
                #    （`os.path.join(DATA_RAW, name + ".csv")` ✗）
                #    ⇒ 只匹配 `xxx.csv` 会漏掉生产者 ✗
                #    实测：`stablecoin_usage.csv` / `putcall.csv` /
                #    `vix3m.csv` / `news_sentiment.csv` 全被判「无生产者」✗
                #    ⇒ 同时匹配**去掉 .csv 的词干** ✓
                stem = n[:-4] if n.endswith(".csv") else n
                if n not in line and stem not in line:
                    continue
                # 🔴 上下文窗口 ✓ —— 文件名行与写入动作常不在同一行 ✗
                lo = max(0, ln_no - 1 - CTX)
                hi = min(len(lines), ln_no + CTX)
                ctx = "\n".join(lines[lo:hi])
                is_write = any(h in ctx for h in WRITE_HINTS)
                is_read = any(h in line for h in READ_HINTS)
                rec = "%s:%d" % (rel, ln_no)
                if is_write and not is_read:
                    out[n]["writers"].append(rec)
                elif is_read:
                    out[n]["readers"].append(rec)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args(argv)

    files = _py_files()
    audit = _scan(files)

    # 现有文件
    existing = sorted(
        [os.path.basename(p) for p in glob.glob(str(DATA / "*.csv"))]
        + [os.path.basename(p) for p in glob.glob(str(DATA / "putcall" / "*.csv"))])

    print("# 数据文件审计（扫 %d 个 .py）\n" % len(files))
    print("| 文件 | 生产者 | 消费者 | 判定 |")
    print("|---|---|---|---|")
    rows = []
    for n in sorted(audit):
        w = len(audit[n]["writers"])
        r = len(audit[n]["readers"])
        if n in MONITORED:
            # 🔴 白名单优先 ✗ —— 监控/动态拼名的消费者静态扫描抓不到 ✓
            verdict = "**监控依赖**（勿删 ✓）"
        elif w > 0 and r > 0:
            verdict = "**在用** ✓"
        elif r > 0:
            verdict = "**只读**（无生产者 ✗）"
        elif w > 0:
            verdict = "**孤儿**（无人读 ✗）"
        else:
            verdict = "**死文件**（无人读也无人写 ✗）"
        rows.append((n, w, r, verdict))
        print("| `%s` | %d | %d | %s |" % (n, w, r, verdict))

    # 汇总（🔴 白名单优先 ✗ 不计入「孤儿/死文件」）
    mon = [n for n in audit if n in MONITORED]
    n_mon = len(mon)
    rest = [n for n in audit if n not in MONITORED]
    n_used = sum(1 for n in rest
                 if audit[n]["writers"] and audit[n]["readers"])
    n_ro = sum(1 for n in rest
               if not audit[n]["writers"] and audit[n]["readers"])
    n_orphan = sum(1 for n in rest
                   if audit[n]["writers"] and not audit[n]["readers"])
    n_dead = sum(1 for n in rest
                 if not audit[n]["writers"] and not audit[n]["readers"])
    print("\n## 汇总\n")
    print("| 判定 | 数量 |")
    print("|---|---|")
    print("| **监控依赖**（勿删 ✓）| %d |" % n_mon)
    print("| 在用 ✓ | %d |" % n_used)
    print("| 只读（无生产者）✗ | %d |" % n_ro)
    print("| 孤儿（无人读）✗ | %d |" % n_orphan)
    print("| 死文件 ✗ | %d |" % n_dead)
    print("\n⚠️ 「只读」「孤儿」「死文件」**都可能有误判** ✗：")
    print("   ① 监控脚本用**硬编码完整路径**（`REF_PRODUCTS` ✗）⇒ 抓不到")
    print("   ② 因子代码用**动态拼名**（`\"%s.csv\" % name` ✗）⇒ 抓不到")
    print("   ⇒ **删之前必须人工核对** ✓ 白名单见 `MONITORED`")

    if args.json:
        p = Path(args.json)
        if not p.is_absolute():
            p = REPO / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"existing": existing, "audit": audit},
                                ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n[已写 %s]" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
