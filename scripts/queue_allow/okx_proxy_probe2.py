# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/okx_proxy_probe2.py` ✓。

为什么放行（2026-11-28）：需在 **Mac 的真实网络环境**下区分
「代理没生效 / 节点屏蔽 OKX / 直连可行」三种情况 ✗
本脚本**只读**、只做 HTTP 探测 + 读凭据里的 `proxy` 字段（不回显密钥）✓
"""
