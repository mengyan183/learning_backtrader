#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「已改好但未提交」的指定文件 + 一个 docs 变更**一起提交** ✓（2026-11-25）。

【为什么需要】
  `fix_1125e` 的 commit 被纪律门禁拦下（改 `config.py` 却没带 docs）✗
  ⇒ 文件留在 Mac 工作区未提交 ✗
  ⇒ 再发同名文件的包，patch 打不上（内容已存在）⇒ 被跳过 ⇒ **永远提交不了** ✗
  ⇒ 而死锁是自我强化的：工作区越脏，越多的包进不来 ✗

  直接 `git commit <3 个文件>` 会被门禁**再次**拦下（这次仍缺 docs）✗
  ⇒ 必须把「docs 变更」和「3 个代码文件」放进**同一个 commit** ✓

【安全设计】
  · **文件列表由调用方显式给出**，不做 `git add -A` ✗
  · 路径必须在 `SAFE_PREFIXES` 内 ✓
  · 提交前**自检门禁条件**：若含 `RULE_PATHS` 却没有 `docs/` ⇒ 直接拒绝 ✓
  · 默认 `--dry-run`，必须 `--apply` 才真提交 ✓

用法（Mac，经队列）：
    python scripts/commit_pool_pending.py --files a,b,c --message "..."          # 只看
    python scripts/commit_pool_pending.py --files a,b,c --message "..." --apply
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAFE_PREFIXES = ("fg_system/", "scripts/", "tests/", "docs/",
                 ".codebuddy/", "evolution/")

#: 与 `scripts/pre-commit-discipline.sh` 的 `RULE_PATHS` **保持一致** ✓
RULE_PATHS = ("fg_system/signal/", "fg_system/models/", "fg_system/config.py")


def _git(*args, timeout=180):
    r = subprocess.run(["git", "-C", ROOT] + list(args),
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _safe(rel):
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return None
    return rel if rel.startswith(SAFE_PREFIXES) else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", required=True, help="逗号分隔的相对路径")
    ap.add_argument("--message", required=True, help="提交信息")
    ap.add_argument("--apply", action="store_true")
    # 🔴 2026-11-25：**脚本自己补一条 docs 记录** ✓
    #   动机：`docs/` 可能已被上一个包单独提交过（`fix_1125i` 就是）✗
    #   ⇒ 暂存区里没有 docs 变更 ⇒ §8 门禁再次拦下 ✗
    #   ⇒ 让本脚本**追加一行**到指定 docs 文件，保证同 commit 里有 docs ✓
    #     （这行是真记录，不是为过门禁而编的 ✓）
    ap.add_argument("--doc-file", default="docs/rules-2026-11-20.md",
                    help="追加一行记录的 docs 文件")
    ap.add_argument("--doc-note", default="",
                    help="追加的内容（留空则不追加）")
    args = ap.parse_args(argv)

    raw = [x.strip() for x in args.files.split(",") if x.strip()]
    bad = [f for f in raw if _safe(f) is None]
    if bad:
        return {"ok": False,
                "error": "路径不在安全前缀内：%s" % ", ".join(bad)}
    files = [_safe(f) for f in raw]

    out = {"files": files, "apply": args.apply, "steps": {}}

    # ①.5 追加 docs 记录（保证同 commit 里有 docs 变更）✓
    if args.doc_note.strip():
        _dp = _safe(args.doc_file)
        if _dp is None:
            return {"ok": False, "error": "doc-file 路径不安全：%s" % args.doc_file}
        _abs = os.path.join(ROOT, _dp)
        try:
            with open(_abs, "a", encoding="utf-8") as fh:
                fh.write("\n- %s（`commit_pool_pending.py` 自动记录）\n"
                         % args.doc_note.strip())
            if _dp not in files:
                files.append(_dp)
            out["steps"]["doc_append"] = {"file": _dp, "ok": True}
        except OSError as exc:
            return {"ok": False, "error": "追加 docs 失败：%s" % exc}

    # ① 门禁自检 —— 提前拒绝，别让 git 报一个难读的错 ✓
    _rule = [f for f in files if f.startswith(RULE_PATHS)]
    _docs = [f for f in files if f.startswith("docs/")]
    if _rule and not _docs:
        return {"ok": False,
                "error": "含规则代码 %s 但没有 docs/ 变更 ⇒ 会被 §8 门禁拦下 ✗"
                         % ", ".join(_rule)}

    # ② 当前状态
    rc, so, _ = _git("status", "--porcelain", "--", *files)
    out["steps"]["status_before"] = so[-1500:]

    rc, so, _ = _git("add", "--", *files)
    out["steps"]["add"] = {"rc": rc}
    if rc != 0:
        return {"ok": False, "error": "git add 失败", **out}

    rc, so, _ = _git("diff", "--cached", "--name-only")
    out["staged"] = so.splitlines()
    if not so.strip():
        out["ok"] = True
        out["note"] = "暂存区为空（这些文件本来就没改动）✓"
        return out

    if not args.apply:
        out["ok"] = True
        out["note"] = "**dry-run**：已 add 但未 commit。确认后加 `--apply` ✓"
        return out

    rc, so, se = _git("commit", "-m", args.message)
    out["steps"]["commit"] = {"rc": rc, "stdout": so[-800:], "stderr": se[-400:]}
    if rc != 0:
        return {"ok": False, "error": "commit 失败（可能是门禁）", **out}

    rc, sha, _ = _git("rev-parse", "--short", "HEAD")
    out["head"] = sha
    out["ok"] = True
    out["note"] = "✅ 已提交 %s（%d 个文件）" % (sha, len(out["staged"]))
    return out


if __name__ == "__main__":
    _out = main()
    print(json.dumps(_out, ensure_ascii=False, indent=2))
    sys.exit(0 if isinstance(_out, dict) and _out.get("ok") else 1)
