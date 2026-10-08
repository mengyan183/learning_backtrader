#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fg-sync 单命令入口（OpenClaw 模型只需执行这一条命令，无需多步）。

用法（任选其一）：
    .venv/bin/python scripts/fg_sync_tool.py <分片消息原文>       # 直接传文本
    .venv/bin/python scripts/fg_sync_tool.py -f <消息文件路径>    # 传文件
    cat msg.md | .venv/bin/python scripts/fg_sync_tool.py         # stdin

内部自动完成：
    保存原文 → fg_sync_ingest.py 全流程（聚合→安全解压→白名单→冲突检查
    →入库推送→pytest）→ 输出结果（供 agent 原样回发飞书）。

退出码：0=成功；2=可解释失败（缺片/白名单/冲突/测试失败）；3=内部错误。
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNC_IN_DIR = os.path.expanduser("~/.openclaw/tmp/fg-sync-in")


def _read_input(args):
    """返回分片原文：优先 -f 文件，其次 argv 文本，最后 stdin。"""
    if args.file:
        with open(args.file, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    if args.text:
        return args.text
    return sys.stdin.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="", help="分片消息原文（可省略，用 -f 或 stdin）")
    ap.add_argument("-f", "--file", help="分片消息文件路径（推荐：模型把原文存文件后传路径）")
    ap.add_argument("--commit", default="fg-sync: 公司端同步")
    ap.add_argument("--quick", action="store_true",
                    help="增量测试：只跑相关测试文件（<10s），不跑全量 pytest")
    args = ap.parse_args()

    raw = _read_input(args)
    raw = raw.strip()
    if not raw:
        print("❌ 没有收到分片内容。请把飞书机器人收到的 ###FG: 分片消息原文传给我。")
        return 2
    if "###FG:" not in raw:
        print("❌ 消息里没有 ###FG: 分片标记。请确认发来的是完整分片原文，"
              "格式：###FG:包名:序号/总数###…###FG:end###")
        return 2

    # 1) 保存原文到同步输入目录
    os.makedirs(SYNC_IN_DIR, exist_ok=True)
    dst = os.path.join(SYNC_IN_DIR, "sync_in.md")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(raw)
    print("已保存分片原文到 %s（%d 字符）" % (dst, len(raw)))

    # 2) 调用编排脚本完成全流程
    ingest = os.path.join(REPO, "scripts", "fg_sync_ingest.py")
    py = os.path.join(REPO, ".venv", "bin", "python")
    cmd = [py, ingest, SYNC_IN_DIR, "--repo", REPO, "--commit", args.commit]
    if args.quick:
        cmd.append("--quick")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=2400)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
