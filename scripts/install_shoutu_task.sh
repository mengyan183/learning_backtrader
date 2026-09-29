#!/usr/bin/env bash
# ==========================================================================
# Register / re-register the "Shoutu daily fetch" launchd job.
#
# macOS counterpart of install_shoutu_task.cmd. Run it directly:
#     bash scripts/install_shoutu_task.sh
#
# NO sudo required -- this writes to ~/Library/LaunchAgents (per-user domain).
#
# Schedule: weekly, Tue-Sat, 06:30 local time.
#   Tue-Sat (not Mon-Fri): Tue 06:30 Beijing = Mon 18:30 ET, so it picks up
#   the US Monday session; Sat 06:30 Beijing = Fri 18:30 ET, so it picks up
#   the US Friday session. Covers US Mon-Fri with NO lag.
#
# 06:30 falls inside the intersection of the DST and standard-time safe
# windows (05:00-08:00):
#   DST       after-hours ends 04:00, overnight starts 08:00
#   standard  after-hours ends 05:00, overnight starts 09:00
#
# See docs/trading-discipline.md section 14.5 for the full rationale.
# ==========================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.fg.shoutu-daily"
AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENT_DIR/$LABEL.plist"
DOMAIN="gui/$(id -u)"

mkdir -p "$AGENT_DIR" "$REPO/logs"

echo "Registering launchd job: $LABEL"
echo "  repo:     $REPO"
echo "  plist:    $PLIST"
echo "  schedule: weekly Tue-Sat 06:30 (local time)"
echo

# ---------------------------------------------------------------- 生成 plist
# Weekday: 0/7=Sunday, 1=Monday, ... 6=Saturday  =>  Tue..Sat = 2,3,4,5,6
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$REPO/scripts/shoutu_daily.sh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$REPO</string>

    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>30</integer></dict>
    </array>

    <key>StandardOutPath</key>
    <string>$REPO/logs/shoutu_launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$REPO/logs/shoutu_launchd.err.log</string>

    <key>ProcessType</key>
    <string>Background</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

# ---------------------------------------------------------------- 装载（幂等）
# bootout 在未装载时会返回非零，属正常，故 || true。
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"

echo "[OK] registered."
echo
echo "=== 状态 ==="
launchctl print "$DOMAIN/$LABEL" | grep -E "state|program|runs|last exit" || true
echo
echo "=== 后续操作 ==="
echo "  立即跑一次（会覆盖当天 06:30 快照，见 14.5）:"
echo "      launchctl kickstart -k $DOMAIN/$LABEL"
echo "  暂停（保留配置，推荐）:  launchctl disable $DOMAIN/$LABEL"
echo "  恢复:                    launchctl enable  $DOMAIN/$LABEL"
echo "  彻底删除:                launchctl bootout $DOMAIN/$LABEL && rm '$PLIST'"
echo "  看运行日志:              tail -f '$REPO/logs/shoutu_daily.log'"
echo
echo "=== 建议同时设置定时唤醒（需 sudo，本脚本不代跑）==="
echo "  Mac 睡眠时 launchd 不会执行；唤醒后才会补跑。"
echo "  若要保证 06:30 一定在运行状态："
echo "      sudo pmset repeat wakeorpoweron TWRFS 06:25:00"
echo "  注意 TWRFS 不是 MTWRFS：pmset 的日期字母为"
echo "      M=Mon T=Tue W=Wed R=Thu F=Fri S=Sat U=Sun"
echo "  任务只跑周二~周六，含 M 会白白唤醒周一。"
