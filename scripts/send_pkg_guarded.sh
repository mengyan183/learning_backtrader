#!/bin/bash
# 发飞书分片（带脱离失败自动降级）。
#
# 背景（2026-10-10 实测）：`cmd start` 脱离窗口**偶发**产出空日志（.bat 本身正常，
# 同步跑能出内容），表现为「4 分钟零字节、任务静默没发」。故加本守卫：
#   先试脱离 → 15s 内日志非空即视为成功 → 否则降级前台分批（分片幂等，可安全续发）。
#
# 用法：bash scripts/send_pkg_guarded.sh <包名> [每批片数=6]
set -u
cd "$(dirname "$0")/.."

PKG="${1:?用法: bash scripts/send_pkg_guarded.sh <包名> [每批片数]}"
BATCH="${2:-6}"
LOG="${TEMP:-/tmp}/send_${PKG}.log"

rm -f "$LOG"
cmd //c start "" "scripts\\send_pkg.bat" "$PKG" >/dev/null 2>&1 || true

# 自检：feishu_send 会先打「共 N 条」，故日志非空 = 脱离成功
for _ in $(seq 1 15); do
    sleep 1
    [ -s "$LOG" ] && break
done

if [ -s "$LOG" ]; then
    echo "[脱离] 已启动，日志：$LOG"
    exit 0
fi

echo "[降级] 脱离窗口 15s 无输出 ⇒ 改前台分批（每批 $BATCH 片，分片幂等可续）"
TOTAL=$(ls "dist/feishu/text/${PKG}"-t*.txt 2>/dev/null | wc -l)
[ "$TOTAL" -gt 0 ] || { echo "❌ 没有 $PKG 的分片，先跑 scripts/pack_many.py"; exit 2; }

START=1
while [ "$START" -le "$TOTAL" ]; do
    echo "--- 批次 start=$START limit=$BATCH ---"
    py -3.10 scripts/send_pkg.py "$PKG" --start "$START" --limit "$BATCH" || echo "[警告] 该批非零退出"
    START=$((START + BATCH))
done
echo "[完成] $PKG 共 $TOTAL 片"
