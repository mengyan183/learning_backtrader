# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/clash_rule_probe.py` ✓。

为什么放行（2026-11-28）：需读 Mac 上的 ClashX 配置（不在仓库里）✗
且要调 Clash external-controller API 逐节点测 OKX ✓
安全：只 GET（proxies / rules / delay），**不 PUT**（不切节点、不改配置）✓
     不回显 secret 值，只说「有/无」✓
"""
