# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/git_push_diag.py` ✓。

为什么放行（2026-11-26）：同步链 `mac → github → gitee → windows` 断在第一步，
而 `run_git` 白名单**没有** `remote` / `push` ✗ ⇒ 只能靠本脚本诊断 ✓
安全：全部只读；`push` 用 `--dry-run`（只连服务器、不改远端）✓
"""
