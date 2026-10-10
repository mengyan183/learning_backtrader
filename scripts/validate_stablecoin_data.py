#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-10 稳定币数据质量校验（H-034 数据质量前置，WT-10）。

校验 `Data/raw/stablecoin_usage.csv`（由 `scripts/fetch_stablecoin_usage.py` 产出）：
  1. 文件存在 + 列齐全（COLUMNS 顺序固定，与 fetch 脚本一致）
  2. `date` 可解析（ISO）
  3. 缺失率：任一列 >5% 告警
  4. 异常值：`circulation` / `monthly_volume` ≤0，或环比跳变 >10×
  5. 输出校验报告（行数 / 日期范围 / 缺失率 / 异常清单）

退出码：0=通过；1=有告警；2=无数据 / 不可校验（可解释失败，不抛栈）。
用法：py -3.10 scripts/validate_stablecoin_data.py
      py -3.10 scripts/validate_stablecoin_data.py --in Data/raw/stablecoin_usage.csv
"""
import argparse
import csv
import datetime as dt
import os
import sys

# §6.2 第 4 条：脚本自带 stdout utf-8，避免 Windows GBK 崩溃。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 走 config 路径常量（照抄 fetch_stablecoin_usage.py 风格）。
try:
    sys.path.insert(0, REPO)
    from fg_system import config            # noqa: E402
    RAW_DIR = config.RAW_DIR
except Exception:                            # pragma: no cover
    RAW_DIR = os.path.join(REPO, "Data", "raw")

# 列**固定**，与 fetch_stablecoin_usage.COLUMNS 一致（顺序不得变）。
COLUMNS = ["date", "symbol", "monthly_volume", "circulation", "usage_efficiency"]
NUM_COLS = ["monthly_volume", "circulation", "usage_efficiency"]
MISSING_WARN = 0.05     # 缺失率 >5% 告警
JUMP_FACTOR = 10.0      # 环比跳变 >10× 标记


def _err(msg):
    print("✗ validate_stablecoin_data: %s" % msg, file=sys.stderr)
    return 2


def _num(text):
    """空/不可解析 → None（记为缺失），否则 float。"""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def check(path):
    """返回 `(warns, report)`；文件/列等硬错误返回 `(None, 错误信息)`。"""
    if not os.path.exists(path):
        return None, ("数据未拉取：%s 不存在。先跑 scripts/fetch_stablecoin_usage.py"
                      % path)
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    cols = list(rows[0].keys()) if rows else []
    if cols != COLUMNS:
        return None, "列不符（期望 %s，实际 %s）" % (COLUMNS, cols)
    if not rows:
        return None, "文件无数据行：%s" % path

    warns, report = [], ["行数：%d" % len(rows)]

    # ① date 可解析 + 日期范围
    dates, bad_dates = [], []
    for i, row in enumerate(rows, 2):
        try:
            dates.append(dt.date.fromisoformat((row["date"] or "").strip()))
        except ValueError:
            bad_dates.append(i)
    if bad_dates:
        warns.append("date 不可解析：%d 行（首个第 %d 行）"
                     % (len(bad_dates), bad_dates[0]))
    if dates:
        report.append("日期范围：%s → %s" % (min(dates), max(dates)))

    # ② 缺失率
    for col in COLUMNS:
        miss = sum(1 for r in rows if not (r.get(col) or "").strip())
        rate = miss / len(rows)
        report.append("缺失率 %-16s %5.1f%%  (%d/%d)"
                      % (col, rate * 100, miss, len(rows)))
        if rate > MISSING_WARN:
            warns.append("缺失率超阈值：%s %.1f%% > %.0f%%"
                         % (col, rate * 100, MISSING_WARN * 100))

    # ③ 数值 ≤0 + 环比跳变
    for col in NUM_COLS:
        vals = [_num(r.get(col)) for r in rows]
        nonpos = [i for i, v in enumerate(vals, 2) if v is not None and v <= 0]
        if nonpos:
            warns.append("%s ≤0：%d 处（首个第 %d 行）" % (col, len(nonpos), nonpos[0]))
        valid = [(i, v) for i, v in enumerate(vals, 2) if v is not None]
        jumps = []
        for (_, prev), (idx, cur) in zip(valid, valid[1:]):
            if prev == 0:
                continue
            ratio = cur / prev
            if ratio > JUMP_FACTOR or ratio < 1.0 / JUMP_FACTOR:
                jumps.append((idx, ratio))
        if jumps:
            warns.append("%s 环比跳变 >%.0f×：%d 处（首个第 %d 行 %.2f×）"
                         % (col, JUMP_FACTOR, len(jumps), jumps[0][0], jumps[0][1]))
    return warns, report


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="校验 Data/raw/stablecoin_usage.csv 的数据质量（WT-10）")
    ap.add_argument("--in", dest="path",
                    default=os.path.join(RAW_DIR, "stablecoin_usage.csv"),
                    help="待校验 CSV（默认 Data/raw/stablecoin_usage.csv）")
    args = ap.parse_args(argv)

    warns, report = check(args.path)
    if warns is None:
        return _err(report)

    print("=== 稳定币数据质量校验 ===")
    print("文件：%s" % args.path)
    for line in report:
        print("  " + line)
    if warns:
        print("--- 告警 %d 条 ---" % len(warns))
        for w in warns:
            print("  ⚠ " + w)
        return 1
    print("结论：通过（无告警）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
