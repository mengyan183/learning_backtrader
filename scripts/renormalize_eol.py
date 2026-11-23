#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把**指定文档**按 `.gitattributes` 重新规范化行尾（CRLF→LF）并提交 ✓。

【为什么需要（2026-11-23）】
  `docs/trading-discipline.md` 的 blob 是 **100% CRLF**（5688 CRLF / 5688 LF）✗
  ⇒ `pack_many` 判「patch 必失败」，整文件 336 KB ≈ **111 片**（≈74 分钟）✗
  ⇒ 而 `run_git` 白名单**没有 `add`**、`git_commit` 白名单**没有 `docs/`** ✗
  ⇒ 于是这个动作在队列里没有出口，只能让人上机敲命令 ✗（违反「Mac 侧操作走队列」）

  本脚本补上这个缺口：`run_script --param script=renormalize_eol.py` 即可 ✓

【安全边界】
  · 只接受 **`docs/` 下、`.md` 结尾**的路径 ✗ 不碰代码 / 数据 / 配置
  · 提交前检查：**除该文件外不得有其他脏文件** ⇒ 有就拒绝（不替人收拾工作区）✗
  · 提交用 **pathspec**（`git commit -m msg -- <path>`）⇒ 不会被别的脏暂存文件毒化 ✓
  · 推送固定 `origin HEAD:main` ✓ 不接受任意 refspec

用法（Mac，经队列）：
    python scripts/renormalize_eol.py --path docs/trading-discipline.md --push
本地调试：
    python scripts/renormalize_eol.py --path docs/x.md --dry-run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 允许规范化的前缀（只有文档）✓
ALLOW_PREFIX = "docs/"
ALLOW_EXT = ".md"


def valid_path(rel):
    """路径是否允许规范化 ✓ —— 返回 (ok, reason)。"""
    p = str(rel or "").strip().replace("\\", "/")
    if not p:
        return False, "路径为空"
    if p.startswith("/") or ".." in p.split("/"):
        return False, "必须是仓库内相对路径（禁止绝对路径 / `..`）"
    if not p.startswith(ALLOW_PREFIX):
        return False, "只允许 `%s` 下的文件（当前 %s）" % (ALLOW_PREFIX, p)
    if not p.endswith(ALLOW_EXT):
        return False, "只允许 `%s` 文件（当前 %s）" % (ALLOW_EXT, p)
    if not os.path.isfile(os.path.join(REPO, p)):
        return False, "文件不存在：%s" % p
    return True, ""


def _git(*args, timeout=180):
    r = subprocess.run(["git", "-C", REPO] + list(args),
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _eol_stats(path):
    """返回 (bytes, crlf, lf) —— 从**工作区**读，仅用于展示。"""
    try:
        with open(os.path.join(REPO, path), "rb") as f:
            d = f.read()
        return len(d), d.count(b"\r\n"), d.count(b"\n")
    except OSError:
        return 0, 0, 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="规范化文档行尾并提交")
    ap.add_argument("--path", required=True, help="仓库内相对路径（docs/*.md）")
    ap.add_argument("--push", action="store_true", help="提交后 push origin HEAD:main")
    ap.add_argument("--dry-run", action="store_true", help="只看会做什么，不改仓库")
    args = ap.parse_args(argv)

    ok, why = valid_path(args.path)
    if not ok:
        return {"ok": False, "error": why}

    rel = args.path.replace("\\", "/")
    out = {"path": rel, "steps": {}}

    # ① 工作区必须只有这一个文件有改动 ✗（不替人收拾别人的脏文件）
    rc, so, se = _git("status", "--porcelain")
    if rc != 0:
        return {"ok": False, "error": "git status 失败：%s" % se[:200]}
    dirty = [ln[3:].strip() for ln in so.splitlines() if ln.strip()]
    others = [d for d in dirty if rel not in d]
    out["steps"]["dirty_before"] = dirty[:10]
    if others:
        return {"ok": False,
                "error": "工作区还有其他脏文件，拒绝执行（先清理）：%s"
                         % ", ".join(others[:5]),
                "dirty": others[:10]}

    before = _eol_stats(rel)
    out["eol_before"] = {"bytes": before[0], "crlf": before[1], "lf": before[2]}

    if args.dry_run:
        out["ok"] = True
        out["dry_run"] = True
        return out

    # ② 重新规范化（只改索引里的 blob，工作区内容不动 ✓）
    rc, so, se = _git("add", "--renormalize", "--", rel)
    out["steps"]["add"] = {"rc": rc, "stderr": se[:300]}
    if rc != 0:
        return {"ok": False, "error": "git add --renormalize 失败：%s" % se[:300]}

    rc, so, se = _git("diff", "--cached", "--numstat", "--", rel)
    out["steps"]["staged"] = so[:200]
    if rc != 0 or not so.strip():
        return {"ok": False, "error": "暂存区没有变化 ⇒ 该文件已是 LF，无需规范化"}

    # ③ 用 **pathspec** 提交 ⇒ 不会被别的脏暂存文件毒化 ✓
    msg = ("chore(docs): 规范化 %s 行尾（CRLF→LF），"
           "为后续 patch 铺路" % os.path.basename(rel))
    rc, so, se = _git("commit", "-m", msg, "--", rel)
    out["steps"]["commit"] = {"rc": rc, "out": so[:300], "stderr": se[:300]}
    if rc != 0:
        return {"ok": False, "error": "commit 失败：%s" % (se or so)[:300]}

    # ④ 可选推送
    if args.push:
        rc, so, se = _git("push", "origin", "HEAD:main", timeout=300)
        out["steps"]["push"] = {"rc": rc, "out": so[-300:], "stderr": se[-300:]}
        if rc != 0:
            return dict(out, ok=False, error="提交成功但推送失败：%s" % se[-300:])

    out["ok"] = True
    return out


if __name__ == "__main__":
    import json
    res = main()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("ok") else 1)
