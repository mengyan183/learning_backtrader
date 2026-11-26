# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/proxy_probe.py` ✓。

为什么放行（2026-11-26）：kalshi 已确认注入代理（`has_proxy: true`）但仍
`Connection reset`，需区分「代理没跑 / 节点屏蔽 / Kalshi 侧故障」✗
本脚本**只读**、只做 HTTP 探测，不写任何文件 ✓
"""
