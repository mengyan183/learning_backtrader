# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/disable_launchd_job.py` ✓。

为什么放行（2026-11-25）：队列只有 `restart_queue`（重启），**没有「停止」** ✗
首个用例：`com.fg.shoutu-history` —— 服务端 `stock_emotion/history`
对全部 8 只返回 `data: []`，而脚本是「失败静默 rc=0」⇒ 每天白跑 41 天 ✗
安全：label 必须以 `com.fg.` / `com.xingguo.` 开头、默认 dry-run、
plist 只改名不删除、支持 `--restore` 反向恢复 ✓
"""
