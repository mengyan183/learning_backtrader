#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fg-sync 安全入库编排（OpenClaw 收到飞书 base64 分片后调用）。

【全流程】
  1. 聚合   —— 复用 scripts/restore_from_base64.py 的 extract_marked/_decode：
               识别 `###FG:包名:序号/总数###…###FG:end###` 分片，缺片/非法字符报错。
  2. 暂存解压 —— base64 → tar.xz → **先解压到临时目录**（安全解压：拒绝绝对路径、
                `..` 穿越、符号链接逃逸），不直接碰仓库。
  3. 白名单过滤 —— 只放行代码/测试/文档目录；拒绝 Data/**（密钥+运行态）、
                .git/**、.venv/**、__pycache__/**、*.pyc、*.key、*.secret。
  4. 冲突检查 —— 与 `git status --porcelain` 未提交修改取交集；有冲突则**中止**，
                列出冲突文件等确认，绝不自动覆盖。
  5. 入库     —— 无冲突才复制进仓库 → git add -A → commit → push。
  6. 测试回传 —— `.venv/bin/python -m pytest -q`，汇总结果到 stdout（供 agent 回发飞书）。

用法（OpenClaw/agent 侧）：
    .venv/bin/python scripts/fg_sync_ingest.py <分片目录> \
        [--repo /Users/xingguo/learning_backtrader] [--commit "同步: <描述>"] [--quick]
退出码：0=全流程成功；2=白名单/冲突/缺片等可解释失败；3=内部错误。
--quick：增量测试模式，只跑与本次入库文件相关的测试文件（tests/test_<模块>.py、
        tests/company_sync_test.py 等），预计 <10s；全量 pytest 留给每日链。

【触发词（写进 fg-qa/ag 侧规则）】同步、还原、补传、backfill、base64、分片。
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 允许同步进仓库的顶层目录 / 根级文件（其余一律拒绝）
ALLOWED_DIRS = {"fg_system", "scripts", "tests", "evolution", "docs"}
ALLOWED_ROOT_FILES = {"README.md", "AGENTS.md", "pyproject.toml",
                      "requirements.txt", "requirements-dev.txt", "Makefile",
                      ".gitignore", ".gitattributes"}
# 任何情况下都拒绝的目录片段（按路径分段精确匹配，避免误伤 .gitignore/.gitattributes 等普通文件）
DENY_DIR_SEGMENTS = {".git", ".venv", "__pycache__", "Data", "node_modules"}
# 任何情况下都拒绝的文件后缀/片段
DENY_FILE_FRAGMENTS = (".pyc", ".key", ".secret", ".token", ".env")


def _denied(rel):
    """判定是否命中强制拒绝规则。目录级与文件级分开精确匹配。"""
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or rel.startswith("../") or ".." in rel.split("/"):
        return True
    segs = rel.split("/")
    if any(seg in DENY_DIR_SEGMENTS for seg in segs):
        return True
    base = segs[-1]
    return any(f in base for f in DENY_FILE_FRAGMENTS)


def _allowed(rel, full_repo=False):
    rel = rel.replace("\\", "/")
    if _denied(rel):
        return False
    if full_repo:
        # 一次性完整同步授权：跳过目录白名单，但仍受 _denied 保护
        return True
    head = rel.split("/", 1)[0]
    if head in ALLOWED_DIRS:
        return True
    if "/" not in rel and rel in ALLOWED_ROOT_FILES:
        return True
    return False


def _safe_extract(tf, dest):
    """安全解压：拒绝绝对路径、`..` 穿越、链接逃逸；返回解出的相对路径列表。"""
    out = []
    for m in tf.getmembers():
        name = m.name.replace("\\", "/")
        if name.startswith("/") or name.split("/", 1)[0] in ("..", ".") or ".." in name.split("/"):
            raise SystemExit(f"❌ tar 内含穿越路径，已拒绝：{m.name}")
        if m.issym() or m.islnk():
            raise SystemExit(f"❌ tar 内含链接（不安全），已拒绝：{m.name}")
        target = os.path.realpath(os.path.join(dest, name))
        if not target.startswith(os.path.realpath(dest) + os.sep):
            raise SystemExit(f"❌ tar 内路径逃逸，已拒绝：{m.name}")
        tf.extract(m, dest)
        out.append(name)
    return out


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True, timeout=60)


def _dirty_paths(repo):
    r = _git(repo, "status", "--porcelain")
    if r.returncode != 0:
        return [], r.stderr.strip()
    paths = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        p = line[3:].strip()
        paths.append(p.replace("\\", "/"))
    return paths, None


def _clean_processed(src, keep=None):
    """成功后清理已处理的分片原文与标记文件（自动清理，2026-10-09）。

    只删除 src 目录根下的 `.md` / `.txt`（分片原文 + 聚合 sync_in.md）与
    `.done` 标记；目录本身、非文本文件、`keep` 白名单（如保留的归档目录名）
    一律不动。删除失败不致命（下次处理可再清），记录一行即可。
    """
    keep = set(keep or ())
    if not os.path.isdir(src):
        return
    for fn in sorted(os.listdir(src)):
        if fn in keep:
            continue
        p = os.path.join(src, fn)
        if not os.path.isfile(p):
            continue
        if fn.endswith((".md", ".txt", ".done")):
            try:
                os.unlink(p)
            except OSError as exc:
                print("⚠️ 自动清理跳过 %s：%s" % (fn, exc))
    print("🧹 已自动清理处理后的分片原文（保留目录：%s）" % (", ".join(sorted(keep)) or "无"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="放着 base64 分片文本（.txt/.md）的目录")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--commit", default="fg-sync: 公司端同步")
    ap.add_argument("--quick", action="store_true",
                    help="增量测试：只跑与本次入库文件相关的测试文件（<10s）")
    ap.add_argument("--full-repo", action="store_true",
                    help="一次性完整同步授权：跳过目录白名单（仍拒绝 Data/、密钥、.git 等危险路径）")
    args = ap.parse_args()

    sys.path.insert(0, os.path.join(args.repo, "scripts"))
    from restore_from_base64 import extract_marked, _decode  # 复用既有解析

    raw = ""
    for fn in sorted(os.listdir(args.src)):
        if fn.endswith((".txt", ".md")):
            with open(os.path.join(args.src, fn), encoding="utf-8",
                      errors="ignore") as fh:
                raw += fh.read()

    groups, problems = extract_marked(raw)
    if not groups:
        print("❌ 分片目录里没认出 ###FG: 标记的包（共读入 %d 字符）。"
              "请确认消息以 同步/还原/补传/backfill 开头，且分片标记完整。" % len(raw))
        return 2
    if problems:
        print("⚠️ 分片不完整，中止入库：")
        for p in problems:
            print("   " + p)
        print("请等剩余分片补发后再跑。")
        return 2

    print("认出的包：%s" % ", ".join("%s(%d片)" % (k, len(v)) for k, v in groups.items()))
    with tempfile.TemporaryDirectory(prefix="fg-sync-") as tmp:
        for name, parts in groups.items():
            blob = _decode(parts)
            if blob[:6] != b"\xfd7zXZ\x00":
                print(f"❌ 包 {name} 解出来不是 xz 数据，中止。")
                return 2
            tarpath = os.path.join(tmp, name + ".tar.xz")
            with open(tarpath, "wb") as fh:
                fh.write(blob)
            with tarfile.open(tarpath, "r:xz") as tf:
                members = _safe_extract(tf, tmp)

        allowed, denied = [], []
        for m in members:
            (allowed if _allowed(m, full_repo=args.full_repo) else denied).append(m)
        if denied:
            print("⛔ 以下文件不在白名单内，已拒绝（不入库）：")
            for d in denied[:20]:
                print("   - " + d)
            if len(denied) > 20:
                print("   … 共 %d 个被拒" % len(denied))
        if not allowed:
            print("❌ 没有任何文件通过白名单，中止。")
            return 2

        # 冲突检查：与仓库未提交修改取交集
        dirty, err = _dirty_paths(args.repo)
        if err:
            print("⚠️ 无法读取 git 状态（%s），中止（不冒险覆盖）。" % err)
            return 2
        conflict = sorted(set(allowed) & set(dirty))
        if conflict:
            print("⛔ 与 Mac 本地未提交修改冲突，中止（不自动覆盖），冲突文件：")
            for c in conflict:
                print("   - " + c)
            print("处理方式：先在 Mac 提交/丢弃本地改动，再重新触发同步。")
            return 2

        # 入库：复制白名单内文件 → git add/commit/push
        copied = []
        for rel in sorted(allowed):
            src_p = os.path.join(tmp, rel)
            if not os.path.isfile(src_p):
                continue
            dst_p = os.path.join(args.repo, rel)
            os.makedirs(os.path.dirname(dst_p), exist_ok=True)
            shutil.copy2(src_p, dst_p)
            copied.append(rel)
        print("入库 %d 个文件：%s" % (len(copied), ", ".join(copied[:8]) +
              (" …" if len(copied) > 8 else "")))

        # 只 add 本次入库文件，避免 git add -A 把运行态/未提交改动连带提交
        r = _git(args.repo, "add", "--", *copied)
        if r.returncode != 0:
            print("❌ git add 失败：" + r.stderr.strip()); return 2
        r = _git(args.repo, "commit", "-m", args.commit)
        if r.returncode != 0:
            print("⚠️ commit 失败（可能无变更可提交）：" + r.stderr.strip())
        else:
            r = _git(args.repo, "push", "-q", "origin", "main")
            if r.returncode != 0:
                print("⚠️ push 失败：" + r.stderr.strip())
            else:
                print("已推送 origin/main")

    # 测试
    py = os.path.join(args.repo, ".venv", "bin", "python")
    if not os.path.exists(py):
        print("⚠️ 未找到 .venv/bin/python，跳过 pytest（同步本身已成功）。")
        return 0

    # 增量模式：由已入库文件推导相关测试文件（tests/test_<模块>.py）
    if args.quick:
        related = set()
        for rel in copied:
            base = os.path.basename(rel)
            if base.startswith("test_"):
                related.add(os.path.join(args.repo, "tests", base))
                continue
            stem = os.path.splitext(base)[0]
            cand = os.path.join(args.repo, "tests", "test_" + stem + ".py")
            if os.path.exists(cand):
                related.add(cand)
        # 白名单兜底：同步链路自身测试恒跑
        for always in ("test_fg_sync_ingest.py", "test_restore_from_base64.py"):
            p = os.path.join(args.repo, "tests", always)
            if os.path.exists(p):
                related.add(p)
        if related:
            print("=== 增量测试（--quick，%d 个相关文件）===" % len(related))
            targets = sorted(related)
        else:
            print("=== 无直接相关测试文件，退回冒烟测试 ===")
            targets = [os.path.join(args.repo, "tests", "company_sync_test.py")]
        tr = subprocess.run([py, "-m", "pytest", "-q", *targets], cwd=args.repo,
                            capture_output=True, text=True, timeout=600)
        tail = (tr.stdout or "").strip().splitlines()
        last = tail[-1] if tail else ""
        print(last)
        if tr.returncode != 0:
            print("❌ 增量 pytest 有失败，详见仓库根 pytest 输出；同步文件已入库，请修复后再提交。")
            return 2
        print("✅ 增量 pytest 通过（同步相关测试）。")
        _clean_processed(args.src)
        return 0

    tr = subprocess.run([py, "-m", "pytest", "-q"], cwd=args.repo,
                        capture_output=True, text=True, timeout=1800)
    tail = (tr.stdout or "").strip().splitlines()
    last = tail[-1] if tail else ""
    print(last)
    if tr.returncode != 0:
        print("❌ pytest 有失败，详见仓库根 pytest 输出；同步文件已入库，请修复后再提交。")
        return 2
    print("✅ pytest 通过。同步完成，可回复公司端：文件已入库并测试通过。")
    _clean_processed(args.src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
