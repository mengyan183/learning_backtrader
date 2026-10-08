#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-3 人工审批闭环：提案扫描 → 审批清单 → 签字回写 → 决策日志。

流程（evolution-plan 第 8 条：先文档→再代码→再回测→人工审批）：
  1. `list`      扫描 evolution/proposals/*.md 中未审批的提案，输出审批清单；
  2. `--approve <file> <Y|N|Z> [--note "…"]`：
       Y=采纳（允许后续动 config.py）/ N=否决 / Z=观察（纳入长期观察）
       在提案文件「## 6. 审批」追加审批记录行；
  3. `--log`     把审批动作写入 docs/decision-log.md（人工门控记忆，同 decision_log.py 口径）。

红线：审批只写提案文件与决策日志；Y 只解除「允许动 config」的权限，实际改 config 仍须单独显式操作。
用法：
  .venv/bin/python scripts/evolve_approve.py list
  .venv/bin/python scripts/evolve_approve.py --approve evolution/proposals/proposal_TQQQ_V-H7_2026-10-08.md Z --note "OOS负结果,纳入长期观察"
"""
import argparse
import datetime as dt
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROPOSALS = os.path.join(REPO, "evolution", "proposals")
DECISION_LOG = os.path.join(REPO, "docs", "decision-log.md")
APPROVAL_MARK = "审批记录："


def scan_pending():
    pending = []
    for path in sorted(glob.glob(os.path.join(PROPOSALS, "proposal_*.md"))):
        text = open(path, encoding="utf-8").read()
        if APPROVAL_MARK in text:
            continue
        # 提取标的与变体（文件名 proposal_<SYM>_<VK>_<date>.md）
        m = re.search(r"proposal_([A-Z0-9]+)_([A-Za-z0-9_-]+)_\d{4}-\d{2}-\d{2}\.md$", path)
        sym = m.group(1) if m else "?"
        vk = m.group(2) if m else "?"
        # 提取判定行
        verdict = ""
        vm = re.search(r"^\*\*(不采纳|提案候选)[^*]+\*\*", text, re.M)
        if vm:
            verdict = vm.group(1)
        pending.append({"path": path, "sym": sym, "vk": vk, "verdict": verdict})
    return pending


def list_pending():
    pend = scan_pending()
    if not pend:
        print("无未审批提案（evolution/proposals/ 已全部审批）")
        return
    print("未审批提案 %d 份：" % len(pend))
    for i, p in enumerate(pend, 1):
        print("  %d. %s / %s  判定=%s  → %s" % (i, p["sym"], p["vk"], p["verdict"],
                                              os.path.basename(p["path"])))


def approve(path, status, note=""):
    full = path if os.path.isabs(path) else os.path.join(REPO, path)
    if not os.path.exists(full):
        print("✗ 提案不存在：%s" % path)
        sys.exit(1)
    if status not in ("Y", "N", "Z"):
        print("✗ 审批状态须为 Y（采纳）/ N（否决）/ Z（观察）")
        sys.exit(1)
    text = open(full, encoding="utf-8").read()
    if APPROVAL_MARK in text:
        print("⚠️ 该提案已有审批记录，勿重复审批：%s" % os.path.basename(full))
        sys.exit(1)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = "\n%s%s %s（%s）%s\n" % (APPROVAL_MARK, status, stamp,
                                  {"Y": "采纳", "N": "否决", "Z": "观察"}[status],
                                  ("：" + note) if note else "")
    # 追加到文件末尾（提案模板末尾即审批位）
    with open(full, "a", encoding="utf-8") as fh:
        fh.write(line)
    print("✅ 已回写审批：%s → %s" % (status, os.path.basename(full)))
    return full, status, note


def log_decision(full, status, note=""):
    sym_vk = os.path.basename(full).replace(".md", "")
    entry = ("\n## %s 审批（C-3）\n\n- 提案：%s\n- 审批：%s（%s）\n- 备注：%s\n"
             % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), sym_vk,
                status, {"Y": "采纳", "N": "否决", "Z": "观察"}[status],
                note or "—"))
    os.makedirs(os.path.dirname(DECISION_LOG), exist_ok=True)
    with open(DECISION_LOG, "a", encoding="utf-8") as fh:
        fh.write(entry)
    print("✅ 已写入决策日志 docs/decision-log.md")


def main():
    ap = argparse.ArgumentParser(description="C-3 人工审批闭环")
    ap.add_argument("action", nargs="?", default="list", help="list 或默认")
    ap.add_argument("--approve", metavar="FILE")
    ap.add_argument("--status", choices=["Y", "N", "Z"], help="Y/N/Z")
    ap.add_argument("--note", default="")
    ap.add_argument("--log", action="store_true", help="审批后写决策日志")
    args = ap.parse_args()

    if args.approve:
        if not args.status:
            print("✗ 需提供审批状态：--approve <file> --status Y|N|Z")
            sys.exit(1)
        full, st, note = approve(args.approve, args.status, args.note)
        if args.log:
            log_decision(full, st, note)
    else:
        list_pending()


if __name__ == "__main__":
    main()
