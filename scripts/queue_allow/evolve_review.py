# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/evolve_review.py` ✓。

为什么放行（2026-11-24）：
  每日链里这一步**连续多日 rc=1（185s）** ✗，而 `main()` 的失败分支只
  `print` 到 `/tmp/fg_daily.log` ✗（队列侧读不到）⇒ 无法定位 ✗
  ⇒ 放行后用 `run_script` 跑一次，把 traceback 落到任务回执里 ✓

⚠️ 副作用：正常路径会**追加** `evolution/memory/YYYY-MM-DD.md` 与
   登记新假说到 `evolution/hypotheses.md` ✓（这是它的本职，幂等去重）
"""
