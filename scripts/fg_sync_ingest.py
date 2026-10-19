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
                列出冲突文件等确认，绝不自动覆盖（patch 目标文件同样受保护 ✓）。
  5. 入库     —— 无冲突才复制进仓库 → git add 本次文件 → commit → push；
                含 `__patch__/<包名>.diff` 统一 diff 包时，先转 git patch 用
                `git apply` 应用（MT-20），失败保留分片并告警。
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


def _git(repo, *args, input=None):
    return subprocess.run(["git", "-C", repo, *args], input=input,
                          capture_output=True, text=True, timeout=60)


# pack_many.py --patch 的 diff 包前缀（故意不命中白名单，需本文件显式 apply）
PATCH_PREFIX = "__patch__/"


def _split_patch_payload(payload):
    """解析 pack_many --patch 的 payload → [(rel, [diff块行])]。

    两种格式都支持（MT-38 起 Windows 改产标准 git 风格）：

    ① **标准 git patch**（`a/` `b/` 前缀，各文件独立成段）：
        diff --git a/scripts/x.py b/scripts/x.py
        index <old>..<new> <mode>
        --- a/scripts/x.py
        +++ b/scripts/x.py
        @@ -l,c +l,c @@
        ...
       按 `diff --git` 分段，rel 取 `b/` 侧（删除文件时回落 `a/` 侧）。

    ② **旧格式**（MT-20，difflib.unified_diff + 外层分隔头）：
        --- docs/xxx.md ---
        --- docs/xxx.md@origin/main
        +++ docs/xxx.md
        @@ ...
       分隔头 `--- <rel> ---` 开始新文件块。

    两种都只保留含 `@@` hunk 的块。
    """
    lines = payload.splitlines()

    if any(ln.startswith("diff --git ") for ln in lines):
        blocks, cur_rel, cur = [], None, []
        for ln in lines:
            m = re.match(r"^diff --git a/(.+) b/(.+)$", ln)
            if m:
                if cur_rel is not None:
                    blocks.append((cur_rel, cur))
                a_side, b_side = m.group(1).strip(), m.group(2).strip()
                cur_rel = a_side if b_side == "/dev/null" else b_side
                cur = [ln]
                continue
            if cur_rel is not None:
                cur.append(ln)
        if cur_rel is not None:
            blocks.append((cur_rel, cur))
        return [(rel, blk) for rel, blk in blocks
                if any(ln.startswith("@@") for ln in blk)]

    blocks = []
    cur_rel, cur = None, []
    for ln in lines:
        m = re.match(r"^--- (.+) ---$", ln)
        if m:
            if cur_rel is not None:
                blocks.append((cur_rel, cur))
            cur_rel = m.group(1).strip()
            cur = []
            continue
        if cur_rel is not None:
            cur.append(ln)
    if cur_rel is not None:
        blocks.append((cur_rel, cur))
    return [(rel, blk) for rel, blk in blocks if any(ln.startswith("@@") for ln in blk)]


def _has_hunks(payload):
    """payload 是否含 hunk 行（`@@`）。

    用来区分两种「解析出 0 个文件块」：
    - **无** `@@` ⇒ 真的与基准无差异 ⇒ 无害，跳过即可；
    - **有** `@@` 却解析不出块 ⇒ **diff 格式不认识**（如 Windows 某次改了
      `--patch` 产出格式而 Mac 侧解析器没跟上，`sync_1019h` 实测踩过）
      ⇒ 必须报错交人工，**不得静默当成「无变更」放过**。
    """
    return "@@" in payload


def _to_git_patch(rel, blk):
    """把 diff 块规整成 `git apply` 可解析的 patch（MT-20 / MT-38）。

    两种输入都归一到同一输出：
    - **旧格式**（difflib）：`--- rel@ref` / `+++ rel` → 重写为 git 风格；
    - **新格式**（MT-38 后 Windows 产的标准 git patch）：块首已是
      `diff --git a/rel b/rel`、`--- a/rel`、`+++ b/rel`。

    统一做法：丢弃输入里原有的 `diff --git` / `--- ` / `+++ ` 行（避免
    `a/` `b/` 前缀被叠成 `a/a/`），按 rel 重建头部，并把 `index` 行
    重排到 `diff --git` 之后、`---` 之前 —— git 只认该位置，放错则
    `--3way` 拿不到基准 blob、退化成普通 apply。
    """
    body, index_lines = [], []
    for ln in blk:
        if ln.startswith("diff --git "):
            continue
        if ln.startswith("--- ") or ln.startswith("+++ "):
            continue
        if _INDEX_RE.match(ln):
            index_lines.append(ln)
            continue
        body.append(ln)
    head = ["diff --git a/%s b/%s" % (rel, rel)]
    head.extend(index_lines)
    head.extend(["--- a/%s" % rel, "+++ b/%s" % rel])
    return "\n".join(head + body) + "\n"


_INDEX_RE = re.compile(r"^index [0-9a-f]{4,}\.\.[0-9a-f]{4,}(?: \d+)?$", re.M)


def _has_index_line(patch_text):
    """patch 是否带 `index <old>..<new> <mode>` 行（MT-38）。

    有 index 行时 git 才拿得到基准 blob ⇒ `git apply --3way` 可做三方合并
    （patch 基于旧基准、目标又被别的提交推进时仍能合上）；
    没有 index 行时 --3way 与普通 apply 等价（仍直接失败）。
    """
    return bool(_INDEX_RE.search(patch_text))


def _restore_paths(repo, rels):
    """把 patch 目标文件恢复到 HEAD（MT-38，仅 apply 失败后调用）。

    调用前提：这些路径已通过冲突检查（apply 前无本地未提交修改），
    因此恢复到 HEAD 不会丢失任何用户改动。
    `git apply --3way` 冲突时会把冲突标记写进工作区并登记 index，
    必须清理，否则下一次同步的冲突检查会被自己留下的脏状态挡住。
    """
    for rel in rels:
        if _git(repo, "cat-file", "-e", "HEAD:%s" % rel).returncode == 0:
            _git(repo, "checkout", "HEAD", "--", rel)
        else:
            # 新增文件（HEAD 中不存在）：移出 index 并删掉刚被 patch 写入的副本
            _git(repo, "reset", "-q", "--", rel)
            p = os.path.join(repo, rel)
            if os.path.isfile(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _patch_targets(payload):
    """提取 diff 包涉及的全部目标文件（用于冲突检查）。

    新格式优先按 `diff --git a/<rel> b/<rel>` 取（`b/` 为 `/dev/null`
    即删除场景，回落 `a/` 侧）；无 `diff --git` 时回落旧格式外层分隔头。
    """
    gits = set()
    for m in re.finditer(r"^diff --git a/(.+) b/(.+)$", payload, re.M):
        a_side, b_side = m.group(1).strip(), m.group(2).strip()
        gits.add(a_side if b_side == "/dev/null" else b_side)
    if gits:
        return gits
    return {m.group(1).strip()
            for m in re.finditer(r"^--- (.+) ---$", payload, re.M)}


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
    """（已停用目录级清扫 2026-10-16）成功后清理已处理的分片原文与标记文件。

    🔴 **不再从 ingest 调用** —— 目录级清扫会把**其他包**的残留分片连坐删除
    （实测 `sync_1016t` 分片被 `sync_1016u` 成功入库时的清理连带删除，2026-10-16）。
    清理职责已移交 `fg-sync-watcher.py` / `fg-sync-bypass.py`（各清**本包**分片+done，
    watcher 幂等分支兜底模型直跑路径）。
    本函数保留仅供显式调用方使用；若被调用，只清 sync_in.md 与 .done、**不动分片**。
    """
    if not os.path.isdir(src):
        return
    for fn in sorted(os.listdir(src)):
        p = os.path.join(src, fn)
        if not os.path.isfile(p):
            continue
        if fn in ("sync_in.md",) or fn.endswith(".done"):
            try:
                os.unlink(p)
            except OSError as exc:
                print("⚠️ 自动清理跳过 %s：%s" % (fn, exc))
    print("🧹 已清理聚合文件与 .done 标记（分片原文保留，由 watcher/bypass 各清本包）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="放着 base64 分片文本（.txt/.md）的目录")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--commit", default="fg-sync: 公司端同步")
    ap.add_argument("--quick", action="store_true",
                    help="增量测试：只跑与本次入库文件相关的测试文件（<10s）")
    ap.add_argument("--full-repo", action="store_true",
                    help="一次性完整同步授权：跳过目录白名单（仍拒绝 Data/、密钥、.git 等危险路径）")
    ap.add_argument("--only", default=None,
                    help="只处理 src 目录下指定的单个文件名（隔离目录残留分片，避免阻塞；"
                         "fg_sync_tool -f 模式必传 sync_in.md）")
    args = ap.parse_args()

    sys.path.insert(0, os.path.join(args.repo, "scripts"))
    from restore_from_base64 import extract_marked, _decode  # 复用既有解析

    raw = ""
    if args.only:
        # --only 模式：只读指定文件（fg_sync_tool -f 传 sync_in.md），
        # 目录里其他包残留分片不再阻塞本包（2026-10-16：ak 残留曾阻塞 al 入库）。
        fp = os.path.join(args.src, args.only)
        if os.path.isfile(fp):
            with open(fp, encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()
        else:
            print("❌ --only 指定的文件不存在：%s" % fp)
            return 2
    else:
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

        # 分类：__patch__/ 前缀 = 统一 diff 包（MT-20，不命中白名单，单独 apply）
        patch_diffs = sorted(m for m in members if m.startswith(PATCH_PREFIX))
        members = [m for m in members if not m.startswith(PATCH_PREFIX)]

        allowed, denied = [], []
        for m in members:
            (allowed if _allowed(m, full_repo=args.full_repo) else denied).append(m)
        if denied:
            print("⛔ 以下文件不在白名单内，已拒绝（不入库）：")
            for d in denied[:20]:
                print("   - " + d)
            if len(denied) > 20:
                print("   … 共 %d 个被拒" % len(denied))
        if not allowed and not patch_diffs:
            print("❌ 没有任何文件通过白名单（也无 __patch__ 包），中止。")
            return 2

        # 冲突检查：与仓库未提交修改取交集（普通文件 + patch 目标文件）
        dirty, err = _dirty_paths(args.repo)
        if err:
            print("⚠️ 无法读取 git 状态（%s），中止（不冒险覆盖）。" % err)
            return 2
        conflict = sorted(set(allowed) & set(dirty))
        patch_targets = set()
        for pd in patch_diffs:
            with open(os.path.join(tmp, pd), encoding="utf-8",
                      errors="replace") as fh:
                patch_targets |= _patch_targets(fh.read())
        conflict += sorted(patch_targets & set(dirty))
        if conflict:
            print("⛔ 与 Mac 本地未提交修改冲突，中止（不自动覆盖），冲突文件：")
            for c in conflict:
                print("   - " + c)
            print("处理方式：先在 Mac 提交/丢弃本地改动，再重新触发同步。")
            return 2

        # 应用 __patch__/ diff 包（MT-20）：任一失败 ⇒ 保留分片告警，绝不半途入库
        applied = []
        for pd in patch_diffs:
            pkg = os.path.basename(pd)
            if pkg.endswith(".diff"):
                pkg = pkg[:-len(".diff")]
            with open(os.path.join(tmp, pd), encoding="utf-8",
                      errors="replace") as fh:
                payload = fh.read()
            blocks = _split_patch_payload(payload)
            if not blocks:
                if _has_hunks(payload):
                    # 含 hunk 却解析不出块 ⇒ diff 格式不认识（≠ 真无差异）
                    # ⇒ 必须报错并保留分片，不得静默放过（sync_1019h 曾因此假成功 ✗）
                    print("⛔ %s：含 hunk 但解析不出任何文件块（diff 格式不认识），"
                          "分片已保留待排查。" % pd)
                    print("   请核对 pack_many.py --patch 的产出格式是否已变更，"
                          "并同步更新 _split_patch_payload。")
                    return 2
                print("⚠️ %s：无可应用变更（与基准无差异）" % pd)
                continue
            for rel, blk in blocks:
                patch_text = _to_git_patch(rel, blk)
                # MT-38：带 index 行时用 --3way（基准漂移也能三方合并）；
                # 无 index 行时 --3way 与普通 apply 等价（仍直接失败）。
                use_3way = _has_index_line(patch_text)
                apply_args = ["apply", "--whitespace=nowarn"]
                if use_3way:
                    apply_args.append("--3way")
                r = _git(args.repo, *apply_args, "-", input=patch_text)
                if r.returncode != 0:
                    print("⛔ patch 应用失败（%s → %s），分片已保留待排查："
                          % (pkg + ".diff", rel))
                    print(r.stderr.strip())
                    # --3way 冲突会把冲突标记写进工作区并登记 index ⇒ 恢复目标文件，
                    # 让工作区保持干净（失败一律交人工，不自动重试）。
                    _restore_paths(args.repo, applied + [rel])
                    if use_3way:
                        print("↩️ 已恢复本次 patch 触及的文件到 HEAD（避免冲突标记残留）")
                    return 2
                applied.append(rel)
                print("📦 应用 patch：%s → %s%s"
                      % (pkg + ".diff", rel, "（--3way）" if use_3way else ""))
        if applied:
            print("应用 patch %d 个文件：%s" % (len(applied), ", ".join(applied[:8]) +
                  (" …" if len(applied) > 8 else "")))

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

        # 只 add 本次入库/应用文件，避免 git add -A 把运行态/未提交改动连带提交
        add_all = sorted(set(copied) | set(applied))
        r = _git(args.repo, "add", "--", *add_all)
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

    # 增量模式：由已入库文件推导相关测试文件（tests/**/test_<模块>*.py 递归前缀匹配）
    if args.quick:
        import glob as _glob
        related = set()
        for rel in copied:
            base = os.path.basename(rel)
            if base.startswith("test_"):
                # 新测试文件可能在子目录（tests/dashboard/ 等）：glob 定位真实路径，
                # 不生成平铺 tests/test_xxx.py（不存在 ⇒ pytest not found）。
                exact = _glob.glob(os.path.join(args.repo, "tests", "**", base),
                                   recursive=True)
                for p in exact:
                    if os.path.isfile(p):
                        related.add(p)
                continue
            stem = os.path.splitext(base)[0]
            # 递归前缀匹配（tests/dashboard/、tests/signal/ 等子目录 + _warning/_key 等语义后缀）：
            # 旧逻辑 tests/test_<stem>.py 平铺精确匹配 ⇒ 子目录/后缀测试全漏，生成不存在路径
            # ⇒ pytest "file or directory not found" ⇒ 增量假失败（2026-10-10 sync_1010k 实测）。
            hits = _glob.glob(os.path.join(args.repo, "tests", "**", "test_" + stem + "*.py"),
                              recursive=True)
            for p in hits:
                if os.path.isfile(p):
                    related.add(p)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
