# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/install_dep.py` ✓。

为什么放行（2026-11-27）：队列没有通用 `pip install` 动作 ✗，而
`exchange_calendars` 要装到 **Mac 的 .venv** ✓
安全：包名白名单（只 `exchange_calendars`）、只装当前解释器、默认 dry-run、
      装完验证可导入 ✓
"""
