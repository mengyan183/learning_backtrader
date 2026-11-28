# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/clash_proc_probe.py` ✓。

为什么放行（2026-11-28）：v1/v2 靠「猜配置路径」全失败 ——
`~/.config/clash/config.yaml` 只有 6 条规则/0 组/`MATCH,DIRECT`，
而 9090 返回 401 ⇒ 真配置在别处 ✗
本版改从 `ps aux` + `lsof` 反查进程与配置 ✓
安全：只读（ps / lsof / 读文件 / GET API），**不 kill、不 PUT、不改配置** ✓
"""
