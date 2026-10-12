#!/bin/bash
# fg-auto-update: 每日 02:00 检查前一日是否有代码提交，有则更新常驻程序为最新代码。
# 逻辑：
#   1) git fetch origin（静默，失败不阻塞）；若本地落后 origin/main 且可快进 → pull --ff-only
#   2) 统计"昨日 00:00 ~ 今日 00:00"的本地提交数
#   3) 有提交 → 重启常驻服务（dashboard / realtime / futuopend）使新代码生效；无 → 跳过
# 日志：logs/auto-update.log（仓库内）
set -uo pipefail
REPO=/Users/xingguo/learning_backtrader
LOG="$REPO/logs/auto-update.log"
SERVICES=(com.xingguo.fg-dashboard com.xingguo.fg-realtime com.xingguo.futuopend)

cd "$REPO" || exit 1
mkdir -p "$(dirname "$LOG")"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $1" >> "$LOG"; }

log "=== auto-update start ==="

# 1) 远端同步（仅快进；有本地冲突时不动，保安全）
if git fetch origin --quiet 2>>"$LOG"; then
  BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
  if [ "${BEHIND:-0}" -gt 0 ]; then
    if git pull --ff-only origin main 2>>"$LOG"; then
      log "pulled ${BEHIND} commit(s) from origin/main"
    else
      log "pull 失败（非快进/冲突），跳过远端同步，保留本地状态"
    fi
  fi
else
  log "git fetch 失败（网络或远端不可达），跳过远端同步"
fi

# 2) 检查前一日是否有代码提交（含刚 pull 的远端提交）
YESTERDAY=$(date -v-1d '+%Y-%m-%d')
TODAY=$(date '+%Y-%m-%d')
NEW_COMMITS=$(git log --since="$YESTERDAY 00:00:00" --until="$TODAY 00:00:00" --oneline 2>/dev/null | wc -l | tr -d ' ')

# 3) 有提交 → 重启常驻服务
if [ "${NEW_COMMITS:-0}" -gt 0 ]; then
  log "前一日($YESTERDAY)有 ${NEW_COMMITS} 个提交，重启常驻服务加载最新代码"
  for svc in "${SERVICES[@]}"; do
    if launchctl list 2>/dev/null | grep -q "$svc"; then
      if launchctl kickstart -k "gui/$(id -u)/$svc" 2>>"$LOG"; then
        log "  ✓ $svc 已重启"
      else
        log "  ✗ $svc 重启失败"
      fi
    fi
  done
else
  log "前一日($YESTERDAY)无新提交，跳过"
fi

log "=== auto-update end ==="
