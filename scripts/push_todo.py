#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""push_todo.py：生成「贪恐系统待办快照」摘要，供 fg-sync 收到「同步待办」后回传飞书。

为什么需要：Windows 端（公司电脑，无公网）看不到 Mac 仓库里的最新待办；
本脚本把 docs/ 下的待办状态提炼成一段人类可读摘要，Mac 端 OpenClaw 收到
「同步待办/任务清单/有什么任务」时运行本脚本，把输出回传飞书即可。

用法:
  .venv/bin/python scripts/push_todo.py                  # 只打印摘要（agent 回传用）
  .venv/bin/python scripts/push_todo.py --send <chat_id> # 摘要直接发到飞书会话

摘要数据源（只读，不修改）：
  docs/blocked-registry.md   —— 等待型（🟡）清单
  docs/dual-end-workflow.md  —— Windows 端可做任务（B 表）
  docs/NEXT-SESSION.md       —— 最近落地 ✅ 行
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime

REPO = "/Users/xingguo/learning_backtrader"
HOME = os.path.expanduser("~")
CFG_PATH = os.path.join(HOME, ".openclaw", "openclaw.json")


def git_head():
    try:
        r = subprocess.run(
            ["git", "-C", REPO, "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else "(git 不可用)"
    except Exception:
        return "(git 不可用)"


def parse_waiting():
    """blocked-registry.md 中状态列为 🟡 的行（数据积累/等待型，勿开工）。"""
    waiting = []
    path = os.path.join(REPO, "docs", "blocked-registry.md")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\|\s*(B-\d+)\s*\|\s*([^|]+?)\s*\|", line)
                # 只认行尾状态列 = 🟡（避免行内含"🟡 研究参考"但已完成的 B-7 误入）
                if m and re.search(r"\|\s*🟡\s*\|\s*$", line):
                    waiting.append((m.group(1), m.group(2).strip()))
    except OSError as e:
        waiting.append(("ERR", f"blocked-registry 读取失败：{e}"))
    return waiting


def parse_win_tasks():
    """docs/windows-tasks.md「待做任务」表中状态非 ✅ 的任务（编号+任务名+说明摘要）。"""
    tasks = []
    path = os.path.join(REPO, "docs", "windows-tasks.md")
    try:
        with open(path, encoding="utf-8") as f:
            in_todo = False
            for line in f:
                if line.startswith("## 待做任务"):
                    in_todo = True
                    continue
                if in_todo and line.startswith("## "):
                    break
                if in_todo:
                    # 行形如：| WT-01 | 任务名 | 说明 | 验收 | 状态 |
                    m = re.match(r"\|\s*(WT-\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|", line)
                    if m:
                        num, name, desc = m.group(1), m.group(2).strip(), m.group(3).strip()
                        # 只收状态非 ✅ 的行（避免"已完成"区或误标）
                        if not re.search(r"\|\s*✅\s*\|", line):
                            desc_short = desc if len(desc) <= 40 else desc[:37] + "…"
                            tasks.append(f"{num} {name} — {desc_short}")
    except OSError as e:
        tasks.append(f"ERR windows-tasks 读取失败：{e}")
    return tasks


def recent_changes(limit=3):
    """NEXT-SESSION.md 状态基线里最新的 ✅ 行。"""
    hits = []
    path = os.path.join(REPO, "docs", "NEXT-SESSION.md")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("- ✅") and "状态基线" not in s:
                    hits.append(s.lstrip("- ").strip())
    except OSError as e:
        hits.append(f"- 读取失败：{e}")
    return hits[:limit]


def build_summary():
    head = git_head()
    waiting = parse_waiting()
    win = parse_win_tasks()
    recent = recent_changes()

    parts = []
    parts.append("📋 贪恐系统待办快照")
    parts.append(f"生成时间：{datetime.now():%Y-%m-%d %H:%M} · 仓库 HEAD：{head[:7] if head else '未知'}")
    parts.append("")
    parts.append("【Windows 端可做（立即开工）】")
    if win:
        for task in win:
            parts.append(f"  · {task}")
    else:
        parts.append("  （暂无独立待办；默认动作：全量 pytest 回归 ~900 用例）")
    parts.append("")
    parts.append("【等待型（数据积累中，勿开工）】")
    if waiting:
        for num, item in waiting:
            parts.append(f"  · {num} {item}")
    else:
        parts.append("  （无）")
    parts.append("")
    parts.append("【最近落地】")
    for r in recent:
        parts.append(f"  · {r}")
    parts.append("")
    parts.append("开工流程：选任务 → 本地开发 → scripts/make_feishu_bundle.py 打包 → 飞书回传 fg-sync")
    parts.append("完整待办：docs/blocked-registry.md · docs/NEXT-SESSION.md · docs/dual-end-workflow.md")
    return "\n".join(parts)


def send_feishu(text, chat_id):
    """以飞书机器人身份向指定 chat 发普通文本消息（复用 OpenClaw feishu 配置）。"""
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        f_cfg = cfg["channels"]["feishu"]
    except Exception as e:
        return f"配置读取失败：{e}"
    base = "https://open.feishu.cn/open-apis"
    try:
        req = urllib.request.Request(
            f"{base}/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id": f_cfg["appId"], "app_secret": f_cfg["appSecret"]}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            tok = json.loads(r.read())
        if tok.get("code") != 0:
            return f"token err: {tok.get('msg')}"
        token = tok["tenant_access_token"]
    except Exception as e:
        return f"token 获取失败：{e}"
    body = json.dumps(
        {"receive_id": chat_id, "msg_type": "text",
         "content": json.dumps({"text": text})}
    ).encode()
    req2 = urllib.request.Request(
        f"{base}/im/v1/messages?receive_id_type=chat_id",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req2, timeout=15) as r:
            resp = json.loads(r.read())
            return "ok" if resp.get("code") == 0 else resp.get("msg", "send fail")
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.read().decode()[:200]}"


def main():
    ap = argparse.ArgumentParser(description="生成贪恐系统待办快照摘要")
    ap.add_argument("--send", metavar="CHAT_ID", default=None,
                    help="直发到指定飞书会话（缺省只打印摘要）")
    args = ap.parse_args()

    summary = build_summary()
    if args.send:
        result = send_feishu(summary, args.send)
        print(f"摘要 {len(summary)} 字符 → 发送结果：{result}")
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
