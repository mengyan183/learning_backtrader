# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/clash_rule_probe2.py` ✓。

为什么放行（2026-11-28）：v1 只读了第一个配置（`~/.config/clash/config.yaml`，
仅 6 条规则 / 0 组 / `MATCH,DIRECT`）⇒ 结论失真 ✗
本版列出**全部**候选配置并逐节点测 OKX ✓
安全：只 GET（version / proxies / delay），**不 PUT**（不切节点、不改配置）✓
"""
