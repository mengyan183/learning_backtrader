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
  .venv/bin/python scripts/evolve_approve.py --push            # C-3 增强：未审批提案推飞书
  .venv/bin/python scripts/evolve_approve.py --push --dry-run  # 只写分片不发送（本地可验 ✓）
  .venv/bin/python scripts/evolve_approve.py --approve evolution/proposals/proposal_TQQQ_V-H7_2026-10-08.md Z --note "OOS负结果,纳入长期观察"

⚠️ C-3 增强（WT-02，2026-10-10）的推送**不照抄** `evolve_weekly.py` 的写法：
   那边是 `feishu_send.py <file>` —— 而 `feishu_send.py` **没有位置参数** ✗
   （它固定从 `dist/feishu/text/*-t*.txt` 读分片）⇒ argparse 直接报错 ✗，
   且 `check=False` 把错误吞掉 ⇒ **实际什么都没推** ✗。
   本文件改用已验证路径：写分片到 `dist/feishu/text/` → 调 `feishu_send.py --pkg <包名>` ✓。
"""
import argparse
import datetime as dt
import glob
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROPOSALS = os.path.join(REPO, "evolution", "proposals")
DECISION_LOG = os.path.join(REPO, "docs", "decision-log.md")
APPROVAL_MARK = "审批记录："
TEXT_DIR = os.path.join(REPO, "dist", "feishu", "text")

# ⚠️ Windows 控制台默认 GBK ✗ ⇒ 本文件大量 `print("✅ …")` 会直接
# `UnicodeEncodeError` 崩溃 ✓（2026-10-10 实测：`--push --dry-run` 即挂 ✓）。
# 与 `scripts/feishu_send.py` 的 utf-8 修复同根 ✓。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


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


def push_pending(chat="海外投资助手", dry_run=False):
    """C-3 增强：把**未审批提案**推飞书 ✓（WT-02）。

    路径（本会话已验证 3 次 ✓）：写一条纯文本分片到 `dist/feishu/text/` ⇒
    调 `feishu_send.py --pkg <包名>`。包名按约定 `approve_<MMDD>` ✓
    （只含 [A-Za-z0-9_] ✓，且换名可避免与历史导出撞车 ✗）。
    """
    pend = scan_pending()
    if not pend:
        print("无未审批提案，无需推送")
        return 0
    lines = ["📋 C-3 待审批提案（%s）" % dt.datetime.now().strftime("%Y-%m-%d %H:%M")]
    for i, p in enumerate(pend, 1):
        lines.append("%d. %s / %s  判定=%s  → %s"
                     % (i, p["sym"], p["vk"], p["verdict"],
                        os.path.basename(p["path"])))
    lines.append("")
    lines.append("审批：scripts/evolve_approve.py --approve <file> --status Y|N|Z --log")
    body = "\n".join(lines)

    pkg = "approve_" + dt.datetime.now().strftime("%m%d")
    os.makedirs(TEXT_DIR, exist_ok=True)
    for f in os.listdir(TEXT_DIR):            # 清掉本包旧分片，重跑不叠加 ✓
        if f.startswith(pkg + "-t"):
            os.remove(os.path.join(TEXT_DIR, f))
    chunk = os.path.join(TEXT_DIR, "%s-t001.txt" % pkg)
    open(chunk, "w", encoding="utf-8", newline="\n").write(body)
    print("✅ 已写分片：%s（%d 字符）" % (chunk, len(body)))

    if dry_run:
        print("（--dry-run：未发送 ✓；可自行验证：feishu_send.py --pkg %s --dry-run）" % pkg)
        return 0
    rc = subprocess.run([sys.executable,
                         os.path.join(REPO, "scripts", "feishu_send.py"),
                         "--pkg", pkg, "--chat", chat]).returncode
    if rc != 0:
        print("✗ 推送失败（rc=%d）—— 分片保留在 %s，可重试" % (rc, chunk))
        return rc
    print("✅ 已推送 %d 份待审批提案（包名 %s）" % (len(pend), pkg))
    return 0


def main():
    ap = argparse.ArgumentParser(description="C-3 人工审批闭环")
    ap.add_argument("action", nargs="?", default="list", help="list 或默认")
    ap.add_argument("--approve", metavar="FILE")
    ap.add_argument("--status", choices=["Y", "N", "Z"], help="Y/N/Z")
    ap.add_argument("--note", default="")
    ap.add_argument("--log", action="store_true", help="审批后写决策日志")
    ap.add_argument("--push", action="store_true",
                    help="把未审批提案推飞书（C-3 增强 ✓）")
    ap.add_argument("--dry-run", action="store_true", help="--push 时只写分片不发送")
    ap.add_argument("--chat", default="海外投资助手", help="飞书会话名（默认海外投资助手）")
    args = ap.parse_args()

    if args.push:
        sys.exit(push_pending(args.chat, args.dry_run))

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
