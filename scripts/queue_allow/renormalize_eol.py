# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/renormalize_eol.py` ✓。

为什么放行：把 `docs/*.md` 的行尾按 `.gitattributes` 重新规范化（CRLF→LF）并提交 ✓。
⚠️ 只动 `docs/` 下的 .md，且工作区有其他脏文件时**直接拒绝** ✓
⚠️ 不改系统、不装包 ✗。
"""
