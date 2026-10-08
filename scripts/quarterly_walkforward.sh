#!/bin/bash
# 季度 walk-forward 重标定（C-5）：由 launchd 每季度触发（1/4/7/10 月 1 日 08:00）
# 运行 evolve_walkforward.py --write，结果写入 evolution/walkforward-report.md，日志留痕。
LOG="/Users/xingguo/learning_backtrader/logs/walkforward_launchd.log"
REPO="/Users/xingguo/learning_backtrader"
PY="$REPO/.venv/bin/python"
echo "==== walkforward $(date '+%F %T') ====" >> "$LOG"

cd "$REPO" || { echo "cd 失败" >> "$LOG"; exit 1; }

"$PY" scripts/evolve_walkforward.py --write >> "$LOG" 2>&1
rc=$?
echo "exit=$rc" >> "$LOG"
exit $rc
