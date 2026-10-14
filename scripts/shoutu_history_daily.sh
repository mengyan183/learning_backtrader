#!/usr/bin/env bash
# ==========================================================================
# Shoutu history (bsk browser side-channel) -- conditional daily fetch
#
# launchd: com.fg.shoutu-history.plist, every day 06:35 (after shoutu-daily 06:30)
#
# Why conditional: fetch_shoutu_history.py needs a live bsk browser session
# (Chrome + szdt.tech logged-in page). Browsers are not guaranteed up at
# 06:35, and history shows "Chrome not running after wake" breaks the naive
# launchd approach. So: try; on failure log quietly and exit 0 (no launchd
# retry noise, no push alerts -- the script itself never pushes).
#
# Log: logs/shoutu_history_daily.log (appended)
# ==========================================================================
set -u
cd /Users/xingguo/learning_backtrader || exit 1
LOG="logs/shoutu_history_daily.log"
mkdir -p logs

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  if ! .venv/bin/python scripts/fetch_shoutu_history.py 2>&1; then
    echo "[FAIL] bsk 会话不可用或抓取失败（仅记录，不打扰；明天 06:35 再试）"
  fi
  echo "---"
} >> "$LOG" 2>&1

exit 0
