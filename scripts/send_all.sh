#!/usr/bin/env bash
# 后台批量发送 + 自动重试（2026-10-26 用户选方案 A）
#
# 为什么需要：`send_pkg.py` 本来就能一次发全部片，但我一直前台跑，
# 本机 hook 5 秒就杀命令，`--limit 2` 几乎必死，只剩第一片成功，
# 10 片的包要 11 轮、约 20 分钟（实测）。
#
# 用法（后台启动，立即返回）：
#     nohup bash scripts/send_all.sh <包名> [最大轮数] > /tmp/send_<包名>.log 2>&1 &
#     cat dist/feishu/text/<包名>.done        # OK 已发 N/N  或  FAIL 缺片 [...]
#
# 环境变量 PY 可覆盖解释器（Windows 用 `PY="py -3.10"`，Mac 默认 python3）。
set -u
cd "$(dirname "$0")/.." || exit 1

PKG="${1:-}"
MAX_ROUNDS="${2:-8}"
[ -z "$PKG" ] && { echo "用法: bash scripts/send_all.sh <包名> [最大轮数]"; exit 2; }

export PYTHONIOENCODING=utf-8
PY="${PY:-python3}"
TXT="dist/feishu/text"
DONE="$TXT/$PKG.done"

rm -f "$DONE"
TOTAL=$(ls "$TXT/$PKG"-t*.txt 2>/dev/null | wc -l | tr -d ' ')
echo "[send_all] $PKG: $TOTAL 片, 最多 $MAX_ROUNDS 轮"

for round in $(seq 1 "$MAX_ROUNDS"); do
    echo "[send_all] === round $round ==="
    # 不带 start/limit 即发送全部片
    # 🔴 **必须加 timeout** ✗（2026-10-26 实测：`bsk` 卡住时进程**永久不退出** ✗
    # ⇒ 整个后台脚本卡死在第 1 轮 ✗）⇒ 单轮最多 180 秒 ✓
    timeout 180 $PY scripts/send_pkg.py "$PKG"
    rc=$?
    if [ "$rc" = "124" ]; then
        echo "[send_all] SEND TIMEOUT -> restart bsk session"
        pkill -f "send_pkg.py" 2>/dev/null
        bsk session start >/dev/null 2>&1
    elif [ "$rc" != "0" ]; then
        echo "[send_all] rc=$rc (continue)"
    fi

    STATUS=$($PY scripts/feishu_send.py --sent-status "$PKG" 2>&1 | head -1)
    echo "[send_all] $STATUS"

    if echo "$STATUS" | grep -q "缺片 \*\*无\*\*"; then
        echo "OK 已发 $TOTAL/$TOTAL" > "$DONE"
        echo "[send_all] ALL SENT"
        exit 0
    fi

    # 台账完全没有记录：可能是 bsk 会话死了，重启
    if echo "$STATUS" | grep -q "无记录"; then
        echo "[send_all] no ledger -> restart bsk session"
        bsk session start >/dev/null 2>&1
    fi
    sleep 2
done

MISSING=$($PY scripts/feishu_send.py --sent-status "$PKG" 2>&1 | head -1)
echo "FAIL $MISSING" > "$DONE"
echo "[send_all] INCOMPLETE after $MAX_ROUNDS rounds: $MISSING"
exit 1
