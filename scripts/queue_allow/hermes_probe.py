# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/hermes_probe.py` ✓。

为什么放行（2026-11-24）：`evolve_review.py` 报 Hermes(8642) 超时 ✗
而端口/`/v1/models` 都正常（401）⇒ 需真发一次 completion 才能确认上游 ✓
本脚本只读 key 并发一次 8 token 的请求，不改仓库 ✓
"""
