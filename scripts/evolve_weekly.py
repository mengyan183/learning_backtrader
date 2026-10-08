#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-4 阶段 6 复盘/周报自动化：每周自动汇总进化闭环状态。

汇总内容（全部来自仓库文件，数字可指回）：
  1. 本周假说状态变更（hypotheses.md：按日期列过滤本周 verified/adopted/falsified）；
  2. 本周提案（evolution/proposals/ 按文件名日期）；
  3. 本周审批决策（docs/decision-log.md 本周条目）；
  4. 本周因子状态变更（factors.md 按日期列过滤）；
  5. 数据缺口（docs/blocked-registry.md 中「可实施/待 X」项）；
  6. 风险快照（Data/features.csv 尾行 zone/熔断 + positions 浮盈面）。

输出：evolution/weekly/YYYY-Www.md（ISO 周）。--push 时调用 scripts/feishu_send.py 推送（GUI 链路，默认不推）。

用法：.venv/bin/python scripts/evolve_weekly.py [--push]
"""
import argparse
import datetime as dt
import glob
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVO = os.path.join(REPO, "evolution")
WEEKLY_DIR = os.path.join(EVO, "weekly")


def parse_md_rows(path, prefix):
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding="utf-8"):
        if line.startswith("| %s" % prefix):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 6:
                rows.append(cells)
    return rows


def iso_week():
    today = dt.date.today()
    iso = today.isocalendar()
    return "%04d-W%02d" % (iso[0], iso[1])


def main():
    ap = argparse.ArgumentParser(description="C-4 阶段 6 周报自动化")
    ap.add_argument("--push", action="store_true", help="推送周报到飞书（GUI 链路）")
    ap.add_argument("--days", type=int, default=7, help="回顾窗口天数")
    args = ap.parse_args()

    today = dt.date.today()
    since = today - dt.timedelta(days=args.days)
    week = iso_week()
    date_s = today.isoformat()

    lines = ["# 进化周报（C-4，%s · %s）" % (date_s, week), "",
             "> 由 scripts/evolve_weekly.py 生成 · 全部数字可指回仓库文件",
             "", "## 1. 本周假说状态变更", ""]
    hyp = parse_md_rows(os.path.join(EVO, "hypotheses.md"), "H-")
    hits = 0
    for cells in hyp:
        if len(cells) >= 6 and cells[1] >= since.isoformat():
            lines.append("- %s（%s）：%s → 状态 %s" % (cells[0], cells[1], cells[2][:40], cells[5]))
            hits += 1
    if not hits:
        lines.append("- 无本周变更")
    lines += ["", "## 2. 本周提案", ""]
    hits = 0
    for path in sorted(glob.glob(os.path.join(EVO, "proposals", "proposal_*.md"))):
        m = re.search(r"_(\d{4}-\d{2}-\d{2})\.md$", path)
        if m and m.group(1) >= since.isoformat():
            name = os.path.basename(path).replace("proposal_", "").replace(".md", "")
            approved = "审批记录：" in open(path, encoding="utf-8").read()
            lines.append("- %s（%s）%s" % (name, m.group(1), "✅ 已审批" if approved else "⏳ 待审批"))
            hits += 1
    if not hits:
        lines.append("- 无本周提案")
    lines += ["", "## 3. 本周审批决策（decision-log.md）", ""]
    dlog = os.path.join(REPO, "docs", "decision-log.md")
    hits = 0
    if os.path.exists(dlog):
        for block in open(dlog, encoding="utf-8").read().split("## "):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", block)
            if m and m.group(1) >= since.isoformat():
                lines.append("- %s" % block.strip().splitlines()[0])
                hits += 1
    if not hits:
        lines.append("- 无本周审批")
    lines += ["", "## 4. 本周因子状态变更", ""]
    fac = parse_md_rows(os.path.join(EVO, "factors.md"), "F-")
    hits = 0
    for cells in fac:
        if len(cells) >= 7 and cells[1] >= since.isoformat():
            lines.append("- %s（%s）：%s 状态=%s" % (cells[0], cells[1], cells[2][:40], cells[6]))
            hits += 1
    if not hits:
        lines.append("- 无本周变更")
    lines += ["", "## 5. 数据缺口 / 待办", ""]
    reg = os.path.join(REPO, "docs", "blocked-registry.md")
    hits = 0
    if os.path.exists(reg):
        for line in open(reg, encoding="utf-8"):
            if line.startswith("| C-") and ("可实施" in line or "待" in line):
                m = re.match(r"\| (C-\d+) \| ([^|]+) \|", line)
                if m:
                    lines.append("- %s %s（%s）" % (m.group(1), m.group(2).strip(), "见 blocked-registry"))
                    hits += 1
    if not hits:
        lines.append("- 无缺口项")
    lines += ["", "## 6. 风险快照", ""]
    feat_path = os.path.join(REPO, "Data", "features.csv")
    if os.path.exists(feat_path):
        tail = open(feat_path, encoding="utf-8").read().strip().splitlines()[-1].split(",")
        fdate = tail[0]
        zone = tail[2] if len(tail) > 2 else "?"
        cb = tail[7] if len(tail) > 7 else "?"
        lines.append("- 指数尾行：%s，zone=%s，熔断=%s（features.csv 尾行）" % (fdate, zone, cb))
    lines += ["", "## 7. 附：本周产物", ""]
    lines.append("- evolution/decay-report.md / walkforward-report.md / attribution-report.md（如存在）")

    os.makedirs(WEEKLY_DIR, exist_ok=True)
    out_path = os.path.join(WEEKLY_DIR, "weekly-%s.md" % week)
    open(out_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\n✅ 周报 → %s" % out_path)
    if args.push:
        subprocess.run([sys.executable, os.path.join(REPO, "scripts", "feishu_send.py"),
                        out_path], check=False)


if __name__ == "__main__":
    main()
