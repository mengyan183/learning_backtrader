# -*- coding: utf-8 -*-
"""任务队列的动作包 ✓ —— 每个模块导出 `ACTIONS` 字典，由调度器合并。

约定（2026-11-19 第四轮）：
  · 只 import `queue_core` + 标准库 ✓
  · **不碰队列状态** ✗（`QUEUE` / `run_once` / flock 在调度器里）
  · 包之间**不互相 import** ✗（共享的往 `queue_core` 上移）
"""
