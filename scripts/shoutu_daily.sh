#!/usr/bin/env bash
# ==========================================================================
# Shoutu (fear/greed index) daily fetch -- macOS / Linux port of shoutu_daily.cmd
#
# Called by the launchd job (see install_shoutu_task.sh); can also be run by
# hand -- but see the WARNING below.
#
# Log: logs/shoutu_daily.log (appended)
#
# Why this wrapper exists instead of pointing launchd at python directly:
#   1 launchd does NOT set a working directory -- must cd explicitly,
#     otherwise relative paths (Data/raw/...) resolve to the wrong place.
#   2 Output must be redirected -- otherwise the failure leaves no trace.
#
# NO BROWSER REQUIRED (2026-09-23): this runs the partner-API path
# (scripts/fetch_shoutu_api.py) -- plain HTTPS, no bsk, no Chrome extension.
# That removes the "Chrome not running after wake" failure mode which the
# earlier bsk-based version had to guard against by launching Chrome and
# polling up to 60s. It also covers AXTX/CRCG, which are absent from the
# page's 11 category tables -- the Windows .cmd now covers them too
# (2026-09-24, via the #/stock_scan per-symbol query), so both platforms
# agree on the symbol set. The Mac path is still preferred HERE because it
# needs no browser at all.
#
# Differences from the Windows .cmd version:
#   - PYTHONUTF8=1 is NOT needed (macOS defaults to UTF-8)
#   - the ASCII-only rule does NOT apply (there is no GBK code page here)
#   - uses a venv interpreter instead of a hard-coded absolute path
#   - uses the API path; the .cmd still uses the bsk browser path
#
# WARNING -- do NOT run this by hand except to verify the install.
# The index updates continuously, and append_records OVERWRITES the row for
# the current date. Any manual run replaces the agreed 06:30 snapshot.
# See docs/trading-discipline.md section 14.5.
# ==========================================================================
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/shoutu_daily.log"
mkdir -p "$LOG_DIR"

stamp() { date +%Y-%m-%dT%H:%M:%S%z; }

# ---------------------------------------------------------------- 解释器
# 优先 venv；三个候选名与 .gitignore 里的 venv/ .venv/ env/ 一致。
PY=""
for cand in "$REPO/.venv/bin/python" "$REPO/venv/bin/python" "$REPO/env/bin/python"; do
    if [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    PY="$(command -v python3 2>/dev/null || true)"
    if [ -n "$PY" ]; then
        {
            echo "警告：未找到 .venv/bin/python，回退到 $PY"
            echo "      该解释器的 pandas/numpy 版本可能与 requirements.txt 不符，"
            echo "      会影响 pipeline 的数值可复现性。建议先建：python3 -m venv .venv"
        } >> "$LOG"
    fi
fi
if [ -z "$PY" ]; then
    echo "===== $(stamp) FATAL exit=127: 未找到 python3，也没找到 .venv/bin/python" >> "$LOG"
    exit 127
fi

{
    echo
    echo "===== start $(stamp) ====="
    echo "repo:   $REPO"
    echo "python: $PY"
} >> "$LOG"

# ---------------------------------------------------------------- 抓取（API 通道）
# 不需要浏览器。密钥经 shoutu.load_token() 读取（环境变量 SHOUTU_TOKEN 优先，
# 其次 Data/shoutu_token）。任一标的失败即非零退出并写明是哪个标的。
"$PY" scripts/fetch_shoutu_api.py >> "$LOG" 2>&1
RC=$?

# ---------------------------------------------------------------- 抓取（历史通道，**可选**）
# A2（2026-09-28）：`shoutu_history.csv` 是**生产信号源**（`run_portfolio_v2` 唯一
# 允许的源）。Windows 的 `.cmd` 第 98 行已经跑它；**Mac 这边此前漏了** ⇒ 信号
# **静默断更**，而且要等到 `SHOUTU_SIGNAL_MAX_LAG_DAYS`（3 个交易日）后才以
# **抛错**的形式暴露（默认关 ⇒ 现状生产不受影响，但能力在 Mac 上是断的）。
#
# ⚠️ **必须可选**：`fetch_shoutu_history.py` 走的是 `bsk` + Chrome 扩展
# （旁观页面自身的登录会话），而 **`bsk` 在 macOS 未实测**
# （docs/trading-discipline.md §14.5 自称「唯一阻塞项」）。所以：
#   1. 先探测 `bsk` 是否在 PATH 上；不在 ⇒ 跳过并记一行日志（**不算失败**）。
#   2. 在也不代表能连上扩展（那要真机验证）⇒ 它的失败**不改变 RC** ——
#      任务成败仍由主路径 `fetch_shoutu_api.py` 决定（同 `.cmd` 的 RC2 约定）。
#
# ⚠️ 时机：06:30 北京 = ET 前一日 18:30/19:30，**已收盘** ⇒ 不会写入
# 「未完成的最后一行」（§10.2 的教训：收盘前抓的那 6 行后来被服务端修正）。
if command -v bsk >/dev/null 2>&1; then
    "$PY" scripts/fetch_shoutu_history.py >> "$LOG" 2>&1
    RC2=$?
    echo "===== shoutu_history exit=$RC2 =====" >> "$LOG"
else
    echo "===== shoutu_history SKIPPED (no bsk on PATH) =====" >> "$LOG"
fi

# ---------------------------------------------------------------- 抓取（行情，**可选**）
# 2026-09-29 补（§12.28③）：`prices.csv` 此前**没有任何定时任务**在更新 ——
# 唯一调用方是 `scripts/bootstrap_data.py`（一次性数据重建）⇒ 生产信号日会**卡住不动**
# （实测 2026-09-29：守猪待兔是当天的，行情却停在 09-25）。
#
# ⚠️ **不改 RC** —— 任务成败仍由主路径 `fetch_shoutu_api.py` 决定
#    （同上面 history 块的「不改 RC」约定）。
# ⚠️ 数据源有请求前节流，24 个标的约 1~3 分钟，属正常等待。
# ⚠️ **无硬超时上界**（24 标的 × 重试 × 节流，最坏可十几分钟）—— 挂起的发现方式：
#    `logs/shoutu_daily.log` 里只有 `===== start` 而没有对应的 `===== end`。
"$PY" -c "from fg_system.data import fetch; _, a = fetch.update_prices(); print('prices.csv 新增 %d 行' % sum(a.values()))" >> "$LOG" 2>&1
RC3=$?
echo "===== prices exit=$RC3 =====" >> "$LOG"
if [ "$RC3" -ne 0 ]; then
    echo "===== prices FAILED rc=$RC3 (see traceback above) =====" >> "$LOG"
fi

echo "===== end $(stamp) exit=$RC =====" >> "$LOG"
exit $RC
