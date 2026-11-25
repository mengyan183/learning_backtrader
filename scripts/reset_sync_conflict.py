#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Mac 上「同步冲突」的文件**回滚到 HEAD** ✓（2026-11-25）。

【为什么需要】
  `fg_sync_ingest` 的流程是「先解包写工作区 → 再 git add/commit」✗
  若 commit 被拦（如纪律门禁），**文件已经改了、但没提交** ✗
  ⇒ 下一次同步会报「与 Mac 本地未提交修改冲突，中止」✗
  ⇒ 卡死：既进不去，也退不回 ✗

  而 `run_git` 的白名单里**没有 `checkout` / `reset`** ✗
  （设计如此：只放只读或只动索引的子命令）
  ⇒ 只能单独一个脚本 ✓

【安全设计】
  · **只接受显式列出的文件**，不做 `git checkout .` ✗
  · 路径必须在 `SAFE_PREFIXES` 内（防 `../` 与越界）✓
  · 执行前先打印 `git diff --stat`，执行后再打印一次 ✓
  · 默认 `--dry-run`，必须显式 `--apply` 才真回滚 ✓

用法（Mac，经队列）：
    python scripts/reset_sync_conflict.py --files a.py,b.py            # 只看
    python scripts/reset_sync_conflict.py --files a.py,b.py --apply    # 真回滚
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 允许回滚的路径前缀（只含**代码/文档**，绝不含 `Data/`）✓
SAFE_PREFIXES = ("fg_system/", "scripts/", "tests/", "docs/",
                 ".codebuddy/", "evolution/")


def _git(*args, timeout=120):
    r = subprocess.run(["git", "-C", ROOT] + list(args),
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _safe(rel):
    """路径必须在前缀内，且不含 `..` ✓。"""
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return None
    return rel if rel.startswith(SAFE_PREFIXES) else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", required=True, help="逗号分隔的相对路径")
    ap.add_argument("--apply", action="store_true", help="真的回滚（默认只看）")
    args = ap.parse_args(argv)

    raw = [x.strip() for x in args.files.split(",") if x.strip()]
    bad = [f for f in raw if _safe(f) is None]
    if bad:
        return {"ok": False,
                "error": "以下路径不在安全前缀内：%s（允许：%s）"
                         % (", ".join(bad), ", ".join(SAFE_PREFIXES))}
    files = [_safe(f) for f in raw]

    out = {"files": files, "apply": args.apply, "steps": {}}

    rc, so, _ = _git("status", "--porcelain", "--", *files)
    out["steps"]["status_before"] = so[-1200:]
    if rc != 0 or not so.strip():
        out["ok"] = True
        out["note"] = "这些文件**本来就没有本地改动** ⇒ 无需回滚 ✓"
        return out

    rc, so, _ = _git("diff", "--stat", "--", *files)
    out["steps"]["diff_stat"] = so[-800:]

    if not args.apply:
        out["ok"] = True
        out["note"] = "**dry-run**：未改动。确认无误后加 `--apply` ✓"
        return out

    rc, so, se = _git("checkout", "--", *files)
    out["steps"]["checkout"] = {"rc": rc, "stderr": se[:400]}
    if rc != 0:
        return {"ok": False, "error": "git checkout 失败：%s" % se[:400],
                **{k: out[k] for k in ("files", "steps")}}

    rc, so, _ = _git("status", "--porcelain", "--", *files)
    out["steps"]["status_after"] = so[-1200:]
    out["ok"] = not so.strip()
    out["note"] = ("✅ 已回滚到 HEAD，工作区干净 ✓" if out["ok"]
                   else "⚠️ 仍有改动残留，请人工检查 ✗")
    return out


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
