#!/usr/bin/env bash
# ==========================================================================
# MT-68：注册自我进化「验证 + 周报」两个 launchd 作业（幂等，无需 sudo）。
#
# 背景：evolve_review 早已挂在 fg-daily 每日链，但 evolve_verify / evolve_weekly
# 从未注册定时 ⇒ 假说只进不出、周报不自动产（2026-10-26 诊断结论）。
#
# 作业：
#   com.xingguo.fg-evolve-verify   每日 06:10（fg-daily 5:30 数据链之后兜底）
#     - 纯本地，数据过期时 _data_is_stale() 闸门 return 2，拒绝回写（安全 ✓）
#   com.xingguo.fg-evolve-weekly   每周一 07:00 汇总上周（默认不推飞书，不带 --push）
#
# 重跑即重装（bootout → bootstrap → enable，幂等 ✓）。
# 用法：bash scripts/install_evolve_tasks.sh
# ==========================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
mkdir -p "$AGENT_DIR" "$REPO/logs"

register() {
    # $7 = 可选命令行参数（2026-10-29 新增：evolve_verify 走 --quiet ✓）
    local label="$1" hour="$2" minute="$3" weekday="$4" script="$5" log="$6"
    local extra="${7:-}"
    local plist="$AGENT_DIR/$label.plist"

    # weekday 为空 ⇒ 每日；否则固定星期（0=Sun … 6=Sat）
    local sched=""
    if [ -n "$weekday" ]; then
        sched="<dict><key>Weekday</key><integer>$weekday</integer><key>Hour</key><integer>$hour</integer><key>Minute</key><integer>$minute</integer></dict>"
    else
        sched="<dict><key>Hour</key><integer>$hour</integer><key>Minute</key><integer>$minute</integer></dict>"
    fi

    cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$label</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>.venv/bin/python "$REPO/scripts/$script"${extra:+ $extra}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO</string>
    <key>StartCalendarInterval</key>
    $sched
    <key>StandardOutPath</key>
    <string>$REPO/logs/$log</string>
    <key>StandardErrorPath</key>
    <string>$REPO/logs/$log</string>
    <key>ProcessType</key>
    <string>Background</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

    echo "== 注册 $label =="
    launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$plist"
    launchctl enable "$DOMAIN/$label"
    launchctl print "$DOMAIN/$label" | grep -E "state|program|last exit" || true
    echo
}

# 每日 06:10 验证（数据过期闸门 return 2，不回写 ✓）
# 2026-10-29：`--quiet` ⇒ 只播状态变化 ✓（跳过/样本不足/未变 adopted 各折叠一行 ✓）
register com.xingguo.fg-evolve-verify 6 10 "" evolve_verify.py evolve_verify.log "--quiet"
# 每周一(1) 07:00 周报（默认不推飞书 ✓）
register com.xingguo.fg-evolve-weekly 7 0 1 evolve_weekly.py evolve_weekly.log

echo "[OK] 两个作业已注册。手动触发："
echo "  launchctl kickstart -k $DOMAIN/com.xingguo.fg-evolve-verify"
echo "  launchctl kickstart -k $DOMAIN/com.xingguo.fg-evolve-weekly"
