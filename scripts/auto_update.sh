#!/bin/bash
# fg-auto-update v2: 每日 02:00 校验「运行版本 commit」vs「仓库 HEAD」，不一致则更新常驻程序。
#
# 精确语义（不再依赖"昨日是否有提交"的时间窗口）：
#   服务启动时记录的 commit id（部署版本）≠ 仓库当前 HEAD → 该服务仍跑旧代码 → 重启加载最新。
#   记录里 PID 已变化（服务被外部重启过，已跑最新代码）→ 仅刷新记录，不重复重启。
#
# 纳入范围：本仓库代码的常驻服务（dashboard / realtime）；
#   futuopend 为富途官方网关（非本仓库代码），无版本更新语义，不纳入。
set -uo pipefail
REPO=/Users/xingguo/learning_backtrader
LOG="$REPO/logs/auto-update.log"
STATE="$REPO/logs/runtime-state"

cd "$REPO" || exit 1
mkdir -p "$(dirname "$LOG")"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $1" >> "$LOG"; }

# 服务清单：label|launchd label（PID 以 launchctl 为准，避免 pgrep 匹配到 bash 包装进程）
SERVICES=(
  "dashboard|com.xingguo.fg-dashboard"
  "realtime|com.xingguo.fg-realtime"
)

svc_pid() { launchctl list 2>/dev/null | awk -v lbl="$1" '$3==lbl && $1!="-" {print $1; exit}'; }

read_state() { grep "^$1 " "$STATE" 2>/dev/null | awk '{print $2, $3}'; }
write_state() {
  local label=$1 commit=$2 pid=$3
  grep -v "^$label " "$STATE" 2>/dev/null > "$STATE.tmp" || true
  echo "$label $commit $pid" >> "$STATE.tmp"
  mv "$STATE.tmp" "$STATE"
}

log "=== auto-update start ==="

# 1) 远端同步（仅快进；冲突则保留本地）
if git fetch origin --quiet 2>>"$LOG"; then
  BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
  if [ "${BEHIND:-0}" -gt 0 ]; then
    if git pull --ff-only origin main 2>>"$LOG"; then
      log "pulled ${BEHIND} commit(s) from origin/main"
    else
      log "pull 失败（非快进/冲突），保留本地状态"
    fi
  fi
else
  log "git fetch 失败，跳过远端同步"
fi

HEAD=$(git rev-parse HEAD)

# 2) 逐服务校验运行版本
for entry in "${SERVICES[@]}"; do
  label="${entry%%|*}"
  llabel="${entry#*|}"
  CUR_PID=$(svc_pid "$llabel")

  if [ -z "$CUR_PID" ]; then
    log "  $label: 服务未运行（launchctl 无 PID），跳过"
    continue
  fi

  read -r REC_COMMIT REC_PID <<< "$(read_state "$label")"

  if [ -z "$REC_COMMIT" ]; then
    # 首次记录：仅登记当前运行版本，不重启
    write_state "$label" "$HEAD" "$CUR_PID"
    log "  $label: 首次登记运行版本 $HEAD (pid $CUR_PID)"
  elif [ "$REC_COMMIT" = "$HEAD" ]; then
    log "  $label: 运行版本与仓库一致 ($(echo $HEAD | cut -c1-7))，无需更新"
  elif [ "$REC_PID" != "$CUR_PID" ]; then
    # 服务已被外部重启（加载了最新代码），仅刷新记录
    write_state "$label" "$HEAD" "$CUR_PID"
    log "  $label: 进程已被外部重启（pid ${REC_PID}->${CUR_PID}），刷新版本记录 $HEAD"
  else
    # 记录 PID 未变且版本落后 → 服务仍跑旧代码 → 重启加载最新
    if launchctl kickstart -k "gui/$(id -u)/$llabel" 2>>"$LOG"; then
      sleep 1
      NEW_PID=$(svc_pid "$llabel")
      write_state "$label" "$HEAD" "${NEW_PID:-$CUR_PID}"
      log "  ✓ $label: 运行版本 $(echo $REC_COMMIT | cut -c1-7) != 仓库 $(echo $HEAD | cut -c1-7)，已重启（pid ${NEW_PID:-$CUR_PID}）"
    else
      log "  ✗ $label: 重启失败，保留旧状态"
    fi
  fi
done

log "=== auto-update end ==="
