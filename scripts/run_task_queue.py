# -*- coding: utf-8 -*-
"""Mac 侧任务队列执行器：读 `docs/task-queue/*.json` → 跑白名单 action → 写 result → 提交。

【为什么要有它 —— 2026-10-28 用户拍板】
看板上「清理堆积 / 同步运行副本」这类**一次性任务**不该各占一个按钮 ✗ ——
每下发一次任务就新增一个按钮，页面必然失控 ✗，而且点完没有执行历史 ✗。
⇒ 改成「任务下发」：

    Windows  写 docs/task-queue/<id>.json（status=pending）→ 飞书分片
    Mac      本脚本扫到 pending → 执行白名单 action → 写 <id>.result.json
             → git add/commit/push（docs/ 在白名单内 ✓）
    Windows  git fetch → 看板读 result 显示任务历史 ✓

🔴 白名单是 **action 名**，不是命令字符串 ✗ —— 后者等于把 RCE 开在飞书群里
   （MT-49 那类洞：任何能给飞书发消息的人都能在 Mac 上执行任意命令）。
   新增动作必须改本文件的 ACTIONS 并过 code review ✓。

用法（Mac）：
    .venv/bin/python scripts/run_task_queue.py            # 跑一次（launchd 每 10s 调）
    .venv/bin/python scripts/run_task_queue.py --no-commit  # 只执行不提交（调试）
"""
import argparse
import glob
import json
import contextlib
import os
# 🔴 2026-11-05：`probe_url` 用 `re.findall` 提取 URL/百分比 ✗
#    而模块顶部**一直没导入 `re`** ✗
#    ⇒ 三个 `probe_url` 任务全报 `NameError: name 're' is not defined` ✗
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "docs", "task-queue")

#: launchd 定时器（本脚本每 10s 被调一次）—— 看板可一键安装 ✓
LABEL = "com.xingguo.fg-task-queue"
PLIST_SRC = os.path.join(ROOT, "scripts", LABEL + ".plist")
PLIST_DST = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                         LABEL + ".plist")


def agent_status():
    """定时器是否已安装 / 已加载（看板据此决定要不要显示安装按钮）。"""
    installed = os.path.isfile(PLIST_DST)
    loaded = False
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True,
                           text=True, timeout=15)
        loaded = LABEL in (r.stdout or "")
    except (subprocess.SubprocessError, OSError):
        pass
    return {"installed": installed, "loaded": loaded, "label": LABEL}


def install_agent():
    """把 plist 装进 `~/Library/LaunchAgents` 并 bootstrap（幂等，重复点会先 bootout）。

    🔴 为什么可以在页面上做：看板服务本身就跑在 Mac 本地、以用户身份运行 ✓，
    有写 `~/Library/LaunchAgents` 和执行 `launchctl` 的权限 ✓。
    安全边界：源是仓库里的固定 plist、目标是固定的 LaunchAgents 路径、无用户输入 ✓。
    """
    if sys.platform != "darwin":
        return {"ok": False, "reason": "只有 macOS 支持 launchd（当前 %s）" % sys.platform}
    if not os.path.isfile(PLIST_SRC):
        return {"ok": False, "reason": "仓库里没有 plist：%s" % PLIST_SRC}
    try:
        os.makedirs(os.path.dirname(PLIST_DST), exist_ok=True)
        shutil.copy2(PLIST_SRC, PLIST_DST)
    except OSError as exc:
        return {"ok": False, "reason": "拷贝 plist 失败：%s" % exc}

    dom = "gui/%d" % os.getuid()
    try:
        # 先卸再装（幂等）：未加载时 bootout 会报错，忽略即可 ✓
        subprocess.run(["launchctl", "bootout", dom + "/" + LABEL],
                       capture_output=True, timeout=30)
        r = subprocess.run(["launchctl", "bootstrap", dom, PLIST_DST],
                           capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "launchctl 执行失败：%s" % exc}
    st = agent_status()
    out = {"ok": bool(st["loaded"]) or r.returncode == 0,
           "stdout": (r.stdout or "")[-300:], "stderr": (r.stderr or "")[-300:]}
    out.update(st)
    return out

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _act_cleanup_backlog(params):
    """把插件层 30 分钟前的历史文件挪进 archive（见 sync_health.archive_backlog）。"""
    from fg_system.dashboard import sync_health
    r = sync_health.archive_backlog()
    # 「没有够老的文件」= **成功**（无事可做）✓；「目录不存在」才是失败 ✗
    ok = bool(r.get("moved")) or "没有超过" in str(r.get("reason") or "")
    return dict(r, ok=ok)


def _act_weekly_review(params):
    """**周度复盘**（在 Mac 上跑 ✓ 2026-11-03 用户裁定）。

    🔴 为什么必须在 Mac：
       `Data/raw/*.csv` 在 Windows 侧只是**旧快照** ✗
       （实测停在 2026-10-12 ✗ 而 Mac 上是新的 ✗）
       ⇒ 在 Windows 跑会得出「数据断流」的假警报 ✗

    参数：`days`（回顾最近 N 份简报，默认 7）✓
    """
    days = int(params.get("days") or 7)
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "weekly_review.py"),
           "--days", str(days)]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超过 600 秒"}
    return {"ok": r.returncode == 0, "days": days,
            "note": "⚠️ 样本很小 ✗ 单周胜率不能当因子有效性证据 ✓",
            "stdout": (r.stdout or "")[-4000:],
            "stderr": (r.stderr or "")[-400:]}


def _act_archive_briefs(params):
    """**立即归档简报并自动提交** ✓（2026-11-03 用户裁定）。

    🔴 为什么需要：Mac 端堆了 10+ 个未追踪的
       `Data/briefs/archive/2026-10/invest_brief_*.md` ✗
       （`archive_briefs.py` 原来只写文件不提交 ✗）
       2026-11-03 已加自动提交 ✓ 但 Mac 端要先拉代码 ✓
       ⇒ 拉完用本动作**立即清一次存量** ✓

    参数：`keep`（保留最近 N 天，默认 7）✓
    """
    keep = int(params.get("keep") or 7)
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "archive_briefs.py"),
           "--keep", str(keep)]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超过 600 秒"}
    return {"ok": r.returncode == 0, "keep": keep,
            "note": "归档后会自动 git commit ✓（只 add Data/briefs/ 路径 ✗）",
            "stdout": (r.stdout or "")[-2000:],
            "stderr": (r.stderr or "")[-400:]}


def _act_diag_daily_log(params):
    """**查每日链日志里每一步的 rc** ✓（2026-11-03 排查 `fetch_*` 停更）。

    【为什么需要】
      用户告警：`sentiment`/`putcall`/`fedwatch`/`kalshi_fed`/`funding_rate`/
      `shoutu_fng`/`news_sentiment`/`stablecoin_usage`/`fred_dff` **全停更 20-26 天** ✗
      但日志尾部显示「简报成功 / 漂移监控成功 / 稳定币成功」✗ ⇒ **矛盾** ✗
      ⇒ 链是 `;` 串联 ✗ **某步失败不影响后面** ✗
      ⇒ 必须看**每一行 `[guard]` 的 rc** 才能定位 ✓

    【查什么】
      ① `/tmp/fg_daily.log` 里所有 `[guard] ... rc=` 行（最近 N 条）✓
      ② 非 0 的单独列出 ✓
      ③ 日志里最后的「日期」—— 判断日志是不是**今天的** ✗
         （如果日志是旧的 ✗ 那「简报成功」也是旧的 ✗ 就解释了矛盾 ✓）

    参数：`tail`（默认 400 行）✓
    """
    import re as _re

    n = int(params.get("tail") or 400)
    log = params.get("log") or "/tmp/fg_daily.log"
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:                # noqa: BLE001
        return {"ok": False, "error": "读不到 %s：%s" % (log, exc)}

    tail = lines[-n:]
    guards = [ln.rstrip() for ln in tail if "[guard]" in ln]
    fails = [g for g in guards if "rc=0" not in g]

    # 🔴 2026-11-04 用户要求：**还要抓 traceback** ✗
    #    因为 `backfill_stockanalysis.py` 里**只有 `return 0`** ✗
    #    它的 `rc=1` 来自**未捕获异常** ✗ ⇒ 日志里有完整 traceback ✓
    #    而原来只 grep `[guard]` ✗ 看不到 ✗
    traces = []
    for i, ln in enumerate(tail):
        if "Traceback (most recent call last)" in ln:
            # 抓后续 25 行 ✓（含异常类型和消息 ✓）
            traces.append("\n".join(x.rstrip() for x in tail[i:i + 25]))
    # 单独抓「Error / Exception」行 ✓（有些脚本不打印 traceback ✗）
    errs = [ln.rstrip() for ln in tail
            if ("Error:" in ln or "Exception:" in ln
                or "❌" in ln or "[ERROR]" in ln) and "[guard]" not in ln]
    # 日志里的日期（找 `MM-DD HH:MM:SS` 或 `YYYY-MM-DD`）
    dates = []
    for ln in tail:
        m = _re.search(r"\b(\d{4}-\d{2}-\d{2})\b", ln) or \
            _re.search(r"\b(\d{2}-\d{2} \d{2}:\d{2}:\d{2})\b", ln)
        if m:
            dates.append(m.group(1))

    return {"ok": True, "log": log,
            "total_lines": len(lines), "tail_lines": len(tail),
            "guard_count": len(guards), "fail_count": len(fails),
            "log_first_date": dates[0] if dates else "?",
            "log_last_date": dates[-1] if dates else "?",
            "note": "⚠️ 链是 `;` 串联 ⇒ **某步失败不影响后面** ✗ "
                    "所以「简报成功」不代表前面 fetch 成功 ✗",
            "fails": fails[-40:],
            "guards_tail": guards[-40:],
            "tracebacks": traces[-3:],
            "error_lines": errs[-20:]}


def _act_audit_data(params):
    """**数据文件审计** ✓（谁读谁写 ⇒ 在用/孤儿/死文件）。

    🔴 必须在 **Mac** 跑 ✗ —— Windows 的 `Data/raw/` 只是旧快照 ✗
       （2026-11-03 用户澄清）
    """
    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "audit_data_files.py")]
    js = params.get("json") or "evolution/experiments/factor-adoption/data-audit.json"
    cmd += ["--json", str(js)]
    try:
        # 🔴 2026-11-03：`text=True` 在 Windows 用 **GBK** 解码 ✗
        #    而审计输出含 `✓`/`✗` ⇒ `UnicodeDecodeError` ✗（Mac 上无此问题 ✓）
        #    ⇒ 显式指定 utf-8 + replace ✓ 两边都稳 ✓
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超过 900 秒"}

    # 🔴 2026-11-03：**只回汇总 + 分类文件名** ✗ —— 全表 39 行会撑爆
    #    `_write_result` 的 8000 上限 ✗ 且 JSON 被截断就没法解析 ✗
    #    ⇒ 明细落盘（`--json`）✓ 返回值只带「能行动的结论」✓
    summary, groups = {}, {"used": [], "read_only": [], "orphan": [], "dead": []}
    try:
        import json as _json
        ap = os.path.join(ROOT, str(js))
        with open(ap, "r", encoding="utf-8") as f:
            data = _json.load(f)
        for name, rec in (data.get("audit") or {}).items():
            w, rd = len(rec.get("writers") or []), len(rec.get("readers") or [])
            if w and rd:
                groups["used"].append(name)
            elif rd:
                groups["read_only"].append(name)
            elif w:
                groups["orphan"].append(name)
            else:
                groups["dead"].append(name)
        summary = {k: len(v) for k, v in groups.items()}
    except Exception as exc:                # noqa: BLE001
        summary = {"error": str(exc)[:120]}

    return {"ok": r.returncode == 0,
            "json": js,
            "summary": summary,
            "groups": groups,
            # 🔴 2026-11-03 踩坑：`"~10% 误判 ... %s" % js` ✗
            #    第一个 `%` 后面跟的是中文「误」✗ ⇒
            #    `ValueError: unsupported format character '误' (0x8bef)` ✗
            #    ⇒ 任务直接 `failed` ✗ 整个动作白跑 ✗
            #    ⇒ 改用 `.format()` ✓ 不受 `%` 影响 ✓
            "note": ("⚠️ 审计有 ~10% 误判 ✗（动态拼名/消费者在别处 ✗）"
                     " ⇒ 删文件前务必人工复核 ✓；明细见 `{f}`").format(f=js),
            "stdout": (r.stdout or "")[-1200:],
            "stderr": (r.stderr or "")[-400:]}


def _act_prune_dead_data(params):
    """**删死文件** ✓（2026-11-03 用户裁定「死文件要删」）。

    安全措施：
      ① 默认 **dry-run** ✓ —— 必须显式 `apply=1` 才真删 ✗
      ② 真删前**备份**到 `dist/pruned/` ✓
      ③ 只删 `Data/raw/` 下**明确列出**的文件 ✓ 不递归扫 ✗
      ④ `Data/raw/` 已 gitignore ⇒ **git 不会有任何改动** ✓

    参数：
      - `apply`：`1` = 真删 ✓（默认只看 ✗）
      - `restore`：`1` = **全部从 `dist/pruned/` 恢复** ✓
        （2026-11-03 误删事故后加的 ✗）
      - `restore_files`：逗号分隔的**指定文件名** ✓ 优先于 `restore`
    """
    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "prune_dead_data.py")]
    rf = str(params.get("restore_files") or "").strip()
    if rf:
        cmd.append("--restore")
        cmd += [x.strip() for x in rf.split(",") if x.strip()]
    elif str(params.get("restore") or "").lower() in ("1", "true", "yes"):
        cmd.append("--restore")
    elif str(params.get("apply") or "").lower() in ("1", "true", "yes"):
        cmd.append("--apply")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超过 600 秒"}
    return {"ok": r.returncode == 0,
            "applied": "--apply" in cmd,
            "note": "误删可从 `dist/pruned/` 拷回 ✓",
            "stdout": (r.stdout or "")[-5000:],
            "stderr": (r.stderr or "")[-400:]}


#: 🔴 `run_fetch_step` 的**脚本白名单** ✓（2026-11-03）
#: 为什么必须白名单：这个动作会**执行任意命令** ✗ 若不加限，
#: 一个拼错的任务 json 就能跑 `rm -rf` ✗
FETCH_SCRIPTS = (
    "fetch_sentiment.py", "fetch_putcall.py", "fetch_kalshi_fed.py",
    "fetch_fred.py", "fetch_fedwatch.py", "fetch_shoutu_api.py",
    "fetch_stablecoin_usage.py", "fetch_news.py", "fetch_trades_futu.py",
    # 🔴 2026-11-04：补 `shoutu_history.csv`（停在 10-14 ✗ 21 天）
    #    它是**服务端权威日值**（每只 ~600 天 ✗ 研究/回测用 ✗）
    #    ⚠️ **不在每日链里**（需会员 ✗ 至 2027-01-16）⇒ 只能手工/按需跑 ✓
    #    ⚠️ 缺口会**永久丢失** ✗（服务端只给最近 N 天 ✗）⇒ 该补 ✓
    "fetch_shoutu_history.py",
    # 🔴 2026-11-04：CME 改用 **bsk**（真实浏览器 ✗ headless 拿不到数据 ✗）
    # 🔴 2026-11-05：**最终方案** ✓ 富途 OpenD 官方接口 ✗ 不是爬虫 ✓
    #    市面调研结论：
    #      cme-fedwatch（PyPI）⇒ 已停维护 ✗
    #      fed-funds-target.json ⇒ 404 ✗
    #      curl_cffi/nodriver/FlareSolverr ⇒ 解决不了 iframe+Referer ✗
    #    富途 `get_fed_watch_target_rate()` ⇒ **官方** ✓ 零新增依赖 ✓
    "fetch_fedwatch_futu.py",
)


def _act_diagnose_symbols(params):
    """**查 `update_prices()` 为什么漏标的** ✓（2026-11-04 用户要求）。

    【背景】
      `config.FETCH_SYMBOLS` **39 个** ✗ 而 `prices.csv` 只有 **36 个** ✗
      长期缺失 11 个：
        DIA / EWY / ITB / KRE / TLT / VGK / XBI / XLE / XLK / XLU / XLV
      ⇒ 全是**主流 ETF** ✗ Nasdaq 不可能没有 ✗
      ⇒ 而 `fetch_symbol` **已有** `etf→stocks` 回退 + 3 轮退避重试 ✗
      ⇒ **所以问题在「增量逻辑」或「URL 参数」** ✗ 不在「标的不可得」✗

    【逐个标的查 4 件事】
      ① `prices.csv` 里有没有、行数、最新日期 ✓
      ② `missing_ranges(old, sym)` 返回什么 ✓ ← **最可疑**
      ③ 用它给的 `fromdate` 直接调 `fetch_symbol` 能否抓到 ✓
      ④ 抓不到时的**真实异常** ✓

    参数：`symbols`（逗号分隔 ✗ 默认 = FETCH_SYMBOLS 里 `prices.csv` 缺的那些 ✓）
    """
    import pandas as _pd

    want = str(params.get("symbols") or "").strip()
    path = os.path.join(ROOT, "Data", "raw", "prices.csv")
    old = _pd.DataFrame()
    if os.path.exists(path):
        old = _pd.read_csv(path, dtype={"symbol": str},
                           parse_dates=["date"])

    from fg_system import config as _cfg
    if want:
        syms = [x.strip() for x in want.split(",") if x.strip()]
    else:
        have = set(old["symbol"].unique()) if not old.empty else set()
        syms = [s for s in _cfg.FETCH_SYMBOLS if s not in have]

    from fg_system.data import fetch as _fetch

    out = {}
    for sym in syms:
        rec = {}
        sub = old[old["symbol"] == sym] if not old.empty else _pd.DataFrame()
        rec["in_csv"] = int(len(sub))
        if len(sub):
            rec["csv_last"] = str(sub["date"].max().date())
        # ② 增量逻辑怎么说 ✓
        try:
            start, end = _fetch.missing_ranges(old, sym)
            rec["missing_ranges"] = {
                "start": str(start.date()) if start is not None else None,
                "end": str(end.date()) if end is not None else None,
            }
            fromdate = (start.strftime("%Y-%m-%d")
                        if start is not None else "2010-01-01")
        except Exception as exc:            # noqa: BLE001
            rec["missing_ranges"] = {"error": str(exc)[:120]}
            fromdate = "2010-01-01"
        rec["fromdate_used"] = fromdate
        # ③④ 直接抓 ✓
        try:
            df = _fetch.fetch_symbol(sym, fromdate=fromdate)
            rec["fetch_ok"] = True
            rec["fetch_rows"] = int(len(df))
            if len(df):
                rec["fetch_range"] = "%s → %s" % (
                    df["date"].min().date(), df["date"].max().date())
        except Exception as exc:            # noqa: BLE001
            rec["fetch_ok"] = False
            rec["fetch_error"] = "%s: %s" % (type(exc).__name__,
                                             str(exc)[:200])
        out[sym] = rec

    ok_cnt = sum(1 for v in out.values() if v.get("fetch_ok"))
    return {"ok": True, "checked": len(out),
            "fetch_ok": ok_cnt, "fetch_fail": len(out) - ok_cnt,
            "symbols": out,
            "note": "⚠️ `fetch_ok=True` 但 `missing_ranges` 给了错日期 ⇒ "
                    "**增量逻辑是根因** ✗；"
                    "`fetch_ok=False` ⇒ 看 `fetch_error` ✓"}


def _find_bsk_bin():
    """**自动探测 `bsk` 路径** ✓（2026-11-05）。

    🔴 为什么不能直接用 `"bsk"` ✗：
       launchd 的 `PATH` **不含 `~/.local/bin`** ✗
       实测 `fetch_fedwatch_bsk.py` 在 Mac 上报
         `session_start rc=-1  **找不到 bsk** ✗`
       而 bsk 确实装着 ✓
    """
    env = os.environ.get("FG_BSK")
    if env and os.path.exists(env):
        return env
    import shutil
    w = shutil.which("bsk")
    if w:
        return w
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, ".local", "bin", "bsk"),
        "/opt/homebrew/bin/bsk",
        "/usr/local/bin/bsk",
        os.path.join(home, ".npm-global", "bin", "bsk"),
    ]
    import glob as _g
    cands += sorted(_g.glob(os.path.join(
        home, "Library", "Python", "*", "bin", "bsk")), reverse=True)
    for c in cands:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return "bsk"


BSK_BIN = _find_bsk_bin()


def _act_inspect_snapshots(params):
    """**核实持仓/账户快照的真实积累情况** ✓（2026-11-05）。

    🔴 为什么要查 ✗：
       `verify_hypotheses` 在 **Mac** 上跑，却报
         `[H-006] pending — Data/accounts.csv（本机仅 1 日快照）`
       而同一天 `sync_positions` 在 **Mac** 上跑，输出
         `已写入：accounts 54 行（新增 2）/ positions 162 行（新增 6）`
       ⇒ **两者矛盾** ✗
       可能：① `verify_hypotheses` 读的路径/判断有 bug ✗
             ② 它读的是「某列唯一值」而非行数 ✗
             ③ 文件里 `date` 列只有 1 个值（其余行 date 为 NaN ✗）

    ⇒ 直接把**行数 / date 唯一值 / 各列非空数**打出来 ✓ 一看就清楚 ✓
    """
    import pandas as _pd
    out = {"ok": True, "files": {}}
    for name in ("accounts", "positions"):
        p = os.path.join(ROOT, "Data", "%s.csv" % name)
        rec = {"path": os.path.relpath(p, ROOT)}
        if not os.path.exists(p):
            rec["exists"] = False
            out["files"][name] = rec
            continue
        rec["exists"] = True
        rec["size_kb"] = round(os.path.getsize(p) / 1024.0, 1)
        try:
            d = _pd.read_csv(p)
            rec["rows"] = int(len(d))
            rec["columns"] = list(d.columns)
            if "date" in d.columns:
                dd = d["date"].astype(str)
                uniq = sorted(dd.dropna().unique())
                rec["date_unique"] = len(uniq)
                rec["date_first"] = uniq[0] if uniq else None
                rec["date_last"] = uniq[-1] if uniq else None
                rec["date_null"] = int(dd.isna().sum())
                rec["date_samples"] = uniq[:3] + uniq[-3:] if len(uniq) > 6 else uniq
            # 每列非空数 ✓（看是不是大部分列都空 ✗）
            rec["nonnull"] = {c: int(d[c].notna().sum())
                              for c in d.columns[:12]}
        except Exception as exc:            # noqa: BLE001
            rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        out["files"][name] = rec
    # 判读 ✓
    a = out["files"].get("accounts") or {}
    p2 = out["files"].get("positions") or {}
    n = max(int(a.get("date_unique") or 0), int(p2.get("date_unique") or 0))
    out["verdict"] = ("✓ **有 %d 个不同日期** ⇒ 数据够 ✓ "
                      "那 `verify_hypotheses` 的判断有 bug ✗" % n
                      if n >= 2 else
                      "✗ **只有 %d 个日期** ⇒ 确实没积累 ✗" % n)
    return out


def _act_verify_hypotheses(params):
    """**跑 `verify_hypotheses.py` 推进假说验证** ✓（2026-11-05 用户要求）。

    🔴 为什么要推进 ✗：
       台账现状（`evolution/hypotheses.md` ✗ 共 85 条）：
         `verifying`  **3 条** —— H-006 / H-008 / H-009 ✗ **10-02 登记，一个月没推进**
         `open`       **15 条**
         `pending-revise` **1 条** —— H-085
       ⇒ 假说验证**停摆** ✗ 而 `verify_hypotheses.py` 就是执行器 ✓

    【脚本参数】
      `-H/--hypothesis H-006`（可重复 ✗ 不给则跑**全部 open** ✓）
      `--dry-run`（只算不写台账 ✗）
      `--out <path>`（结果另存 ✗）
      `--check-table`（校验台账列名 ✗）

    参数：
      - `hypotheses`：逗号分隔（默认空 ⇒ 全部 open ✓）
      - `dry_run`：`1` = 只算不写 ✓
    """
    hs = [x.strip() for x in str(params.get("hypotheses") or "").split(",")
          if x.strip()]
    dry = str(params.get("dry_run") or "").lower() in ("1", "true", "yes")

    # 🔴 2026-11-05：`write_notes=1` ⇒ **只写备注列** ✓（不跑假说 ✗）
    #    用户要求「备注列加等数据 x/y，且支持动态更新」✗
    #    实现放在 `verify_hypotheses.py --write-notes` ✓ 幂等 ✗
    notes = str(params.get("write_notes") or "").lower() in ("1", "true", "yes")

    cmd = [sys.executable, "scripts/verify_hypotheses.py"]
    for h in hs:
        cmd += ["-H", h]
    if notes:
        cmd.append("--write-notes")
    if dry:
        cmd.append("--dry-run")

    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800, cwd=ROOT)
    secs = round(time.time() - t0, 1)
    so = (r.stdout or "").strip()
    se = (r.stderr or "").strip()

    # 🔴 逐条摘出结论行 ✓（脚本会打 `H-xxx` 开头的结果 ✗）
    #    只留「有判定」的行 ✓ 去掉噪声 ✓
    hits = []
    for ln in so.splitlines():
        s = ln.strip()
        if re.match(r"^H-\d+", s) or re.search(
                r"(通过|不通过|样本不足|跳过|无法|已验证|证伪)", s):
            if s and s not in hits:
                hits.append(s[:200])

    out = {"ok": r.returncode == 0, "rc": r.returncode, "seconds": secs,
           "hypotheses": hs or "全部 open",
           "dry_run": dry,
           "stdout_len": len(so), "stderr_len": len(se),
           "verdict_lines": hits[:40],
           "stdout_tail": so[-2500:] if so else "",
           "stderr_tail": se[-800:] if se else ""}
    # 简单判读 ✓
    if r.returncode != 0:
        out["verdict"] = "✗ 脚本失败 ✗ 见 stderr_tail"
    elif not hits:
        out["verdict"] = ("⚠️ 跑完了但**没有判定行** ✗ "
                          "可能全部「样本不足」✗ 见 stdout_tail")
    else:
        n_ok = sum(1 for h in hits if "通过" in h and "不通过" not in h)
        n_bad = sum(1 for h in hits if "不通过" in h)
        n_skip = sum(1 for h in hits if "样本不足" in h or "跳过" in h)
        out["verdict"] = ("✓ 有 %d 条判定：通过 %d / 不通过 %d / 样本不足 %d"
                          % (len(hits), n_ok, n_bad, n_skip))
    return out


def _act_rerun_brief(params):
    """**重算 features 并生成简报** ✓（2026-11-05 用户要求「重新测试输出的简报」）。

    🔴 为什么不能只跑 `invest_research.py` ✗：
       简报读的是 `features.csv` ✗ 而它由 `pipeline.run(write=True)` 产出 ✗
       ⇒ `fedwatch.csv` 更新了 ✗ 但 `features.csv` **还是旧的** ✗
       ⇒ 必须**先重算 pipeline** ✓ 才能看到 `FED` 因子的变化 ✓

    【两步】
      ① `pipeline.run(write=True)` —— 重算六因子 ✓
      ② `invest_research.py --dry-run` —— 生成简报 ✓ **不推送飞书** ✓

    参数：
      - `skip_pipeline`：1 = 跳过第①步 ✗ 只看现有 features ✗
      - `push`：1 = **推飞书** ✓（默认 `--dry-run` 不推 ✗）
        🔴 2026-11-09 用户要求「把这份简报推飞书」⇒ 加此开关 ✓
    """
    skip = str(params.get("skip_pipeline") or "").lower() in ("1", "true", "yes")
    push = str(params.get("push") or "").lower() in ("1", "true", "yes")
    out = {"steps": {}}

    # ① pipeline ✓
    if not skip:
        t0 = time.time()
        # 🔴 2026-11-05：**必须显式加 sys.path** ✗
        #    实测报 `[warn] 有效敞口计算失败：No module named 'fg_system'` ✗
        #    因为 `python -c` 的 `sys.path[0]` 是 `""`（cwd ✗）
        #    而 `cwd=ROOT` 下 `fg_system` **应该能找到** ✗ 但被别的
        #    路径顺序干扰 ✗ ⇒ 显式 insert ✓
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.'); "
             "from fg_system import pipeline; pipeline.run(write=True)"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=900, cwd=ROOT)
        out["steps"]["pipeline"] = {
            "rc": r.returncode, "seconds": round(time.time() - t0, 1),
            "stdout": (r.stdout or "")[-800:],
            "stderr": (r.stderr or "")[-500:],
        }
        if r.returncode != 0:
            out["ok"] = False
            out["error"] = "pipeline 失败 ✗ 见 steps.pipeline.stderr"
            return out

    # ② 简报 ✓（`--dry-run` 不推送 ✓）
    t0 = time.time()
    cmd = [sys.executable, "scripts/invest_research.py"]
    if not push:
        cmd.append("--dry-run")        # 不加 --dry-run 才会推飞书 ✓
    r = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=1200, cwd=ROOT)
    # 🔴 2026-11-05 **关键**：`--dry-run` 的 **stdout 只有运行日志** ✗
    #    实测 stdout 只有 1083 字（`[warn]` + `简报已写入: ...` ✗）
    #    而**完整简报写到了 `Data/invest_brief_<日期>.md`** ✓
    #    ⇒ 必须**读那个 md 文件** ✗ 不能只取 stdout ✗
    brief = ""
    md_path = ""
    import glob as _g2
    cands = sorted(_g2.glob(os.path.join(ROOT, "Data", "invest_brief_*.md")),
                   key=os.path.getmtime, reverse=True)
    if cands:
        md_path = cands[0]
        try:
            brief = open(md_path, encoding="utf-8",
                         errors="replace").read()
        except OSError:
            brief = ""
    if not brief:
        brief = (r.stdout or "").strip()

    out["steps"]["brief"] = {
        "rc": r.returncode, "seconds": round(time.time() - t0, 1),
        "len": len(brief), "md": os.path.relpath(md_path, ROOT) if md_path else "",
        "stdout_len": len(r.stdout or ""),
        "stderr": (r.stderr or "")[-500:],
    }
    out["ok"] = r.returncode == 0
    out["push"] = push
    m3 = re.search(r"飞书富文本推送[:：]\s*(.+)", r.stdout or "")
    out["push_result"] = m3.group(1).strip()[:120] if m3 else "(未见推送结果)"
    out["brief"] = brief[-12000:] if brief else "(空 ✗)"
    # 关键：把「美联储动态」那一段单独摘出来 ✓（用户最关心 ✗）
    m = re.search(r"美联储动态(.{0,1500})", brief, re.S)
    out["fed_section"] = (m.group(0)[:1500] if m else "(没找到美联储动态段 ✗)")
    # 顺带报数据日 ✓
    m2 = re.search(r"数据日[:：]\s*(\d{4}-\d{2}-\d{2})", brief)
    out["data_date"] = (m2.group(1) if m2 else "?")
    return out


def _act_test_futu_fed(params):
    """**验证富途 OpenD 的 `get_fed_watch_target_rate`** ✓（2026-11-05）。

    🔴 为什么这是 CME 的最优替代 ✗：
       搜到 moomoo/futu 开放平台有**官方接口** ✓：
         `OpenQuoteContext.get_fed_watch_target_rate()`
       文档原文：「获取 CME FedWatch 工具的联邦基金目标利率概率预测数据。
                 数据来源于 CME 联邦基金期货定价。」
       返回字段：
         `meeting_date`  str    FOMC 会议日期 "yyyy-MM-dd"
         `target_range`  str    目标利率区间，如 "4.25% ~ 4.50%"
         `probability`   float  市场预期概率(%)，如 92.13

    ✅ 为什么比爬虫好 ✗：
       - **官方接口** ✓ 不会因为 CME 改版而失效 ✓
       - **项目已在用 futu** ✓（`fetch_trades_futu.py` / `sync_positions.py` ✗）
         ⇒ **零新增依赖** ✓ 零新增凭证 ✓
       - **不需要浏览器** ✗ 不需要代理 ✗ 不需要 cookie ✗

    ⚠️ 前提：**OpenD 必须在跑** ✗（`127.0.0.1:11111` ✗）

    参数：`host`（默认 127.0.0.1 ✗）、`port`（默认 11111 ✗）、`write`（1=写盘 ✗）
    """
    host = str(params.get("host") or "127.0.0.1")
    port = int(params.get("port") or 11111)
    write = str(params.get("write") or "").lower() in ("1", "true", "yes")

    out = {"host": host, "port": port}
    try:
        import futu
        out["futu_version"] = getattr(futu, "__version__", "?")
        from futu import OpenQuoteContext
    except ImportError as exc:
        return {"ok": False, "error": "**没装 futu** ✗：%s" % str(exc)[:120]}

    has = hasattr(OpenQuoteContext, "get_fed_watch_target_rate")
    out["has_method"] = has
    if not has:
        out["fed_methods"] = [m for m in dir(OpenQuoteContext)
                              if "fed" in m.lower()]
        out["ok"] = False
        out["error"] = ("**这个 futu 版本没有 `get_fed_watch_target_rate`** ✗ "
                        "⇒ 需要升级 `pip install -U futu-api` ✗")
        return out

    ctx = None
    try:
        ctx = OpenQuoteContext(host=host, port=port)
        ret, data = ctx.get_fed_watch_target_rate()
        out["ret"] = str(ret)[:80]
        # 🔴 2026-11-05 **关键修复**：`futu.RET_OK` **就是整数 0** ✗
        #    我原来写 `"RET_OK" in str(ret)` ✗
        #    ⇒ `str(0)` == `"0"` ✗ **永远不含 "RET_OK"** ✗
        #    ⇒ 接口明明成功了 ✗ 却被判成失败 ✗ 还提前 return 丢掉了 data ✗
        #    实测：`ret=0` `has_method=True` ⇒ **接口是通的** ✓
        #    ⇒ 判据改成 `ret == 0` ✓（同时兼容字符串形式 ✗）
        ok = (ret == 0) or ("RET_OK" in str(ret))
        out["ok"] = ok
        if not ok:
            out["error"] = "接口返回非 OK：%s ✗" % str(ret)[:200]
            # 即使失败也把 data 打出来 ✓（可能是错误消息 ✗ 有价值 ✗）
            out["raw"] = str(data)[:600]
            return out
        try:
            out["columns"] = list(data.columns)
            out["rows"] = int(len(data))
            out["head"] = data.head(20).to_dict(orient="records")
        except Exception:                   # noqa: BLE001
            out["raw"] = str(data)[:1500]
            return out

        # 可选写盘 ✓（统一成 `fedwatch.csv` 的列名 ✗ 让 `fed.py` 直接消费 ✓）
        if write and len(data):
            import pandas as _pd
            d = data.copy()
            # 取**最近一次会议**的分布 ✓ 聚合成 ease/hold/hike ✓
            # ⚠️ 这里只做**原始落盘** ✓ 聚合逻辑等看清数据结构再写 ✗
            p = os.path.join(ROOT, "Data", "raw", "futu_fedwatch_raw.csv")
            d.to_csv(p, index=False, encoding="utf-8")
            out["written"] = os.path.relpath(p, ROOT)
    except Exception as exc:                # noqa: BLE001
        out["ok"] = False
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        out["hint"] = ("⚠️ 若是连接失败 ⇒ **OpenD 没开** ✗ "
                       "（`~/futu_OpenD/OpenD` 或 GUI 版 ✗）")
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:               # noqa: BLE001
                pass
    return out


def _act_probe_url(params):
    """**用 bsk 探测任意 URL** ✓（2026-11-05 用户要求分析 `cmegroup.cn`）。

    🔴 为什么需要 ✗：
       `cmegroup.cn/fed-watch/` 在 **Windows 完全不可达** ✗：
         DNS 解析 OK（`119.23.206.245` ✗ 阿里云 ✗）
         但 `ping` 100% 丢包 ✗ 80/443 全超时 ✗ `web_fetch` 也超时 ✗
       ⇒ 只能让 **Mac** 去试（网络环境不同 ✗）

    【测什么】
      ① `bsk navigate` 能否打开 ✓
      ② `get-html` 长度 + 有无 `<table>` + 有无百分比 ✓
      ③ `observe` 语义视图前 500 字 ✓
      ④ `network` 里的业务 API（排除字体/脚本/样式 ✗）

    参数：`url`（必填 ✗）、`wait_ms`（默认 15000 ✗）
    """
    url = str(params.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "必须给 `url` ✗"}
    wait_ms = int(params.get("wait_ms") or 15000)

    def _run(args, timeout=120):
        """跑一条 `bsk` 命令 ✓（本文件的本地 helper ✗）。"""
        try:
            r = subprocess.run([BSK_BIN] + list(args), capture_output=True,
                               text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
            return r.returncode, (r.stdout or ""), (r.stderr or "")
        except FileNotFoundError:
            return -1, "", "**找不到 bsk** ✗（BSK_BIN=%s ✗）" % BSK_BIN
        except subprocess.TimeoutExpired:
            return -2, "", "bsk 超时（%ds ✗）" % timeout

    rc, o, e = _run(["session", "start"], timeout=60)
    sid = (o or "").strip().splitlines()[-1].strip() if o else ""
    if rc != 0 or not sid:
        return {"ok": False, "error": "session start 失败 ✗",
                "stderr": e[-300:]}
    out = {"url": url, "steps": {}}
    try:
        rc, o, e = _run(["navigate", url, "--session", sid,
                         "--timeout", "90s"], timeout=180)
        out["steps"]["navigate"] = {"rc": rc, "out": o[-250:], "err": e[-250:]}
        if rc != 0:
            return out
        _run(["wait-ms", str(wait_ms)], timeout=90)

        rc, html, e = _run(["get-html", "--session", sid], timeout=120)
        pcts = re.findall(r"\d{1,3}\.\d\s*%", html or "")
        out["steps"]["html"] = {
            "rc": rc, "len": len(html or ""),
            "has_table_tag": "<table" in (html or "").lower(),
            "pct_count": len(pcts), "pct_samples": pcts[:15],
            "has_iframe": "<iframe" in (html or "").lower(),
        }

        rc, o, e = _run(["observe", "--session", sid], timeout=120)
        out["steps"]["observe"] = {
            "rc": rc, "lines": len((o or "").splitlines()),
            "data_hits": sum(o.count(k) for k in ("%", "ZQ", "利率", "概率")),
            "head": (o or "")[:600],
        }

        rc, o, e = _run(["network", "--session", sid, "--json",
                         "--limit", "200"], timeout=120)
        urls = re.findall(r"https?://[^\s\"'<>\\]+", o or "")
        api = [u for u in urls if any(k in u.lower() for k in
                                      ("cme", "fed", "api/", "json", "watch"))]
        out["steps"]["network"] = {
            "rc": rc, "total_urls": len(urls),
            "api_urls": sorted(set(api))[:20],
        }
    finally:
        _run(["session", "stop", sid], timeout=60)

    h = out["steps"].get("html") or {}
    out["ok"] = True
    out["verdict"] = (
        "✓ **有数据特征**（%d 个百分比 ✗ 有 table=%s ✗）⇒ 值得深挖 ✓"
        % (h.get("pct_count", 0), h.get("has_table_tag"))
        if h.get("pct_count", 0) > 0 else
        "✗ **页面打开了但零个百分比** ✗（HTML %d 字节 ✗）"
        % h.get("len", 0))
    return out


def _act_analyze_png(params):
    """**分析截图的「文字密度」** ✓（2026-11-05 用户要求「交给 Mac 的 AI 分析」）。

    🔴 为什么用密度而不是 OCR ✗：
       Mac 上**不一定有 tesseract** ✗ 而 PIL **一定有**（pandas 的依赖链里 ✗）
       而「有没有数据表格」这个判断 ✗ **密度就够了** ✓：
         - 数据表格 = **大量密集小字** ✗ ⇒ 暗像素比例高 ✓
         - 只有框架/图片 = **大片空白** ✗ ⇒ 暗像素比例低 ✓

    【怎么判】
      ① 全图暗像素比例（`< 2%` ⇒ 基本是空白 ✗）
      ② 切成 4×4 网格，**每格的暗像素比例** ✓
         ⇒ 表格通常出现在**中下部**，且**连续几格都很高** ✓
      ③ **横向连续高密度行数**（表格是横向排列的 ✗）
      ④ 与「典型表格页」的经验阈值比对 ✓

    参数：`path`（默认 `dist/cme.png`）、`grid`（默认 4）
    """
    path = str(params.get("path") or "dist/cme.png")
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    grid = int(params.get("grid") or 4)
    if not os.path.exists(path):
        return {"ok": False, "error": "文件不存在：%s ✗" % path}

    try:
        from PIL import Image
    except ImportError:
        return {"ok": False,
                "error": "**没有 PIL** ✗ 装 `pip install pillow` ✗"}

    try:
        im = Image.open(path).convert("L")   # 灰度 ✓
    except Exception as exc:                # noqa: BLE001
        return {"ok": False, "error": "打开失败：%s" % str(exc)[:150]}

    w, h = im.size
    px = im.load()
    # 全图暗像素比例 ✓（阈值 128 ✗ 保守一点用 160 抓浅色字 ✓）
    dark = 0
    total = 0
    step = max(1, min(w, h) // 600)         # 抽样加速 ✓（大图别逐像素 ✗）
    for y in range(0, h, step):
        for x in range(0, w, step):
            if px[x, y] < 160:
                dark += 1
            total += 1
    ratio = (dark / total) if total else 0.0

    # 网格密度 ✓
    cells = []
    for gy in range(grid):
        row = []
        for gx in range(grid):
            x0, x1 = gx * w // grid, (gx + 1) * w // grid
            y0, y1 = gy * h // grid, (gy + 1) * h // grid
            d = t = 0
            for y in range(y0, y1, step):
                for x in range(x0, x1, step):
                    if px[x, y] < 160:
                        d += 1
                    t += 1
            row.append(round((d / t) if t else 0.0, 4))
        cells.append(row)

    # 判据 ✓
    max_cell = max((max(r) for r in cells), default=0.0)
    hot_rows = sum(1 for r in cells if max(r) > 0.08)
    verdict = (
        "✗ **全图几乎空白**（暗像素 %.2f%%）⇒ 页面没渲染出内容 ✗"
        % (ratio * 100) if ratio < 0.02 else
        "⚠️ **只有零散文字**（%.1f%%，最高格 %.1f%%）"
        "⇒ 像「导航+标题」✗ 不像数据表格 ✗"
        % (ratio * 100, max_cell * 100) if max_cell < 0.10 else
        "✓ **有密集文字区**（%.1f%%，最高格 %.1f%%，%d 行高密度）"
        "⇒ **可能有数据表格** ✓ 值得再看 ✓"
        % (ratio * 100, max_cell * 100, hot_rows))

    return {"ok": True, "path": path, "size_kb": round(
                os.path.getsize(path) / 1024.0, 1),
            "image": {"w": w, "h": h},
            "dark_ratio": round(ratio, 4),
            "grid": grid, "cells": cells,
            "max_cell": max_cell, "hot_rows": hot_rows,
            "verdict": verdict,
            "note": "⚠️ 密度只能判「有没有密集文字」✗ "
                    "不能判「是不是 FedWatch 数据」✗ "
                    "⇒ 若显示「有密集文字区」⇒ 需人工看图确认 ✓"}


def _act_restart_queue(params):
    """**重启任务队列** ✓（2026-11-05 用户要求）。

    🔴 为什么必须重启 ✗：
       `install_daily_plist` 只**拷贝 plist 文件** ✗ **不重启进程** ✗
       而任务队列是**常驻进程**（`state = running` ✗）
       ⇒ **新补的代理（`FG_LLM_PROXY` 等）不会生效** ✗
       ⇒ 实测：plist 里已有 `http://127.0.0.1:7890` ✓
         但进程环境里没有 ✗

    🔴 **不能直接 `kickstart -k`** ✗：
       那会**立即杀掉**本进程 ✗ ⇒ 本动作**自己的结果写不进去** ✗
       ⇒ 用 `nohup` 起一个**延迟 5 秒**的脚本 ✓
         它先等本动作写完 result ✓ 再 `kickstart -k` ✓

    ⚠️ 重启后**新进程会读新 plist** ✓ 代理生效 ✓
    ⚠️ 若队列里有**正在执行**的任务 ⇒ 会被杀 ✗（`delay` 参数可调 ✗）
    """
    label = "com.xingguo.fg-task-queue"
    delay = int(params.get("delay") or 5)
    uid = os.getuid() if hasattr(os, "getuid") else 501
    target = "gui/%s/%s" % (uid, label)

    # 写一个延迟脚本 ✓（避免杀自己 ✗）
    sh = os.path.join(ROOT, "dist", "_restart_queue.sh")
    os.makedirs(os.path.dirname(sh), exist_ok=True)
    with open(sh, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n"
                "sleep %d\n"
                "launchctl kickstart -k %s >> /tmp/fg_task_queue.log 2>&1\n"
                "echo \"[restart] $(date '+%%F %%T') kickstart done\" "
                ">> /tmp/fg_task_queue.log\n" % (delay, target))
    os.chmod(sh, 0o755)

    # 记录重启前的环境 ✓
    before = {k: (os.environ.get(k) or "")
              for k in ("FG_LLM_PROXY", "HTTP_PROXY", "HTTPS_PROXY")}

    try:
        subprocess.Popen(["nohup", "bash", sh],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
        ok, err = True, ""
    except Exception as exc:                # noqa: BLE001
        ok, err = False, "%s: %s" % (type(exc).__name__, str(exc)[:150])

    return {"ok": ok, "error": err, "label": label, "target": target,
            "delay_seconds": delay, "script": os.path.relpath(sh, ROOT),
            "env_before_restart": before,
            "note": "⚠️ %d 秒后重启 ✓ 重启后**新进程会读新 plist** ✓"
                    "代理生效 ✓；"
                    "⚠️ 队列里正在跑的任务会被杀 ✗ "
                    "⇒ 下次拉取时看 `run_fetch_step` 的 `has_proxy` ✓"
                    % delay}


def _act_bsk_update(params):
    """**升级 bsk CLI** ✓（2026-11-05 用户要求）。

    🔴 为什么必须升级 ✗：
       实测 bsk 的**写操作全部失败** ✗：
         `click`     rc=1  `shared page control or observation changed` ✗
         `evaluate`  rc=1  同上 ✗
       而**只读操作全部成功** ✓（observe/snapshot/get-html/network/tab ✗）
       根因：`bsk status` 长期警告：
         `protocol ext 1.3 vs CLI 1.1 (app ext v0.3.3, CLI v0.2.0)`
       ⇒ **写操作需要 ext 1.3 的新协议** ✗ ⇒ 必须升级 CLI ✓

    🔴 **必须先配代理** ✗（用户特别叮嘱 ✗）：
       `bsk update` 要下载 npm 包 ✗ 而**国内直连 npm 经常超时** ✗
       ⇒ 显式注入 `HTTP_PROXY` / `HTTPS_PROXY`（Mac 上是 `127.0.0.1:7890` ✗）

    参数：
      - `proxy`：默认 `http://127.0.0.1:7890` ✓
      - `dry_run`：`1` = 只查不升 ✓
      - `daemon`：`restart` = 升完**停掉旧 daemon** 并回读 `bsk status --json` ✓
        🔴 2026-11-06 实测：CLI 二进制已是 **0.4.2**（`bsk update` 说 up to date）
           但 `bsk status` 仍报 `CLI v0.2.0` ⇒ **daemon 是旧进程** ✗
           ⇒ 只升级不重启 daemon = 白升 ✗（协议仍 1.1，扩展是 1.3）
    """
    proxy = str(params.get("proxy") or "http://127.0.0.1:7890")
    dry = str(params.get("dry_run") or "").lower() in ("1", "true", "yes")
    restart_daemon = str(params.get("daemon") or "").lower() in ("restart", "1",
                                                                "true", "yes")

    # ① 升级前版本 ✓
    def _ver():
        try:
            r = subprocess.run([BSK_BIN, "--version"], capture_output=True,
                               text=True, encoding="utf-8",
                               errors="replace", timeout=30)
            return (r.stdout or r.stderr or "").strip()[:120]
        except Exception as exc:            # noqa: BLE001
            return "查不到：%s" % str(exc)[:100]

    before = _ver()

    # ② **带代理**跑 update ✓（用户明确要求 ✗）
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy"):
        env[k] = proxy
    # ⚠️ npm registry 走代理时**不要**把 localhost 也代理掉 ✗
    env.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
    env.setdefault("no_proxy", "127.0.0.1,localhost,::1")

    cmd = [BSK_BIN, "update"] + (["--check"] if dry else [])
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=900, env=env, cwd=ROOT)
        rc, so, se = r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return {"ok": False, "error": "**找不到 bsk** ✗（设 FG_BSK ✗）"}
    except subprocess.TimeoutExpired:
        rc, so, se = 124, "", "超过 900 秒 ✗（代理不通？✗）"
    secs = time.time() - t0

    after = _ver()

    def _run(args, timeout=90):
        """跑一条 bsk 子命令并回显（daemon 操作用）✓。"""
        try:
            r = subprocess.run([BSK_BIN] + list(args), capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, env=env, cwd=ROOT)
            return {"rc": r.returncode,
                    "out": (r.stdout or r.stderr or "").strip()[:1500]}
        except Exception as exc:            # noqa: BLE001
            return {"rc": -1, "out": str(exc)[:200]}

    out = {"ok": rc == 0, "rc": rc, "seconds": round(secs, 1),
           "proxy": proxy, "dry_run": dry,
           "version_before": before, "version_after": after,
           "changed": before != after,
           "stdout": so[-3000:], "stderr": se[-1500:],
           "note": ("⚠️ 升级后要**重启 daemon** 才生效 ✗"
                    "（`bsk daemon restart` 或重启 Chrome ✗）；"
                    "⚠️ 升级可能改变 CLI 行为 ✗ "
                    "`fetch_shoutu_history.py` 依赖它 ✓ 要回归 ✓")
           if rc == 0 and not dry else ""}
    if restart_daemon:
        # stop 之后**不需要** start：任何 bsk 命令都会自动拉起（SKILL.md）
        out["daemon_stop"] = _run(["daemon", "stop"])
        out["status_after"] = _run(["status", "--json"])
    return out


def _act_update_crypto(params):
    """**补抓加密数据** ✓（2026-11-03 用户要求）。

    🔴 为什么单独做一个动作：
       `crypto_prices.csv` / `crypto_underlying.csv` 停在 **2026-09-29**（35 天 ✗）
       而它们由每日链里的 `python -c "fetch.update_crypto_prices();
       fetch.update_crypto_aux()"` 生成 ✗（`guard#7`）
       ⇒ 那不是独立脚本 ✗ `run_fetch_step` 的白名单覆盖不到 ✗
       ⇒ 单独做一个 ✓

    【和 `run_fetch_step` 一样对比跑前后日期】✓
    参数：`aux`（默认 1，顺带跑 `update_crypto_aux()` ✓）
    """
    do_aux = str(params.get("aux") or "1").lower() in ("1", "true", "yes")
    code = ("from fg_system.data import fetch;"
            "print('prices:', fetch.update_crypto_prices())")
    if do_aux:
        code += ";print('aux:', fetch.update_crypto_aux())"

    def _snap():
        import glob as _g
        snap = {}
        for p in _g.glob(os.path.join(ROOT, "Data", "raw", "*.csv")):
            name = os.path.basename(p)
            if not any(k in name for k in ("crypto", "btc", "eth")):
                continue
            try:
                import pandas as _pd
                last = None
                for col in ("date", "observation_date"):
                    try:
                        d = _pd.read_csv(p, usecols=[col], parse_dates=[col])
                        last = d[col].max()
                        break
                    except Exception:       # noqa: BLE001
                        continue
                snap[name] = (str(last.date())
                              if last is not None and _pd.notna(last) else "?")
            except Exception:               # noqa: BLE001
                snap[name] = "?"
        return snap

    before = _snap()
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
        rc, so, se = r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        rc, so, se = 124, "", "超过 1800 秒"
    secs = time.time() - t0
    after = _snap()

    changed = {k: {"before": before.get(k), "after": v}
               for k, v in after.items() if before.get(k) != v}
    return {"ok": rc == 0, "rc": rc, "seconds": round(secs, 1),
            "aux": do_aux, "before": before, "after": after,
            "changed": changed,
            "verdict": ("rc=%d 但**加密文件无更新** ✗ ⇒ 静默失败 ✗"
                        % rc if rc == 0 and not changed
                        else "rc=%d，更新 %d 个" % (rc, len(changed))),
            "stdout": so[-4000:], "stderr": se[-2000:]}


def _act_run_fetch_step(params):
    """**单独重跑一个 fetch 脚本** ✓ 并对比跑前/跑后的数据日期。

    【为什么需要（2026-11-03）】
      7 个数据源在每日链里 `rc=0` ✗ 但数据停在 10-11~10-13 ✗
      ⇒ 链日志只记 rc ✗ **看不到脚本自己的输出** ✗
      ⇒ 必须单独跑一次，看它到底说了什么 ✓

    【本动作回答三个问题】
      ① 脚本**报错了吗**（stderr / 非 0 rc）✓
      ② 脚本**说成功但没写**吗（`before == after` ✗）✓ ← 最关键
      ③ 卡在**哪个环节**（完整 stdout 里有分步打印 ✓）

    参数：
      - `script`：**必须**是 `FETCH_SCRIPTS` 里的一个 ✓
      - `args`：额外参数（逗号分隔 ✗ 会被原样传给脚本 ✓）
      - `timeout`：默认 900 秒 ✓
    """
    script = str(params.get("script") or "").strip()
    if script not in FETCH_SCRIPTS:
        return {"ok": False,
                "error": "不允许的脚本：`%s` ✗（白名单：%s）"
                         % (script, ", ".join(FETCH_SCRIPTS))}

    raw_args = str(params.get("args") or "").strip()
    extra = [a for a in raw_args.split(",") if a] if raw_args else []
    limit = int(params.get("timeout") or 900)

    # ① 跑前快照 ✓ —— 只对比该脚本**可能写**的文件（全量太多 ✗）
    def _snap():
        import glob as _g
        snap = {}
        for p in _g.glob(os.path.join(ROOT, "Data", "raw", "*.csv")):
            name = os.path.basename(p)
            try:
                import pandas as _pd
                # 🔴 2026-11-03 踩坑：FRED 落盘用的是 **`observation_date`** ✗
                #    而原来写死 `usecols=["date"]` ✗ ⇒ 读 FRED 文件**抛异常** ✗
                #    ⇒ 记成 `"?"` ⇒ 被 `unchanged` 排除 ✗
                #    ⇒ 误判「`fetch_fred` 静默成功、无文件更新」✗（实际抓成功了 ✗）
                #    ⇒ 依次尝试 `date` / `observation_date` ✓
                last = None
                for col in ("date", "observation_date"):
                    try:
                        d = _pd.read_csv(p, usecols=[col], parse_dates=[col])
                        last = d[col].max()
                        break
                    except Exception:       # noqa: BLE001
                        continue
                snap[name] = (str(last.date())
                              if last is not None and _pd.notna(last) else "?")
            except Exception:               # noqa: BLE001
                snap[name] = "?"
        return snap

    before = _snap()
    t0 = time.time()
    cmd = [sys.executable, os.path.join(ROOT, "scripts", script)] + extra
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=limit)
        rc, so, se = r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        rc, so, se = 124, "", "超过 %d 秒被强杀" % limit
    secs = time.time() - t0
    after = _snap()

    # ② 哪些文件的日期变了 ✓ / 没变 ✗
    changed, unchanged = {}, {}
    for name, av in after.items():
        bv = before.get(name)
        if bv != av:
            changed[name] = {"before": bv, "after": av}
        elif av != "?":
            unchanged[name] = av

    # 🔴 2026-11-05：**回报代理环境变量** ✓
    #    为什么必须回报 ✗：
    #      `install_daily_plist` 只**拷贝 plist 文件** ✗ **不重启进程** ✗
    #      而任务队列是**常驻进程**（`state = running` ✗）
    #      ⇒ **新补的代理不会生效** ✗ 直到重启 ✗
    #      ⇒ 所以「重跑 fetch_*」之前**必须先确认这里有没有代理** ✗
    env_proxy = {k: (os.environ.get(k) or "")
                 for k in ("FG_LLM_PROXY", "HTTP_PROXY", "HTTPS_PROXY",
                           "http_proxy", "https_proxy", "NO_PROXY")}

    return {"ok": rc == 0, "script": script, "args": extra, "rc": rc,
            "seconds": round(secs, 1),
            "env_proxy": env_proxy,
            "has_proxy": bool(env_proxy.get("FG_LLM_PROXY")
                              or env_proxy.get("HTTPS_PROXY")
                              or env_proxy.get("https_proxy")),
            "changed": changed, "unchanged": unchanged,
            "verdict": ("rc=%d 但**没有任何文件更新** ✗ ⇒ 「静默成功」✗"
                        % rc if rc == 0 and not changed
                        else "rc=%d，更新了 %d 个文件"
                             % (rc, len(changed))),
            "stdout": so[-6000:], "stderr": se[-2000:]}


def _act_diagnose_data(params):
    """**数据断流诊断** ✓（2026-11-03 用户要求「Mac 上先修数据」）。

    【背景】
      `Data/raw/prices.csv` 停在 2026-10-12 ✗ 断 22 天 ✗
      而简报每天正常生成 ✗ ⇒ 「现价」「浮盈亏」全是 3 周前的数字 ✗
      ⇒ 先查**为什么停**，再决定怎么补 ✗

    【查什么】
      ① 每个 `Data/raw/*.csv` 的**行数 + 最新日期** ✓
      ② `/tmp/fg_daily.log` 尾部（找 `fetch_*` 的报错 ✗）
      ③ launchd 里 `fg-daily` 的**最后退出码** ✓

    参数：`tail`（日志行数，默认 40）✓
    """
    import glob as _glob
    from datetime import datetime as _dt

    n_tail = int(params.get("tail") or 40)
    out = {"checked_at": _dt.now().isoformat(timespec="seconds"),
           "files": {}, "log_tail": "", "launchd": ""}

    # ① 各 csv 的最新日期
    for p in sorted(_glob.glob(os.path.join(ROOT, "Data", "raw", "*.csv"))):
        name = os.path.basename(p)
        try:
            import pandas as _pd
            d = _pd.read_csv(p, usecols=["date"], parse_dates=["date"])
            last = d["date"].max()
            out["files"][name] = {
                "rows": int(len(d)),
                "last": str(last.date()) if _pd.notna(last) else "?",
            }
        except Exception as e:              # noqa: BLE001
            out["files"][name] = {"error": str(e)[:80]}

    # ② 每日链日志尾部
    log = "/tmp/fg_daily.log"
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        out["log_tail"] = "".join(lines[-n_tail:])[-3000:]
    except Exception as e:                  # noqa: BLE001
        out["log_tail"] = "读不到 %s：%s" % (log, e)

    # ③ launchd 状态
    try:
        r = subprocess.run(["launchctl", "print", "gui/%d/com.xingguo.fg-daily"
                            % os.getuid()],
                           capture_output=True, text=True, timeout=60)
        txt = r.stdout or r.stderr or ""
        keep = [ln.strip() for ln in txt.splitlines()
                if any(k in ln for k in ("state =", "last exit", "runs =",
                                         "program ="))]
        out["launchd"] = "\n".join(keep[:8]) or "(无输出)"
    except Exception as e:                  # noqa: BLE001
        out["launchd"] = "查不到：%s" % e

    # 判断是否真的断流 ✓
    stale = []
    for name, v in out["files"].items():
        last = v.get("last")
        if not last or last == "?":
            continue
        try:
            gap = (_dt.now() - _dt.strptime(last, "%Y-%m-%d")).days
        except ValueError:
            continue
        if gap > 5:
            stale.append("%s 停 %d 天（%s）" % (name, gap, last))
    out["stale"] = stale
    out["ok"] = not stale
    return out


def _act_inspect_sync(params):
    """**查 Mac 端的 `fg-sync` 到底怎么提交的** ✓ + 可选停止追踪 `Data/raw/`。

    🔴 为什么需要（2026-11-03）：
       `Data/raw/` 被 `git rm --cached` **三次**都「回退」了 ✗
       每次都发现「索引里又是 40 个」✗
       ⇒ 高度怀疑 Mac 端的 `fg-sync`（外部工具 ✗ 不在仓库里 ✗）
         用了 `git add -A` ✗ ⇒ 每次都把 `Data/raw/` 加回来 ✗

    【查什么】
      ① `fg-sync` 脚本在哪（搜 `~/.openclaw` / `~/bin` / `/usr/local/bin` ✗）
      ② 它的 `git add` 用法（`-A` / `-a` / `.` ✗ 都是全加 ✗）
      ③ 当前 `git ls-files Data/raw/` 的数量 ✓
      ④ 是否已有 `Data/raw/` 的 ignore 规则 ✓

    参数：`untrack`（`1` = 顺带执行 `git rm -r --cached Data/raw/` ✓
                    **本地文件保留** ✓ 但不提交 ✗ 让常规流程带走 ✓）
    """
    import glob as _g

    out = {}
    # ① 找 fg-sync
    hits = []
    for d in (os.path.expanduser("~/.openclaw"),
              os.path.expanduser("~/bin"),
              "/usr/local/bin", "/opt/homebrew/bin",
              os.path.expanduser("~/learning_backtrader/scripts")):
        if not os.path.isdir(d):
            continue
        for p in _g.glob(os.path.join(d, "**", "*fg*sync*"), recursive=True):
            if os.path.isfile(p):
                hits.append(p)
        for p in _g.glob(os.path.join(d, "**", "*sync*"), recursive=True):
            if os.path.isfile(p) and p not in hits and os.path.getsize(p) < 200000:
                try:
                    txt = open(p, encoding="utf-8", errors="replace").read()
                    if "fg-sync" in txt or "公司端同步" in txt:
                        hits.append(p)
                except OSError:
                    pass
    out["fg_sync_candidates"] = hits[:6]

    # ② 看它们的 **所有 git 调用行** ✓
    #    🔴 2026-11-03 实测：只 grep `git`+`add` 得到 **空结果** ✗
    #    ⇒ 说明它不用 `git add` ✗ 可能用 `git commit -a` / `git add -u`
    #      / 或者调别的工具 ✗ ⇒ **必须把全部含 git 的行都打出来** ✓
    adds = {}
    for p in hits[:6]:
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        lines = [ln.strip() for ln in txt.splitlines()
                 if "git" in ln.lower() or "add -" in ln or "commit" in ln]
        if lines:
            adds[p] = lines[:12]
    out["git_lines"] = adds

    # ②b 如果还是空 ⇒ 直接把候选文件的**前 40 行**打出来 ✓
    if not adds:
        heads = {}
        for p in hits[:3]:
            try:
                txt = open(p, encoding="utf-8", errors="replace").read()
                heads[p] = txt[:1200]
            except OSError:
                continue
        out["file_heads"] = heads

    # ③ 当前追踪状态
    def _git(*a):
        try:
            r = subprocess.run(["git", "-C", ROOT] + list(a),
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
            return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
        except Exception as e:              # noqa: BLE001
            return -1, "", str(e)

    _, tracked, _ = _git("ls-files", "Data/raw/")
    out["tracked_count"] = len([x for x in tracked.splitlines() if x])
    out["tracked_sample"] = tracked.splitlines()[:5]

    # ④ ignore 规则
    rc, _, _ = _git("check-ignore", "-v", "Data/raw/prices.csv")
    out["ignore_rule"] = "已 ignore ✓" if rc == 0 else "**未 ignore** ✗"

    # 可选：停止追踪 ✓
    if str(params.get("untrack") or "").lower() in ("1", "true", "yes"):
        rc, so, se = _git("rm", "-r", "--cached", "--quiet", "Data/raw/")
        _, after, _ = _git("ls-files", "Data/raw/")
        out["untrack"] = {
            "rc": rc, "stderr": se[-300:],
            "tracked_after": len([x for x in after.splitlines() if x]),
            "note": "本地文件**保留** ✓ 只是索引移除 ✓ "
                    "⚠️ 未提交 ✗ 需常规流程带走（或 `fg-sync` ✗ 见 git_add_lines）",
        }

    return {"ok": True, "root": ROOT, **out,
            "verdict": ("⚠️ 找到 %d 个候选 fg-sync ✗ 若其中有 `git add -A` / `add -a` / "
                        "`add .` ⇒ **这就是 Data/raw 反复回索引的真因** ✗"
                        % len(hits)) if hits else
                       "✗ **没找到 fg-sync 脚本** ✗ 需手工确认它从哪来"}


def _act_safe_pull_data(params):
    """**带数据保护的 git pull** ✓（2026-11-03 新增，紧急）。

    🔴 为什么必须单独做一个：
       `Data/raw/` 已被 `git rm --cached` 停止追踪 ✗
       ⇒ 那个提交里含 **`delete mode`** 记录 ✗
       ⇒ 普通 `git pull` / `merge --ff-only` 会**物理删除本地文件** ✗
       ⇒ Mac 上 40 个抓了几个月的数据文件会**瞬间消失** ✗
          （历史数据抓不回来 ✗）

    【本动作的顺序】
      ① 备份 `Data/raw/*.csv` 到 `dist/raw_backup_<时间戳>/` ✓
      ② `git fetch` + `git merge --ff-only origin/main` ✓（会删文件 ✗ 正常）
      ③ **把备份里「现在不存在」的文件拷回** ✓
      ④ 验证：文件数、各 csv 最新日期 ✓
      ⑤ 备份**保留** ✓（不自动删 ✗ 让用户确认后再清 ✓）

    参数：`keep_backup`（默认 1 = 保留备份 ✓）
    """
    import glob as _g
    import shutil as _sh

    steps = []
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(ROOT, "dist", "raw_backup_%s" % ts)
    raw = os.path.join(ROOT, "Data", "raw")

    # ① 备份
    try:
        os.makedirs(backup, exist_ok=True)
        n = 0
        for p in _g.glob(os.path.join(raw, "*.csv")):
            _sh.copy2(p, os.path.join(backup, os.path.basename(p)))
            n += 1
        steps.append({"step": "backup", "ok": True, "files": n,
                      "path": os.path.relpath(backup, ROOT)})
    except OSError as exc:
        return {"ok": False, "error": "备份失败，**中止** ✗：%s" % exc}

    # ② pull
    def _git(*a):
        try:
            r = subprocess.run(["git", "-C", ROOT] + list(a),
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=300)
            return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
        except Exception as e:              # noqa: BLE001
            return -1, "", str(e)

    # ①b 🔴 2026-11-04：**拉取前先停止追踪 `Data/raw/`** ✓（`untrack=1`）
    #     为什么必须在 pull **之前**做 ✗：
    #       `git rm -r --cached Data/raw/` 只删索引 ✓ **本地文件保留** ✓
    #       索引里没有记录后 ✗ `merge` 就不会「按提交里的 delete mode
    #       去删工作区文件」✗ ⇒ **文件不会消失** ✓
    #     ⚠️ 反过来（先 pull 再 rm --cached）✗ 文件已经被删了 ✗ 补不回来 ✗
    if str(params.get("untrack") or "").lower() in ("1", "true", "yes"):
        rc_u, so_u, se_u = _git("rm", "-r", "--cached", "--quiet", "Data/raw/")
        _, left, _ = _git("ls-files", "Data/raw/")
        steps.append({"step": "untrack_before_pull", "rc": rc_u,
                      "tracked_after": len([x for x in left.splitlines() if x]),
                      "stderr": se_u[-300:]})

    _git("fetch", "origin")
    rc, so, se = _git("merge", "--ff-only", "origin/main")
    steps.append({"step": "merge", "rc": rc,
                  "stdout": so[-400:], "stderr": se[-400:]})

    # ③ 恢复被删的文件 ✓
    restored, missing_src = [], []
    for p in _g.glob(os.path.join(backup, "*.csv")):
        dest = os.path.join(raw, os.path.basename(p))
        if os.path.exists(dest):
            continue
        try:
            _sh.copy2(p, dest)
            restored.append(os.path.basename(p))
        except OSError as exc:
            missing_src.append("%s: %s" % (os.path.basename(p), exc))
    steps.append({"step": "restore", "restored": len(restored),
                  "files": restored[:10], "errors": missing_src[:5]})

    # ④ 验证
    import pandas as _pd
    after = {}
    for p in sorted(_g.glob(os.path.join(raw, "*.csv"))):
        try:
            last = None
            for col in ("date", "observation_date"):
                try:
                    d = _pd.read_csv(p, usecols=[col], parse_dates=[col])
                    last = d[col].max()
                    break
                except Exception:           # noqa: BLE001
                    continue
            after[os.path.basename(p)] = (
                str(last.date()) if last is not None and _pd.notna(last) else "?")
        except Exception:                   # noqa: BLE001
            after[os.path.basename(p)] = "?"

    keep = str(params.get("keep_backup") or "1").lower() in ("1", "true", "yes")
    if not keep and not missing_src:
        _sh.rmtree(backup, ignore_errors=True)

    return {"ok": rc == 0 and not missing_src,
            "backup": os.path.relpath(backup, ROOT),
            "backup_kept": keep,
            "file_count": len(after),
            "steps": steps,
            "files_after": after,
            "note": "⚠️ 备份**保留**在 `%s` ✗ 确认数据无误后可手工删 ✓"
                    % os.path.relpath(backup, ROOT)}


def _act_git_pull(params):
    """在 Mac 上 **git pull** 并汇报关键状态 ✓（2026-11-03 用户裁定）。

    【为什么需要】
      公司端 push → gitee → Mac 拉取 ✗ 这条链路一直靠人工 ✗
      而「入库后本地文件被删/被改」这类副作用（如
      `git rm --cached Data/realtime_state.json` ✗）需要**验证** ✓

    【参数】
      - `stash`：`1` ⇒ 拉取前先 `git stash`（本地有未提交改动时用 ✓）
      - `show_status`：`1`（默认）⇒ 拉完打印 `git status --short`

    【输出】
      before/after 的 HEAD、behind 数、拉取结果、status ✓
    """
    import subprocess as _sp

    def _git(*a):
        try:
            r = _sp.run(["git", "-C", ROOT] + list(a),
                        capture_output=True, text=True, timeout=300)
            return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
        except _sp.TimeoutExpired:
            return -1, "", "超过 300 秒"
        except Exception as e:              # noqa: BLE001
            return -1, "", str(e)

    steps = []
    _, before, _ = _git("rev-parse", "--short", "HEAD")
    steps.append({"step": "before_head", "value": before})

    if str(params.get("stash") or "").lower() in ("1", "true", "yes"):
        rc, so, se = _git("stash", "push", "-m", "task-queue auto-stash")
        steps.append({"step": "stash", "rc": rc, "stdout": so, "stderr": se})

    rc, so, se = _git("fetch", "origin")
    steps.append({"step": "fetch", "rc": rc, "stderr": se[-300:]})

    rc, behind, _ = _git("rev-list", "--count", "HEAD..origin/main")
    steps.append({"step": "behind", "value": behind})

    # 🔴 `--ff-only` 而非 `pull --rebase` ✗ —— 公司端是**线性**提交 ✓
    #    本地若有分叉 ⇒ 明确失败 ✓ 而不是自动产生 merge commit ✗
    rc, so, se = _git("merge", "--ff-only", "origin/main")
    steps.append({"step": "pull", "rc": rc, "stdout": so[-500:],
                  "stderr": se[-500:]})

    _, after, _ = _git("rev-parse", "--short", "HEAD")
    steps.append({"step": "after_head", "value": after})

    if str(params.get("show_status") or "1").lower() in ("1", "true", "yes"):
        _, st, _ = _git("status", "--short")
        steps.append({"step": "status", "value": st[:1500] or "(clean ✓)"})

    # 🔴 2026-11-03：**补推** ✓ —— 用户反馈「页面显示任务失败但 git 上没有结果」✗
    #    根因可能是：任务结果**在 Mac 本地提交了但没 push** ✗
    #    （`_try_push_pending` 每 300s 自愈一次 ✗ 若一直失败就永远不推 ✗）
    #    ⇒ `push=1` 时显式推一次 ✓ 并**回传 ahead 数**（推前有几个未推提交 ✓）
    if str(params.get("push") or "").lower() in ("1", "true", "yes"):
        _, ahead, _ = _git("rev-list", "--count", "@{u}..HEAD")
        steps.append({"step": "ahead_before_push", "value": ahead})
        rc, so, se = _git("push", "origin", "HEAD")
        steps.append({"step": "push", "rc": rc, "stdout": so[-300:],
                      "stderr": se[-500:]})
        _, ahead2, _ = _git("rev-list", "--count", "@{u}..HEAD")
        steps.append({"step": "ahead_after_push", "value": ahead2})

    ok = all(x.get("rc", 0) == 0 for x in steps if "rc" in x)
    return {"ok": ok, "before": before, "after": after,
            "pulled": before != after, "steps": steps}


def _act_sync_runtime(params):
    """把仓库版 bypass 覆盖到运行时副本（见 sync_health.sync_runtime_copy）。"""
    from fg_system.dashboard import sync_health
    return sync_health.sync_runtime_copy()


def _act_clean_sync_partial(params):
    """删掉**指定包**的残留分片（`~/.openclaw/tmp/fg-sync-in/<pkg>_*.md`）✓。

    动机（MT-87，2026-10-28）：Windows 侧弃用的包永远收不齐 ✗ ⇒ bypass 每次同步
    都报「分片不齐，请补发」✗。只删 `pkg` 前缀的分片 ✓，不碰 `.done` / 其它包 ✗。
    """
    from fg_system.dashboard import sync_health
    pkg = str(params.get("pkg") or "")
    # 🔴 只允许 [A-Za-z0-9_] —— 挡住 `..`、`/`、`*` 这类会越出目录的写法 ✗
    if not pkg or any(not (c.isalnum() or c == "_") for c in pkg):
        return {"ok": False, "reason": "pkg 名非法（只允许 [A-Za-z0-9_]）：%r" % pkg}
    removed = []
    for p in sorted(glob.glob(os.path.join(sync_health.SHARD_IN, pkg + "_*.md"))):
        try:
            os.remove(p)
        except OSError as exc:
            return {"ok": False, "removed": removed,
                    "reason": "删 %s 失败：%s" % (os.path.basename(p), exc)}
        removed.append(os.path.basename(p))
    return {"ok": True, "removed": removed, "count": len(removed)}


def _act_install_evolve_tasks(params):
    """重新注册 evolve 定时器（跑仓库里的 `install_evolve_tasks.sh`）✓。

    动机（2026-10-29）：plist 只改仓库副本**不生效** ✗ —— 真身是
    `~/Library/LaunchAgents/*.plist`，必须重跑安装脚本才会重新 bootstrap ✓。
    固定脚本、固定路径，不接受任何参数 ✓（与白名单同一原则 ✗）。
    """
    script = os.path.join(ROOT, "scripts", "install_evolve_tasks.sh")
    if not os.path.exists(script):
        return {"ok": False, "reason": "找不到 %s" % script}
    try:
        r = subprocess.run(["bash", script], cwd=ROOT, capture_output=True,
                           text=True, timeout=180)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-900:], "stderr": (r.stderr or "")[-400:]}


def _act_futu_preflight(params):
    """探一次富途 OpenD 端口 ✓ —— 只读、2 秒超时、零副作用 ✓。

    动机（2026-10-29）：新加的「预检 + 硬超时」要等到明天 05:30 才被跑到 ✗，
    这里让 Mac **立刻验一次** ✓，顺带把状态落盘（简报里就能看到）✓。
    """
    if os.path.join(ROOT, "scripts") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import futu_health
    ok, why = futu_health.preflight()
    futu_health.write_status(ok, why, "queue:futu_preflight")
    return {"ok": bool(ok), "reason": why}


#: 需要「从仓库副本装到 LaunchAgents」的 plist ✓
PLISTS = ["com.xingguo.fg-daily.plist", "com.xingguo.fg-task-queue.plist",
          # 2026-11-03 新增：每周一 07:30 跑 `weekly_review.py` ✓
          # （必须在 Mac ✗ Windows 的 Data/raw 只是旧快照 ✗）
          "com.xingguo.fg-weekly-review.plist"]


def _act_install_daily_plist(params):
    """把仓库里的 plist 装到 `~/Library/LaunchAgents` 并重新 bootstrap ✓。

    动机（2026-10-29）：plist 只改仓库副本**不生效** ✗ —— 真身是
    `~/Library/LaunchAgents/*.plist`，launchd 读的是那份 ✗。
    （每日链套 `run_guarded`、队列加 PATH 都靠这一步落地 ✓。）

    🔴 `com.xingguo.fg-task-queue` **不能当场 bootout** ✗ —— 执行本任务的进程
    正是它启动的 ✗，当场 bootout 会把自己杀掉、结果永远写不出来 ✗
    ⇒ 用**延迟 8 秒的游离 shell** 去重装 ✓。
    """
    agent = os.path.expanduser("~/Library/LaunchAgents")
    domain = "gui/%d" % os.getuid()
    out = {}
    for name in PLISTS:
        src = os.path.join(ROOT, "scripts", name)
        if not os.path.exists(src):
            out[name] = "缺文件 %s" % src
            continue
        dst = os.path.join(agent, name)
        label = name[:-len(".plist")]
        try:
            os.makedirs(agent, exist_ok=True)
            shutil.copy2(src, dst)
        except OSError as exc:
            out[name] = "拷贝失败：%s" % exc
            continue
        if label.endswith("fg-task-queue"):
            # 延迟重装：先让本任务把结果写完 ✓
            # 🔴 2026-10-29：重装结果**必须落盘** ✗ —— 原来起个游离 shell 就返回，
            # `ok:true` 只代表「拷贝成功」，8 秒后成没成无人回收 ✗
            # ⇒ 那个 shell 把结果写进 `<tid>.reinstall.json` ✓，下一轮 `_collect_reinstall`
            #   读回来并回写进任务结果 ✓（看板可见 ✓）。
            tid = str(params.get("_tid") or ("plist-" + time.strftime("%H%M%S")))
            marker = os.path.join(QUEUE, tid + ".reinstall.json")
            script = (
                "sleep 8; "
                "launchctl bootout {dom}/{lab} 2>/dev/null; "
                "launchctl bootstrap {dom} {dst}; RC=$?; "
                "launchctl enable {dom}/{lab} 2>/dev/null; "
                "printf '{{\"ok\": %s, \"rc\": %s, \"at\": \"%s\","
                " \"label\": \"{lab}\"}}' "
                "\"$([ $RC -eq 0 ] && echo true || echo false)\" \"$RC\" "
                "\"$(date +%Y-%m-%dT%H:%M:%S)\" > {marker}"
            ).format(dom=domain, lab=label, dst=dst, marker=marker)
            subprocess.Popen(["/bin/sh", "-c", script],
                             start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out[name] = "已拷贝（8 秒后重装，结果下轮回写）"
            continue
        try:
            subprocess.run(["launchctl", "bootout", "%s/%s" % (domain, label)],
                           capture_output=True, timeout=30)
            r = subprocess.run(["launchctl", "bootstrap", domain, dst],
                               capture_output=True, text=True, timeout=60)
            subprocess.run(["launchctl", "enable", "%s/%s" % (domain, label)],
                           capture_output=True, timeout=30)
            out[name] = "ok" if r.returncode == 0 else (r.stderr or "")[-200:]
        except (subprocess.SubprocessError, OSError) as exc:
            out[name] = "launchctl 失败：%s" % exc
    # 🔴 2026-11-03 用户要求：**装完必须验证** ✗
    #    原来只返回「拷贝成功」✗ 无法证明
    #    ① 代理变量真的进了 `~/Library/LaunchAgents/*.plist` ✗
    #    ② launchd 认了这份配置 ✗
    #    ⇒ 而 `launchctl print` **不显示 EnvironmentVariables** ✗
    #    ⇒ 只能「回读已安装的 plist 文件」+「看 launchd 状态」两条并用 ✓
    verify = {}
    for name in PLISTS:
        dst = os.path.join(agent, name)
        v = {}
        try:
            import plistlib as _pl
            with open(dst, "rb") as f:
                d = _pl.load(f)
            ev = d.get("EnvironmentVariables") or {}
            v["proxy_in_file"] = {
                k: ev.get(k) for k in
                ("FG_LLM_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
                if k in ev
            }
            v["env_keys"] = sorted(ev)
        except Exception as exc:            # noqa: BLE001
            v["file_error"] = str(exc)[:120]
        label = name[:-len(".plist")]
        try:
            r = subprocess.run(
                ["launchctl", "print", "%s/%s" % (domain, label)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60)
            txt = r.stdout or r.stderr or ""
            keep = [ln.strip() for ln in txt.splitlines()
                    if any(k in ln for k in ("state =", "last exit",
                                             "runs =", "path ="))]
            v["launchd"] = " | ".join(keep[:4]) or "(无输出)"
        except Exception as exc:            # noqa: BLE001
            v["launchd"] = "查不到：%s" % exc
        verify[name] = v

    return {"ok": all(v.startswith("ok") or v.startswith("已拷贝")
                      for v in out.values()),
            "result": out,
            "verify": verify,
            "note": "⚠️ `launchctl print` **不显示 EnvironmentVariables** ✗ "
                    "⇒ 代理是否生效看 `verify.*.proxy_in_file` ✓；"
                    "真实生效要等下次链跑（看 fetch 耗时）✓"}


def _act_sync_positions(params):
    """跑一次持仓/账户同步 ✓（`scripts/sync_positions.py`）。

    2026-11-02：用于验证 OKX 的 `securities_mv` / `cash` 拆分 ✓
    （`_okx_split_equity` 从 `/account/balance` 的 `details[]` 拆出来 ✓）
    ⚠️ 会**覆盖** `accounts.csv` / `positions.csv` 的当日行 ✗ —— 幂等 ✓
    """
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "sync_positions.py")]
    # 🔴 2026-11-02 实测：`sync_positions.py` 默认 **static** ✗ ——
    # static 下**不调任何外部 API**、**不碰 accounts/positions** ✗
    # ⇒ 队列任务跑完报 done，但什么都没验证到 ✗（第一次就是这么被骗的 ✗）
    # 而每日链 plist 里是 `FG_SYNC_MODE=live ... sync_positions.py` ✓
    # ⇒ 队列必须显式传 live ✓（否则「验证 OKX 拆分」这个目的达不到 ✗）
    env = dict(os.environ, FG_SYNC_MODE="live")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 300 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    # 🔴 2026-11-05：**回报 `day_pnl` 非空统计** ✓（用户要求 ✗）
    #    为什么需要 ✗：`fill_day_pnl` 刚加上 ✓ 但 stdout 里看不到效果 ✗
    #    而 `day_pnl` 之前 **54 行里只有 1 行有值** ✗（那列从来没被赋值 ✗）
    #    ⇒ 必须**直接统计列的非空数** ✗ 才能确认回填成功 ✓
    stats = {}
    try:
        import pandas as _pd
        p = os.path.join(ROOT, "Data", "accounts.csv")
        if os.path.exists(p):
            d = _pd.read_csv(p)
            stats["accounts_rows"] = int(len(d))
            if "day_pnl" in d.columns:
                nn = int(d["day_pnl"].notna().sum())
                stats["day_pnl_nonnull"] = nn
                stats["day_pnl_ratio"] = round(
                    nn / float(len(d)), 3) if len(d) else 0.0
            if "date" in d.columns:
                stats["date_unique"] = int(d["date"].nunique())
                dd = sorted(d["date"].astype(str).unique())
                stats["date_range"] = "%s → %s" % (dd[0], dd[-1]) if dd else ""
            # 每账户最近一天的 day_pnl ✓（看是否真的算出来了 ✗）
            if {"date", "account", "day_pnl"}.issubset(d.columns) and len(d):
                last = d[d["date"].astype(str) == str(d["date"].max())]
                stats["last_day"] = {
                    str(row["account"]): (None if _pd.isna(row["day_pnl"])
                                          else round(float(row["day_pnl"]), 2))
                    for _, row in last.iterrows()}
    except Exception as exc:                # noqa: BLE001
        stats["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:150])

    # 恒等式不成立时脚本 return 1 ✗ —— 那是**保护**不是崩溃 ✓
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "day_pnl_stats": stats,
            "note": "rc=1 多半是恒等式校验拦住了（sec_mv+cash != net）✗",
            "stdout": (r.stdout or "")[-1500:],
            "stderr": (r.stderr or "")[-600:]}




def _act_fetch_prices(params):
    """**补抓行情**（`fetch.update_prices()`）✓（2026-11-03 数据断流修复）。

    【背景】
      每日链里**有**这一步（`python -c "fetch.update_prices()"` ✗）
      但 `prices.csv` 停在 2026-10-12 ✗ 断 22 天 ✗
      ⇒ 说明这一步**每天失败** ✗ 而日志被后面成功的步骤淹没了 ✗

    【做什么】
      ① 跑 `fetch.update_prices()` ✓ 抓完整 traceback ✓
      ② 跑完读 `prices.csv` 的**最新日期** ✓ 看有没有真更新 ✓
      ③ 同时补 `update_indices()`（VIX/VIX3M 也停了 22 天 ✗）

    参数：`indices`（默认 1，顺带抓 VIX ✓）
    """
    import pandas as _pd

    code = ("from fg_system.data import fetch;"
            "print('prices:', fetch.update_prices())")
    if str(params.get("indices") or "1").lower() in ("1", "true", "yes"):
        code += ";print('indices:', fetch.update_indices())"

    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                           capture_output=True, text=True, timeout=1800)
        so, se, rc = r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        so, se, rc = "", "超过 1800 秒", -1

    # 抓完看结果 ✓ —— 「跑成功」不等于「数据变了」✗
    after = {}
    for name in ("prices.csv", "vix.csv", "vix3m.csv"):
        p = os.path.join(ROOT, "Data", "raw", name)
        try:
            d = _pd.read_csv(p, usecols=["date"], parse_dates=["date"])
            after[name] = {"rows": int(len(d)),
                           "last": str(d["date"].max().date())}
        except Exception as e:              # noqa: BLE001
            after[name] = {"error": str(e)[:80]}

    return {"ok": rc == 0, "rc": rc,
            "stdout": so[-2500:], "stderr": se[-2000:],
            "after": after,
            "note": "⚠️ rc=0 但 `after` 里日期没变 ⇒ 抓取「成功但无新数据」✗"}


def _act_fetch_indices(params):
    """补抓 VIX / VIX3M（`fetch.update_indices()`）✓。

    2026-10-31：每日链每天跑这一步，但它**失败就整步抛错** ✗ ——
    `factor_diag` 只能看到结果，没法触发重抓 ✗
    ⇒ 加这个动作，用于「发现缺失 → 立刻补 → 再复核」的闭环 ✓。
    """
    code = ("from fg_system.data import fetch;"
            "print(fetch.update_indices())")
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                           capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 600 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1200:],
            "stderr": (r.stderr or "")[-800:]}


def _act_c5_backtest(params):
    """C5 ENE 回测裁判 ✓ —— 两步：dump `ene_pos` 进研究 features → 跑 probe。

    2026-10-31 用户裁定：**C5b（自身 ENE）进裁判** ✓
    理由：三变体 ICIR 差距在噪声内（YINN 差 0.044、GDXU 杠杆反而更好 ✗）
    ⇒ 选**最简**的（不需要正股映射表维护 ✓）。
    ⚠️ 且 ICIR 已证实**结构性虚高**（IC 自相关 0.99 ⇒ n_eff 仅 5~15）
    ⇒ **只有裁判结果算数** ✗
    """
    base = str(params.get("features")
               or "evolution/experiments/factor-adoption/features_c5.csv")
    # 2026-10-31 用户裁定：**跑多个标的** ✓（单标的不够代表性）
    # 每个标的必须**各自 dump 一份 features** ✗ —— `ene_pos` 是单列，
    # 不同标的的信号不能塞进同一份文件（会互相覆盖 ✗）
    syms = [x.strip() for x in str(
        params.get("symbols") or params.get("symbol") or "YINN").split(",")
        if x.strip()]
    mode = str(params.get("mode") or "self_ene")
    # `ene_pos` 高 = 超买 ⇒ 未来收益低 ⇒ direction=**negative** ✓
    direc = str(params.get("direction") or "negative")
    steps, feat_of = [], {}
    for s in syms:
        f = base[:-4] + "_%s.csv" % s if base.endswith(".csv") else base + "_" + s
        feat_of[s] = f
        steps.append([sys.executable, os.path.join(ROOT, "scripts", "eval_ene.py"),
                      "--dump-features", f, "--dump-symbol", s,
                      "--dump-mode", mode])
        steps.append([sys.executable,
                      os.path.join(ROOT, "scripts", "factor_backtest_probe.py"),
                      "--factor", "ene_pos", "--symbol", s,
                      "--direction", direc, "--features", f])
    out = []
    for cmd in steps:
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                               timeout=1800)
        except subprocess.TimeoutExpired:
            out.append({"cmd": " ".join(cmd[1:]), "rc": -1,
                        "stdout": "", "stderr": "超过 1800 秒"})
            continue
        # 🔴 probe 判 FAIL 时 **exit 1** ✗ —— 那是**结论**不是崩溃 ✓
        # ⇒ 不能 break，否则后面的标的全被跳过 ✗
        out.append({"cmd": " ".join(cmd[1:]), "rc": r.returncode,
                    "stdout": (r.stdout or "")[-2000:],
                    "stderr": (r.stderr or "")[-400:]})
    # 🔴 2026-10-31 实测：`ok` 用 `rc == 0` 判会让**整个任务显示 failed** ✗
    # 而 probe 判 FAIL 时 `exit 1` 是**结论**不是崩溃 ✗
    # ⇒ 只把「执行异常」（rc not in 0/1）算失败 ✓
    # 并从 stdout 里抽出每个标的的判定，避免被 2000 字截断看不到 ✓
    import re as _re
    verdicts = {}
    for st in out:
        m = _re.search(r"symbol (\w+) --direction", str(st.get("cmd")))
        if not m:
            continue
        v = _re.search(r"判定：\*\*(PASS|FAIL)", str(st.get("stdout") or ""))
        verdicts[m.group(1)] = v.group(1) if v else "?"
    bad = [x for x in out if x.get("rc") not in (0, 1)]
    return {"ok": not bad,
            "symbols": syms, "features": feat_of, "verdicts": verdicts,
            "n_pass": sum(1 for v in verdicts.values() if v == "PASS"),
            "n_fail": sum(1 for v in verdicts.values() if v == "FAIL"),
            "note": "⚠️ 裁判 FAIL 时 probe 会 exit 1 —— 那是**结论**不是崩溃 ✓",
            "errors": bad}


def _act_factor_reduce_probe(params):
    """**风控型因子专用裁判**：减仓触发回测 ✓（2026-11-02 用户裁定接进队列）。

    为什么需要独立动作 ✗：`factor_backtest_probe` 的口径是「因子 → 仓位 0.2~1.0
    线性映射」✗ 它要求因子能**决定仓位比例** ✗ 但 F-016/F-018/F-020 的能力只是
    「识别危险时刻」✗ ⇒ 用满仓吃 beta 的口径去测必然「跑输 B0」✗ 是口径错配 ✗

    参数：
      - `factor`：`ene` / `f020` / `f020_pct`（默认 `ene`）
      - `symbols`：逗号分隔（默认 SPY,YINN,GDXU,CONL,QQQ）
      - `trend_filter`：`1` 开启 MA200 趋势过滤 ✓
        ⚠️ **位置型因子（ENE）不要开** ✗ —— 实测 GDXU 从 +0.05 掉到 -0.04 ✗
           **状态型因子（f020_pct）要开** ✓ —— 有效数 2/5→4/5 ✓
      - `json`：结果落盘路径
    """
    factor = str(params.get("factor") or "ene")
    syms = str(params.get("symbols") or "SPY,YINN,GDXU,CONL,QQQ")
    tf = str(params.get("trend_filter") or "").lower() in ("1", "true", "yes", "on")
    js = params.get("json") or (
        "evolution/experiments/factor-adoption/reduce-%s.json" % factor)

    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "factor_reduce_probe.py"),
           "--factor", factor, "--symbols", syms, "--json", js]
    if tf:
        cmd.append("--trend-filter")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=1800)
    except subprocess.TimeoutExpired:
        return {"ok": False, "factor": factor, "trend_filter": tf,
                "error": "超过 1800 秒"}
    return {"ok": r.returncode == 0, "factor": factor,
            "trend_filter": tf, "symbols": syms, "json": js,
            "note": "判据是 **Calmar**（不是「跑赢 B0」✗）—— "
                    "风控型因子的价值是「同样收益下更少回撤」✓",
            "stdout": (r.stdout or "")[-3000:],
            "stderr": (r.stderr or "")[-400:]}


def _act_f_factor_backtest(params):
    """F-012 / F-020 通用回测裁判 ✓（2026-11-02）。

    两步：`eval_f020.py --dump-features`（写出 `f012_term` / `f020_pc`）
    → `factor_backtest_probe.py --factor <列> --direction <方向>` ✓

    ⚠️ **一个动作跑一个因子** ✗ —— 用户裁定 F-012 / F-020 是**两个独立裁判** ✓
    （两者信号来源不同、经济含义不同，合在一起会混淆结论 ✗）

    方向：
      - `f012_term`（term 变化率）：高=恐慌缓和 ⇒ **positive** ✓
      - `f020_pc`（P/C>1.2 触发）：高=极恐 ⇒ **negative** ✓（逆向：触发时应看多）
    """
    feat = str(params.get("features")
               or "evolution/experiments/factor-adoption/features_f012f020.csv")
    factor = str(params.get("factor") or "f012_term")
    direc = str(params.get("direction") or "positive")
    sym = str(params.get("symbol") or "SPY")
    steps = [
        [sys.executable, os.path.join(ROOT, "scripts", "eval_f020.py"),
         "--dump-features", feat],
        [sys.executable, os.path.join(ROOT, "scripts", "factor_backtest_probe.py"),
         "--factor", factor, "--symbol", sym,
         "--direction", direc, "--features", feat],
    ]
    out = []
    for cmd in steps:
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                               timeout=1800)
        except subprocess.TimeoutExpired:
            out.append({"cmd": " ".join(cmd[1:]), "rc": -1,
                        "stdout": "", "stderr": "超过 1800 秒"})
            continue
        # 🔴 probe 判 FAIL 时 exit 1 是**结论**不是崩溃 ✗ ⇒ 不 break ✓
        out.append({"cmd": " ".join(cmd[1:]), "rc": r.returncode,
                    "stdout": (r.stdout or "")[-2000:],
                    "stderr": (r.stderr or "")[-400:]})
    return {"ok": all(x["rc"] in (0, 1) for x in out),
            "factor": factor, "direction": direc, "symbol": sym,
            "note": "⚠️ 裁判 FAIL 时 probe 会 exit 1 —— 那是**结论**不是崩溃 ✓",
            "steps": out}


def _act_fetch_fred(params):
    """抓 FRED 系列 ✓（默认补 **DGS10** —— 它至今从未落盘 ✗）。

    2026-10-30：每日链跑 `fetch_fred --series DFF,DGS10,T10Y2Y`，
    但 `Data/raw/fred_DGS10.csv` **不存在** ✗；因为 `fed` 因子用的是 DFF，
    缺失一直无人发现 ✗。C2（ERP 估值锚）依赖它 ⇒ 需要先补齐 ✓。
    """
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "fetch_fred.py")]
    ser = str(params.get("series") or "DGS10").strip()
    if ser:
        cmd += ["--series", ser]
    if str(params.get("debug") or "") in ("1", "true", "yes"):
        cmd.append("--debug")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1500:], "stderr": (r.stderr or "")[-600:]}


def _act_fetch_pe_ratio(params):
    """抓 S&P500 PE 月度历史 ✓ —— C2「ERP 估值锚」的数据源（`Data/raw/sp500_pe.csv`）。

    2026-10-30：FRED 没有 PE 系列 ✗，仓库也没有任何 PE 历史 ✗
    ⇒ 先解决数据源，再谈 C2 因子 ✓。
    """
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "fetch_pe_ratio.py")]
    if str(params.get("dry_run") or "") in ("1", "true", "yes"):
        cmd.append("--dry-run")
    # 2026-10-30：默认抓 PE + CAPE 两条 ✓（CAPE 作对照，判断「当期 PE 是否被
    # 一次性高盈利压低」✗）；可用 `series=pe|cape` 只抓一条 ✓
    ser = str(params.get("series") or "").strip()
    if ser in ("pe", "cape", "both"):
        cmd += ["--series", ser]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 180 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1500:], "stderr": (r.stderr or "")[-600:]}


def _act_c1_backtest(params):
    """C1 回测裁判（M2.2）✓ —— 两步：把 `baa10y_z` 并入研究 features → 跑 probe。

    2026-10-30：相关性复核**通过**（无 `|ρ|>0.5 且 n≥250` 的列 ⇒ 跳过正交化）✓
    ⇒ 直接进回测裁判 ✓。
    `factor_backtest_probe.py` 只认 features 里的**列** ✗，而 baa10y 在
    `Data/raw/fred_baa10y_avail.csv` ⇒ 先 dump 一份研究专用 features ✓。
    """
    feat = str(params.get("features")
               or "evolution/experiments/factor-adoption/features_c1.csv")
    # 2026-10-30：支持**多组合扫描** ✓（`symbols`/`directions` 逗号分隔）——
    # ⚠️ 这是**多重检验** ✗：同一份数据反复试直到通过 = 过拟合 ✓
    # ⇒ 结果只作**探索性分析**，**不作为采纳依据** ✗（提案里必须写明）
    syms = [x.strip() for x in str(params.get("symbols")
                                   or params.get("symbol") or "TQQQ").split(",")
            if x.strip()]
    dirs = [x.strip() for x in str(params.get("directions")
                                   or params.get("direction") or "positive").split(",")
            if x.strip()]
    sym = syms[0]
    # C1 是**逆向**因子：信用利差高（z 高）= 恐慌 = 看多 ⇒ direction=positive ✓
    direc = dirs[0]
    steps = [[sys.executable, os.path.join(ROOT, "scripts", "eval_baa10y.py"),
              "--dump-features", feat]]
    for s in syms:
        for d in dirs:
            steps.append(
                [sys.executable,
                 os.path.join(ROOT, "scripts", "factor_backtest_probe.py"),
                 "--factor", "baa10y_z", "--symbol", s,
                 "--direction", d, "--features", feat])
    out = []
    for cmd in steps:
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                               timeout=1800)
        except subprocess.TimeoutExpired:
            out.append({"cmd": " ".join(cmd[1:]), "rc": -1,
                        "stdout": "", "stderr": "超过 1800 秒"})
            continue
        # 🔴 probe 判 FAIL 时 **exit 1** ✗ —— 那是**结论**不是崩溃 ✓
        # ⇒ 不能因为 rc!=0 就 break，否则后面的组合全被跳过 ✗
        out.append({"cmd": " ".join(cmd[1:]), "rc": r.returncode,
                    "stdout": (r.stdout or "")[-1800:],
                    "stderr": (r.stderr or "")[-400:]})
    return {"ok": all(x["rc"] == 0 for x in out),
            "combos": len(syms) * len(dirs),
            "warning": "⚠️ 多组合扫描 = 多重检验 ⇒ 仅作探索，不作为采纳依据 ✗",
            "steps": out}


def _act_fetch_shoutu_history(params):
    """抓守猪待兔**服务端历史** ✓ —— 写 `Data/raw/shoutu_history.csv`。

    动机（2026-10-30）：建仓计划回测第一次跑空 ✗ —— 因为它读的是
    `shoutu_fng.csv`（**本地 06:30 采样**，只有近期几十天 ✗）。
    服务端历史（`stock_emotion/history`）才是权威日值 ✓，
    2024-04 起、每只 ~600 天 ✓（AXTX/CRCG 服务端没有 ⇒ 返回空表，不报错 ✓）。
    """
    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "fetch_shoutu_history.py")]
    syms = str(params.get("symbols") or "").strip()
    if syms:
        cmd += ["--symbols", syms]
    if str(params.get("debug") or "") in ("1", "true", "yes"):
        cmd.append("--debug")
    ids = str(params.get("ids") or "").strip()
    if ids:
        cmd += ["--ids", ids]
    if str(params.get("click_tab") or "") in ("1", "true", "yes"):
        cmd.append("--click-tab")
    if str(params.get("capture_all") or "") in ("1", "true", "yes"):
        cmd.append("--capture-all")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-2000:], "stderr": (r.stderr or "")[-500:]}


def _act_backtest_plan(params):
    """在 Mac 上跑**建仓/加仓计划回测** ✓（`shoutu_fng.csv` 只在 Mac 本地 ✗）。

    `symbols` 非空 ⇒ 覆盖默认 6 个标的 ✓；`json` 非空 ⇒ 完整结果落盘 ✓。
    """
    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "backtest_position_plan.py")]
    syms = str(params.get("symbols") or "").strip()
    if syms:
        cmd += ["--symbols", syms]
    out = str(params.get("json") or "").strip()
    if out:
        cmd += ["--json", out if os.path.isabs(out) else os.path.join(ROOT, out)]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-3000:], "stderr": (r.stderr or "")[-500:]}


def _act_key_diag(params):
    """找本机 API key ✓ —— **只回前缀与长度，绝不回明文** ✗。

    动机（2026-10-29）：NIM 免费通道走不通（唯一可用模型卡死、其余 404），
    要切 DeepSeek 官方，但得先确认 key 在哪、是什么结构 ——
    `~/.dsh/.credentials.yaml` 里既有 `nvapi-`（NVIDIA）也可能有 `sk-`（DeepSeek）✗。
    """
    import re

    root = os.path.expanduser(str(params.get("dir") or "~/.dsh"))
    if not os.path.isdir(root):
        return {"ok": False, "reason": "目录不存在：%s" % root}
    pats = {"nvapi": re.compile(r"nvapi-[A-Za-z0-9_\-]{8,}"),
            "sk": re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
            "sk-or": re.compile(r"sk-or-[A-Za-z0-9_\-]{16,}")}
    files, hits, seen = [], [], set()
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for f in names:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            files.append("%s（%d B）" % (rel, sz))
            if sz > 512 * 1024:                 # 大文件（模型/日志）不扫 ✓
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read()
            except OSError:
                continue
            for kind, rx in pats.items():
                for m in rx.finditer(txt):
                    v = m.group(0)
                    sig = (rel, kind, v[:10], len(v))
                    if sig in seen:
                        continue
                    seen.add(sig)
                    hits.append({"file": rel, "kind": kind,
                                 "prefix": v[:10] + "…", "len": len(v)})
    return {"ok": True, "result": {"dir": root,
                                   "files": files[:40],
                                   "hits": hits[:40]}}


def _act_inspect_csv(params):
    """**查任意 CSV 的尾部行 / 指定 symbol** ✓（2026-11-06）。

    🔴 为什么要查 ✗：
       `pipeline.run` 在 Mac 上失败 ✗ 报：
         `DataQualityError: SOXL 2026-11-05: SOXL 收益 -38.70% 与
          3×SOXX 收益 -70.97% 偏离 174.21pp`
       ⇒ **`SOXX` 一天跌 71%** ✗ 不可能 ✗ ⇒ 数据脏了 ✗
       而 **Windows 的 `prices.csv` 只到 10-12** ✗ 看不到 11-05 ✗
       ⇒ 必须从 **Mac** 取 ✓

    参数：`path`（默认 `Data/raw/prices.csv` ✗）、`symbol`（逗号分隔 ✗）、
          `n`（尾部行数 ✗ 默认 5 ✓）
    """
    import pandas as _pd
    path = str(params.get("path") or "Data/raw/prices.csv")
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    n = int(params.get("n") or 5)
    syms = [x.strip().upper() for x in
            str(params.get("symbol") or "").split(",") if x.strip()]

    if not os.path.exists(path):
        return {"ok": False, "error": "文件不存在：%s ✗" % path}
    out = {"path": os.path.relpath(path, ROOT),
           "size_kb": round(os.path.getsize(path) / 1024.0, 1)}
    try:
        d = _pd.read_csv(path)
    except Exception as exc:                # noqa: BLE001
        return {"ok": False, "error": "%s: %s"
                % (type(exc).__name__, str(exc)[:200])}
    out["rows"] = int(len(d))
    out["columns"] = list(d.columns)

    if "symbol" in d.columns and syms:
        out["symbols"] = {}
        for s in syms:
            g = d[d["symbol"].astype(str).str.upper() == s]
            if not len(g):
                out["symbols"][s] = "**不存在** ✗"
                continue
            g = g.sort_values("date").tail(n)
            cols = [c for c in ("date", "close", "open", "high", "low")
                    if c in g.columns]
            out["symbols"][s] = g[cols].to_dict(orient="records")
            # 顺带算最近几天的**日收益** ✓（看跳变 ✗）
            if "close" in g.columns and len(g) > 1:
                r = g["close"].pct_change().dropna()
                out["symbols"][s + "_ret"] = [round(float(x), 4)
                                              for x in r.tail(n - 1)]
    elif "date" in d.columns:
        out["tail"] = d.sort_values("date").tail(n).to_dict(orient="records")
    else:
        out["tail"] = d.tail(n).to_dict(orient="records")
    out["ok"] = True
    return out


def _act_run_pipeline(params):
    """重算 `features.csv`（与每日链**同一条**调用序列 ✓）。

    动机（2026-10-29 实测）：`features.csv` 尾行的 `vix`/`term` 是空 ✗，
    而 `raw/vix.csv`、`raw/prices.csv` 都已到新日期 ✓ ⇒ 说明 pipeline 当时
    **在 vix 数据补齐之前**就跑了，尾行因子只能留空，之后没人重算 ✗。

    🔴 会**覆写** `features.csv` / `portfolio_features.csv` ✗ —— 所以只跑
    与每日链完全相同的三步（不多做、不少做），避免两条口径打架 ✓。
    """
    code = ("from fg_system import pipeline;"
            "pipeline.run(write=True);"
            "us=pipeline.run_equity_v2();"
            "cr=pipeline.run_crypto(write=True);"
            "pipeline.run_portfolio(us, cr, write=True)")
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 1800 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1200:],
            "stderr": (r.stderr or "")[-500:]}


def _act_factor_diag(params):
    """查六因子为什么缺 ✓ —— 只读，报各数据源的尾行日期与近 30 行非空数。

    动机（2026-10-29）：简报里 `VIX — 数据缺失` / `TERM — 数据缺失` ✗，
    但没人知道是 features 没算、还是原始 csv 没更新 ✗ ⇒ 只能上 Mac 查 ✓。
    """
    import pandas as pd

    data = os.path.join(ROOT, "Data")
    out = {}

    def _tail(path):
        try:
            d = pd.read_csv(path, parse_dates=["date"])
            if d.empty:
                return "空文件"
            return "%s（%d 行）" % (d["date"].iloc[-1].date(), len(d))
        except Exception as exc:                   # noqa: BLE001
            return "读不出：%s" % exc

    out["raw/vix.csv"] = _tail(os.path.join(data, "raw", "vix.csv"))
    out["raw/prices.csv"] = _tail(os.path.join(data, "raw", "prices.csv"))
    out["features.csv"] = _tail(os.path.join(data, "features.csv"))

    try:
        f = pd.read_csv(os.path.join(data, "features.csv"), parse_dates=["date"])
        last = f.iloc[-1]
        out["features 尾行"] = {
            c: (None if pd.isna(last.get(c)) else float(last[c]))
            for c in ("fg_index", "vix", "term") if c in f.columns}
        out["features 尾行"]["date"] = str(last["date"].date())
        # 从哪一天开始断的：倒着数连续为空的长度
        for c in ("vix", "term"):
            if c not in f.columns:
                continue
            s = f[c]
            n = 0
            for v in reversed(list(s)):
                if pd.isna(v):
                    n += 1
                else:
                    break
            out["%s 连续缺失" % c] = "%d 行" % n
        out["近30行非空"] = {c: int(f[c].tail(30).notna().sum())
                          for c in ("vix", "term") if c in f.columns}
    except Exception as exc:                       # noqa: BLE001
        out["features 尾行"] = "读不出：%s" % exc

    try:
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "check_freshness.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=180)
        out["check_freshness"] = {"rc": r.returncode,
                                  "out": (r.stdout or "")[-800:]}
    except (subprocess.SubprocessError, OSError) as exc:
        out["check_freshness"] = "执行失败：%s" % exc
    return {"ok": True, "result": out}


def _act_net_probe(params):
    """探「本地代理端口」+「经代理取一次」✓ —— 只读、秒级。

    动机（2026-10-29）：简报两个 LLM 阶段都 `timed out`（不是 connection refused ✗）
    ⇒ 怀疑本地代理（Clash 127.0.0.1:7890）能连上但上游卡住 ✗。
    队列跑在 launchd 里，环境与登录 shell 不同 ✗ ⇒ 只能在 Mac 本地实测 ✓。
    """
    import socket
    import urllib.error
    import urllib.parse
    import urllib.request

    proxy = str(params.get("proxy") or "http://127.0.0.1:7890")
    url = str(params.get("url") or "https://integrate.api.nvidia.com/v1/models")
    out = {"proxy": proxy, "url": url}

    # ① 代理端口能不能连（3 秒）
    u = urllib.parse.urlsplit(proxy)
    t0 = time.time()
    try:
        s = socket.create_connection((u.hostname, u.port or 80), timeout=3)
        s.close()
        out["proxy_port"] = {"ok": True,
                             "ms": int((time.time() - t0) * 1000)}
    except OSError as exc:
        out["proxy_port"] = {"ok": False, "reason": str(exc)}

    # ② 经代理真取一次 ✓
    # `method`/`body`/`auth`/`secs` 可调 —— 2026-10-29 实测 GET 521ms 通、
    # POST chat 60 秒无响应 ✗ ⇒ 必须能**分别**验 GET 与 POST ✗
    method = str(params.get("method") or "GET").upper()
    body = params.get("body")
    secs = int(params.get("secs") or 10)
    headers = {}
    if body is not None:
        body = str(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if str(params.get("auth") or "") in ("1", "true", "yes"):
        try:
            if os.path.join(ROOT, "scripts") not in sys.path:
                sys.path.insert(0, os.path.join(ROOT, "scripts"))
            import invest_research as ir
            # 按 URL 选 key（本地 ⇒ Hermes 的 key）✓ 2026-11-09 统一走 Hermes
            headers["Authorization"] = "Bearer " + (ir._read_llm_key() or "")
        except Exception as exc:                   # noqa: BLE001
            out["auth"] = "读 key 失败：%s" % exc

    t0 = time.time()
    status = None
    try:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method=method)
        with op.open(req, timeout=secs) as r:
            status = r.status
            out["via_proxy"] = {"ok": True, "status": status, "method": method,
                                "ms": int((time.time() - t0) * 1000)}
            # `body_out=1` ⇒ 解析出**模型 id 列表** ✓（不回传原始正文 ✗）
            # 2026-10-29 踩坑：原始正文 3000 字，而 `_write_result` 只留尾部
            # `output[-2000:]` ✗ ⇒ 开头的 `deepseek-ai/*` 正好被截掉 ✗
            # ⇒ 只回「数量 + 按关键词筛过的 id」，几十个字就够 ✓
            if str(params.get("body_out") or "") in ("1", "true", "yes"):
                try:
                    import re
                    n = max(1000, min(int(params.get("body_len") or 20000), 60000))
                    txt = r.read(n).decode("utf-8", "replace")
                    ids = re.findall(r'"id"\s*:\s*"([^"]+)"', txt)
                    kw = str(params.get("models_like") or "deepseek,qwen,llama-3.3")
                    keys = [k.strip().lower() for k in kw.split(",") if k.strip()]
                    out["via_proxy"]["model_count"] = len(ids)
                    out["via_proxy"]["models"] = [
                        i for i in ids
                        if any(k in i.lower() for k in keys)][:40]
                except Exception as exc:           # noqa: BLE001
                    out["via_proxy"]["models"] = "解析失败：%s" % exc
    except urllib.error.HTTPError as exc:
        # 401/404 这类**也是有效情报** ✓ —— 说明链路通、只是鉴权/路径不对 ✓
        out["via_proxy"] = {"ok": False, "status": exc.code, "method": method,
                            "ms": int((time.time() - t0) * 1000),
                            "reason": "HTTP %s" % exc.code}
    except Exception as exc:                       # noqa: BLE001
        out["via_proxy"] = {"ok": False, "status": status, "method": method,
                            "ms": int((time.time() - t0) * 1000),
                            "reason": "%s: %s" % (type(exc).__name__, exc)}

    # ③ `chat=1` ⇒ 真打一次 chat/completions（max_tokens=8）✓
    # 2026-10-29 实测：GET 模型列表 641ms 通，但简报的归因阶段仍 240s 超时 ✗
    # ⇒ 必须区分「网络不通」和「**生成太慢**」✗，只有真打一次才知道 ✓
    if str(params.get("chat") or "") in ("1", "true", "yes"):
        t0 = time.time()
        try:
            if os.path.join(ROOT, "scripts") not in sys.path:
                sys.path.insert(0, os.path.join(ROOT, "scripts"))
            import invest_research as ir
            # `model` 可覆盖 ⇒ 换模型前先单测候选 ✓（2026-10-29）
            reply = ir._chat(ir.NIM_URL, ir._read_llm_key(),
                             str(params.get("model") or ir.NIM_MODEL),
                             "你是连通性探针。", "只回复 OK", max_tokens=8,
                             proxy=ir.PROXY, timeout=60, retries=1)
            out["chat"] = {"ok": True, "ms": int((time.time() - t0) * 1000),
                           "reply": str(reply)[:40]}
        except Exception as exc:                   # noqa: BLE001
            out["chat"] = {"ok": False,
                           "ms": int((time.time() - t0) * 1000),
                           "reason": "%s: %s" % (type(exc).__name__, exc)}

    ok = out["proxy_port"].get("ok") and out["via_proxy"].get("ok")
    if "chat" in out:
        ok = ok and out["chat"].get("ok")
    return {"ok": ok, "result": out}


def _act_eval_baa10y(params):
    """在 Mac 上跑 **C1 信用利差评测** ✓（`fred_baa10y_avail.csv` 只在 Mac 本地 ✗）。

    `orth` 非空 ⇒ 先剔除该列（如 `fed`）再评测 ✓（用户裁定：先正交化再进裁判 ✓）；
    `json` 非空 ⇒ 把完整报告写到该路径（相对路径按仓库根解析 ✓）。
    """
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "eval_baa10y.py")]
    orth = str(params.get("orth") or "").strip()
    if orth:
        cmd += ["--orthogonalize", orth]
    out = str(params.get("json") or "").strip()
    if out:
        cmd += ["--json", out if os.path.isabs(out) else os.path.join(ROOT, out)]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "orth": orth or None,
            "stdout": (r.stdout or "")[-2500:], "stderr": (r.stderr or "")[-500:]}


def _act_run_invest_research(params):
    """跑一次投研简报 ✓ —— 默认 `--dry-run`（不推飞书）✓。

    动机（2026-10-29）：简报连停两天，改完需要**今天就能验证** ✗，
    而不是干等明天 05:30 ✗。`--dry-run` 只写文件 + 打印开头 ⇒ 从结果里
    就能确认「🔌 数据源健康」这节在不在 ✓。要真发：`--param push=1` ✓。
    """
    push = str(params.get("push") or "") in ("1", "true", "yes")
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "invest_research.py")]
    if not push:
        cmd.append("--dry-run")
    try:
        # 🔴 2026-10-29：600 → **900** 秒 ✗ —— 实测一次 dry-run 到 600 秒被杀，
        # 而串行版历史耗时 478 秒（并发版不该更慢）⇒ 说明阶段耗时波动很大 ✗。
        # 与每日链 `run_guarded` 给这步的 900 秒对齐 ✓。
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"
                "（阶段级进度见 daily_log_tail --which invest）"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode, "push": push,
            "stdout": (r.stdout or "")[-1500:], "stderr": (r.stderr or "")[-500:]}


#: 允许 tail 的日志 —— **固定白名单** ✓（不接受任意路径 ✗，否则等于远程读文件 ✗）
#: `evolve_verify` 是**仓库内** logs/ 下的日志（plist 的 StandardOutPath）✓ ——
#: 2026-10-29 加：验证 06:10 那次复检有没有真的带上 `--quiet` ✓
TAIL_LOGS = {
    "daily": "/tmp/fg_daily.log",
    "task_queue": "/tmp/fg_task_queue.log",
    "evolve_verify": os.path.join(ROOT, "logs", "evolve_verify.log"),
    # 2026-10-29：简报阶段级日志 ✓ —— 队列超时杀进程时 stdout 全丢 ✗，
    # 只有这个文件能看出卡在新闻还是某个 LLM 阶段 ✓
    "invest": os.path.join(ROOT, "Data", "health", "invest_stages.log"),
}


def _act_daily_log_tail(params):
    """回传某个运行日志的尾巴 ✓。

    动机（2026-10-29）：简报连续两天没发，只能靠 `/tmp/fg_daily.log` 定位 ✗ ——
    而「让用户去 Mac 上敲命令」违反「Mac 侧操作一律走队列」✗。
    `which` 走白名单，`lines` 上限 200 ✓。
    """
    which = str(params.get("which") or "daily")
    path = TAIL_LOGS.get(which)
    if not path:
        return {"ok": False,
                "reason": "未知日志 %r（可选：%s）" % (which, ", ".join(sorted(TAIL_LOGS)))}
    try:
        n = max(1, min(int(params.get("lines") or 60), 200))
    except (TypeError, ValueError):
        n = 60
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tail = fh.readlines()[-n:]
    except OSError as exc:
        return {"ok": False, "reason": "读不到 %s：%s" % (path, exc)}
    return {"ok": True, "which": which, "path": path,
            "lines": len(tail), "tail": "".join(tail)}


#: 需要 `_tid` 的动作 ✓ —— 只有「结果要延迟回写」的才需要知道自己是哪个任务
#: （`install_daily_plist` 的游离 shell 要把结果写成 `<tid>.reinstall.json` ✓）
NEEDS_TID = {"install_daily_plist"}


#: 🔴 唯一可执行清单。键是**任务名**，值是固定函数 —— 不接受任何命令字符串 ✓
#: 基础环境变量白名单 ✓ —— 动作**只能**看到这些（2026-11-02 用户裁定）
#: 🔴 原来 `subprocess` **继承全部** `os.environ` ✗ ⇒
#:   ① 动作能读到 plist 里所有密钥（`FG_LLM_KEY` / `FEISHU_OPEN_ID` …）✗
#:   ② 而**行为开关**（`FG_SYNC_MODE`）又因为没在 plist 里而丢失 ✗
#:      ⇒ `sync_positions` 跑成 static、什么都没验证 ✗
#: ⇒ 改成「**白名单 + 每动作声明**」✓
#: ⚠️ 只放**无害**的基础项 ✗ —— 绝不放密钥/凭据 ✓
#: （2026-11-02：`HOME` 缺失让富途 SDK 崩过 ✗ ⇒ 一次补全常见项，
#:   避免「报一个补一个」的往返 ✗）
_BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "PYTHONPATH",
             "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE",
             "USER", "LOGNAME", "SHELL", "TERM", "SSH_AUTH_SOCK")

#: 每个动作**额外**可见的环境变量 ✓
#: 值可以是 `set`（按名取 `os.environ`）或 `dict`（显式注入/覆盖）✓
ACTION_ENV = {
    # `sync_positions.py` 默认 static ✗ ⇒ 必须显式 live 才会真调富途/OKX ✓
    "sync_positions": {"FG_SYNC_MODE": "live"},
    # 简报需要：飞书 open_id + LLM 通道配置（plist 里那份）
    "run_invest_research": {
        # ⚠️ **不含 `FG_LLM_KEY`** ✗（2026-11-02 用户裁定）——
        # 简报走**本地 Hermes**（`127.0.0.1:8642`）✓ key 由 Hermes 自己管 ✓
        # ⇒ 脚本不需要拿到明文 key ✗（`_read_llm_key()` 会从 `~/.dsh` 读 ✓）
        "FEISHU_OPEN_ID", "FG_LLM_URL", "FG_LLM_MODEL",
        "FG_LLM_PROXY", "FG_HERMES_URL", "FG_HERMES_MODEL", "FG_PROXY",
    },
    # 日报链里的抓数动作要走代理（`config.PROXY` 读 `FG_PROXY`）
    "fetch_fred": {"FG_PROXY"},
    "fetch_pe_ratio": {"FG_PROXY"},
    "fetch_indices": {"FG_PROXY"},
    "fetch_shoutu_history": {"FG_PROXY"},
}


def _env_for(action):
    """该动作可见的环境变量 ✓（白名单 + 声明）"""
    env = {k: os.environ[k] for k in _BASE_ENV if k in os.environ}
    # 🔴 2026-11-02 实测：launchd 起的队列进程**可能没有 `HOME`** ✗ ——
    # 富途 SDK 硬读 `os.environ['HOME']`（`ft_logger.py:71`）✗
    # ⇒ 直接 `KeyError: 'HOME'` 崩在 import 阶段 ✗
    # （白名单「只拷贝已存在的键」会把这个缺失**放大**成崩溃 ✗）
    # ⇒ 缺失时用 `expanduser("~")` 兜底 ✓
    if "HOME" not in env:
        try:
            env["HOME"] = os.path.expanduser("~")
        except Exception:                   # noqa: BLE001
            pass
    spec = ACTION_ENV.get(action) or ()
    if isinstance(spec, dict):
        env.update({k: str(v) for k, v in spec.items()})
    else:
        for k in spec:
            if k in os.environ:
                env[k] = os.environ[k]
    return env


@contextlib.contextmanager
def _scoped_env(action):
    """执行期间把 `os.environ` **收窄**成该动作的白名单 ✓。

    这样所有 `subprocess.run(...)`（继承 `os.environ`）都自动受限 ✓
    —— 一处改造，26 个调用点全覆盖 ✓（逐个改容易漏 ✗）
    """
    saved = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(_env_for(action))
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _act_run_task_monitor(params):
    """手动跑一次 `scripts/task_monitor.py` ✓（2026-11-09 用户要求）。

    🔴 为什么需要：改了新鲜度白名单后要等下一次定时才生效 ✗
       ⇒ 手动触发一次，直接看判定结果（默认**不推飞书** ✓）

    参数：`push=1` 才带 `--push-alert`
    退出码语义：0 = 全绿；1 = **有异常项**（脚本跑成功了 ✗ 不算任务失败 ✓）
    """
    args = [sys.executable, os.path.join(ROOT, "scripts", "task_monitor.py")]
    if str(params.get("push") or "").lower() in ("1", "true", "yes"):
        args.append("--push-alert")
    try:
        r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "task_monitor 超过 300 秒"}
    return {"ok": r.returncode in (0, 1),          # 1 = 有异常项，不是跑挂
            "rc": r.returncode,
            "stdout": (r.stdout or "")[-3000:],
            "stderr": (r.stderr or "")[-800:]}


def _resolve_llm_key():
    """逐个来源找 LLM key ⇒ `(key, 明细)` ✓（**不再静默吞异常** ✗）。

    2026-11-09 实测：第一次探针 `key_len=0` ✗ 但看不出是「文件不存在」还是
    「文件里没有 sk- key」还是「yaml 没装」✗ ⇒ 现在每个来源都回报状态 ✓
    """
    detail = {}
    key = os.environ.get("FG_LLM_KEY", "")
    detail["env_FG_LLM_KEY"] = bool(key)

    if os.path.join(ROOT, "scripts") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
    for name, fn in (("invest_research._read_nim_key", "_read_nim_key"),
                     ("invest_research._read_hermes_key", "_read_hermes_key")):
        try:
            mod = __import__("invest_research", fromlist=[fn])
            got = getattr(mod, fn)() or ""
            detail[name] = {"ok": bool(got), "len": len(got)}
            if got and not key:
                key = got
        except Exception as exc:            # noqa: BLE001
            detail[name] = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:120])}

    home = os.path.expanduser("~")
    for rel in (".dsh/.credentials.yaml", ".hermes/config.yaml", ".hermes/.env"):
        p = os.path.join(home, rel)
        detail[rel] = {"exists": os.path.exists(p)}
    return key, detail


#: 三个 agent 的候选端点 ✓（2026-11-09 `agent_probe` 实测端口）
#: 用户确认：三个都配的是 **deepseek 云端 deepseek-flash** ⇒ 模型名统一 ✓
AGENT_CANDIDATES = (
    ("hermes", 8642),
    ("dsh", 8326),
    ("openclaw", 18789),
)


def _openclaw_key():
    """从 `~/.openclaw/openclaw.json` 里捞 `sk-` 开头的 key ✓（不打印）。"""
    import glob as _g
    p = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")
    if not os.path.exists(p):
        return ""
    try:
        obj = json.load(open(p, encoding="utf-8", errors="replace"))
    except Exception:                     # noqa: BLE001
        return ""
    found = []

    def walk(d):
        if isinstance(d, dict):
            for v in d.values():
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)
        elif isinstance(d, str) and d.startswith("sk-") and len(d) > 20:
            found.append(d)

    walk(obj)
    return found[0] if found else ""


def _mask(v):
    """脱敏：只回前 4 + 后 4 + 长度 ✓（**绝不回明文** ✗）。"""
    s = str(v)
    if len(s) <= 10:
        return "*" * len(s) + "(%d)" % len(s)
    return "%s…%s(%d)" % (s[:4], s[-4:], len(s))


def _walk_shape(obj, prefix="", out=None, depth=0):
    """把嵌套结构压成 `a.b.c = 脱敏值` 列表 ✓（只收 key/token/url/model 类）。"""
    if out is None:
        out = []
    if depth > 6:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_shape(v, "%s.%s" % (prefix, k) if prefix else str(k), out,
                        depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            _walk_shape(v, "%s[%d]" % (prefix, i), out, depth + 1)
    else:
        low = prefix.lower()
        hit = any(t in low for t in ("key", "token", "secret", "url", "base",
                                     "port", "model", "host", "endpoint",
                                     "provider", "agent"))
        looks_token = isinstance(obj, str) and len(obj) >= 20 and " " not in obj
        if hit or looks_token:
            out.append("%s = %s" % (prefix, _mask(obj)))
    return out


def _act_key_shape_probe(params):
    """**只列键名与脱敏值** ✓ —— 找出 dsh 的 key 到底叫什么（2026-11-09 用户选 A）。

    🔴 背景：`agent_chat_probe` 显示 `dsh` 的 `key_len=0` ✗
       —— 我从 `~/.dsh/.credentials.yaml` 里只找 `sk-` 开头 ✗ 可能前缀不对 ✗
       ⇒ 把**结构与键名**摆出来，绝不回明文 ✓
    """
    import glob as _g

    home = os.path.expanduser("~")
    out = {"files": {}, "dirs": {}}

    # ① 目录清单（只看文件名）
    for rel in (".dsh", ".openclaw", ".hermes"):
        p = os.path.join(home, rel)
        try:
            out["dirs"][rel] = sorted(os.path.basename(x) for x in _g.glob(p + "/*"))
        except Exception as exc:          # noqa: BLE001
            out["dirs"][rel] = {"error": str(exc)[:80]}

    # ② 配置文件结构（脱敏）
    targets = [".dsh/.credentials.yaml", ".dsh/credentials.yaml",
               ".dsh/config.yaml", ".hermes/config.yaml",
               ".openclaw/openclaw.json"]
    for rel in targets:
        p = os.path.join(home, rel)
        if not os.path.exists(p):
            out["files"][rel] = {"exists": False}
            continue
        try:
            raw = open(p, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            out["files"][rel] = {"error": str(exc)[:80]}
            continue
        obj = None
        if rel.endswith(".json"):
            try:
                obj = json.loads(raw)
            except ValueError:
                obj = None
        else:
            try:
                import yaml
                obj = yaml.safe_load(raw)
            except Exception:             # noqa: BLE001
                obj = None
        if obj is None:
            # yaml 不可用时退回：只回**键名**（`k:` 行），不回值 ✓
            names = [ln.split(":")[0].strip() for ln in raw.splitlines()
                     if ":" in ln and not ln.strip().startswith("#")]
            out["files"][rel] = {"exists": True, "parse": "text",
                                 "keys": names[:30]}
        else:
            out["files"][rel] = {"exists": True, "parse": "ok",
                                 "shape": _walk_shape(obj)[:40]}
    out["ok"] = True
    return out


def _act_agent_chat_probe(params):
    """逐个 agent 发一次最小 chat ✓ —— 定死「哪条通道真能用」。

    🔴 用户确认三个 agent 都配 `deepseek-flash` ✗
       ⇒ 模型名统一，只需确认**端点 + key** 是否可用 ✓
       2026-11-09 `agent_probe` 已知端口：hermes 8642 / dsh 8326 / openclaw 18789
    """
    import urllib.error as _ue
    import urllib.request as _u

    model = str(params.get("model") or "deepseek-flash")
    if os.path.join(ROOT, "scripts") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        import invest_research as ir
        keys = {"hermes": ir._read_hermes_key() or "",
                "dsh": ir._read_nim_key() or "",
                "openclaw": _openclaw_key()}
    except Exception as exc:              # noqa: BLE001
        return {"ok": False, "reason": "读 key 失败：%s" % str(exc)[:200]}

    out = {"model": model, "results": {}}
    for name, port in AGENT_CANDIDATES:
        url = "http://127.0.0.1:%d/v1/chat/completions" % port
        key = keys.get(name) or ""
        payload = json.dumps({"model": model,
                              "messages": [{"role": "user", "content": "ping"}],
                              "max_tokens": 8}).encode()
        req = _u.Request(url, data=payload, method="POST",
                         headers={"Authorization": "Bearer %s" % key,
                                  "Content-Type": "application/json"})
        try:
            with _u.urlopen(req, timeout=60) as resp:
                body = resp.read(200).decode("utf-8", "replace")
                out["results"][name] = {"url": url, "key_len": len(key),
                                        "status": resp.status, "body": body}
        except _ue.HTTPError as exc:
            out["results"][name] = {
                "url": url, "key_len": len(key), "status": exc.code,
                "body": exc.read(200).decode("utf-8", "replace")}
        except Exception as exc:          # noqa: BLE001
            out["results"][name] = {"url": url, "key_len": len(key),
                                    "error": "%s: %s" % (type(exc).__name__,
                                                         str(exc)[:120])}
    out["ok"] = True
    return out


def _act_agent_probe(params):
    """发现本机三个 agent（openclaw / deepseek-harness / hermes）的地址与端口 ✓。

    🔴 2026-11-09 用户要求「简报不同模块用不同 agent」✗，但仓库里**只有 hermes
       的 8642** ✗ —— openclaw / dsh 的端口代码里查不到 ✗
       ⇒ 一次探完，避免猜端口（bsk 那 6 轮的教训）✓

    三段：
      ① `lsof` 列本机 LISTEN 端口
      ② 逐个 `GET /v1/models`（2 秒超时）—— 谁回 OpenAI 风格就说明是 agent
      ③ 读 `~/.openclaw/openclaw.json`、`~/.dsh/*.yaml` 里的 url/port 键
    ⚠️ **只回端口与状态**，绝不回 key/secret ✗
    """
    import socket
    import urllib.error as _ue
    import urllib.request as _u

    out = {"listening": [], "probes": {}, "configs": {}}

    # ① 监听端口
    # 🔴 2026-11-09 实测：launchd 的 PATH 里**没有** /usr/sbin ✗ ⇒ `lsof` 找不到 ✗
    #    （回执 `FileNotFoundError: 'lsof'`）⇒ 用绝对路径 + netstat 兜底 ✓
    ports, errs = set(), []
    for cmd in (["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
                ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            for ln in (r.stdout or "").splitlines()[1:]:
                parts = ln.split()
                if len(parts) >= 9:
                    tail = parts[8].rsplit(":", 1)[-1]
                    if tail.isdigit():
                        ports.add(int(tail))
            break
        except Exception as exc:          # noqa: BLE001
            errs.append("%s: %s" % (cmd[0], type(exc).__name__))
    if not ports:                          # 兜底：netstat
        try:
            r = subprocess.run(["netstat", "-an", "-p", "tcp"],
                               capture_output=True, text=True, timeout=20)
            for ln in (r.stdout or "").splitlines():
                if "LISTEN" not in ln:
                    continue
                # macOS 是 `127.0.0.1.8642`，Windows 是 `0.0.0.0:135` ⇒ 两种都认 ✓
                for tok in ln.split()[:5]:
                    m = re.search(r"[:.](\d{2,5})$", tok)
                    if m:
                        ports.add(int(m.group(1)))
                        break
        except Exception as exc:          # noqa: BLE001
            errs.append("netstat: %s" % type(exc).__name__)
    out["listening"] = sorted(ports)
    if errs:
        out["listening_error"] = "; ".join(errs)

    # ② 逐个探 /v1/models（只探本机监听端口，2 秒超时）
    for port in out["listening"]:
        if not (1024 <= port <= 65535):
            continue
        url = "http://127.0.0.1:%d/v1/models" % port
        try:
            with _u.urlopen(url, timeout=2) as resp:
                body = resp.read(300).decode("utf-8", "replace")
                out["probes"][str(port)] = {"status": resp.status, "body": body}
        except _ue.HTTPError as exc:
            out["probes"][str(port)] = {"status": exc.code,
                                        "body": exc.read(200).decode("utf-8",
                                                                     "replace")}
        except Exception as exc:          # noqa: BLE001 —— 不是 HTTP 服务，正常
            out["probes"][str(port)] = {"error": type(exc).__name__}

    # ③ 配置文件里的 url / port（**不取 secret** ✗）
    home = os.path.expanduser("~")
    for rel in (".openclaw/openclaw.json", ".dsh/config.yaml",
                ".dsh/config.yml", ".hermes/config.yaml"):
        p = os.path.join(home, rel)
        if not os.path.exists(p):
            out["configs"][rel] = {"exists": False}
            continue
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            out["configs"][rel] = {"error": str(exc)[:100]}
            continue
        hits = re.findall(r'"?[\w.-]*(?:url|base|endpoint|port|host)'
                          r'"?\s*[:=]\s*"?([^"\s,}]{1,80})', txt, re.I)
        out["configs"][rel] = {"exists": True, "hits": sorted(set(hits))[:12]}
    return out


def _act_deepseek_key_hunt(params):
    """在 Mac 家目录里**找 `sk-` 开头的 key** ✓（2026-11-09 用户选方案 B）。

    🔴 背景：方案 B = 保留 `api.deepseek.com` 直连，但需要有效 key ✗
       `deepseek_probe` 显示 `~/.dsh/.credentials.yaml` 里**没有** `sk-` ✗
       而用户说三个 agent 都配了 DeepSeek 云端 ⇒ key **一定在某个文件里** ✓
       ⇒ 扫一遍候选位置，只回**文件 + 脱敏值 + 长度**，绝不回明文 ✗

    ⚠️ 不扫业务数据目录（`Data/`、`docs/`），只看配置类路径 ✓
    """
    import glob as _g
    import re as _re

    home = os.path.expanduser("~")
    patterns = [
        ".hermes/*.yaml", ".hermes/*.yml", ".hermes/.env", ".hermes/*.json",
        ".hermes/profiles/*", ".dsh/*.yaml", ".dsh/*.yml", ".dsh/*.json",
        ".dsh/profiles/*", ".dsh/openai-gateway/*",
        ".openclaw/*.json", ".openclaw/credentials/*", ".openclaw/agents/*",
        ".config/deepseek/*", ".deepseek/*", ".env", ".zshrc", ".bash_profile",
    ]
    # `sk-` 后至少 16 位字母数字（DeepSeek 官方格式）
    pat = _re.compile(r"sk-[A-Za-z0-9_\-]{16,}")

    hits, scanned = [], []
    for pattern in patterns:
        for path in _g.glob(os.path.join(home, pattern)):
            if not os.path.isfile(path):
                continue
            scanned.append(os.path.relpath(path, home))
            try:
                txt = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in pat.finditer(txt):
                val = m.group(0)
                hits.append({"file": os.path.relpath(path, home),
                             "mask": _mask(val), "len": len(val)})

    # 去重（同一条 key 可能出现在多处）
    seen, uniq = set(), []
    for h in hits:
        if h["mask"] in seen:
            continue
        seen.add(h["mask"])
        uniq.append(h)

    # 环境变量里有没有（只看名字，不回值）
    env_names = [k for k in os.environ
                 if "DEEPSEEK" in k.upper() or k.upper().endswith("_API_KEY")]
    return {"ok": True, "files_scanned": len(scanned), "hits": uniq[:30],
            "hit_count": len(uniq), "env_names": env_names[:20],
            "note": "只回脱敏值；若 hit_count=0 说明 key 不在这些路径"}


def _act_deepseek_probe(params):
    """探 **DeepSeek 云端**：哪个 `model` id 被接受 ✓（2026-11-09 用户要求）。

    🔴 为什么要探：`invest_research` 默认已切到 `api.deepseek.com`，但模型名
       用的是内部约定的 `deepseek/deepseek-flash` ✗ —— 官方只保证
       `deepseek-chat` / `deepseek-reasoner` ✓ ⇒ 必须实测，不能猜 ✗

    参数：`url`（默认官方端点）、`models`（逗号分隔，默认三个候选）
    每个候选只发 `max_tokens=8` 的 ping ⇒ 便宜且快 ✓
    """
    import urllib.error as _ue
    import urllib.request as _u

    url = str(params.get("url") or "https://api.deepseek.com/v1/chat/completions")
    models = [m.strip() for m in str(
        params.get("models")
        or "deepseek/deepseek-flash,deepseek-chat,deepseek-reasoner"
    ).split(",") if m.strip()]

    key, key_detail = _resolve_llm_key()

    out = {"url": url, "key_len": len(key), "key_sources": key_detail,
           "results": {}}
    for model in models:
        payload = json.dumps({"model": model,
                              "messages": [{"role": "user", "content": "ping"}],
                              "max_tokens": 8}).encode()
        req = _u.Request(url, data=payload, method="POST",
                         headers={"Authorization": "Bearer %s" % key,
                                  "Content-Type": "application/json"})
        try:
            with _u.urlopen(req, timeout=60) as resp:
                out["results"][model] = {
                    "ok": True, "status": resp.status,
                    "body": resp.read(300).decode("utf-8", "replace")}
        except _ue.HTTPError as exc:
            out["results"][model] = {
                "ok": False, "status": exc.code,
                "body": exc.read(300).decode("utf-8", "replace")}
        except Exception as exc:            # noqa: BLE001
            out["results"][model] = {"ok": False, "error": str(exc)[:200]}
    out["ok"] = True
    return out


def _act_hermes_probe(params):
    """探本机 **Hermes 网关**（127.0.0.1:8642）✓（2026-11-09 用户要求排查）。

    回答三件事，区分「网关死」和「模型慢」：
      ① TCP 端口通不通
      ② `/v1/models` 是否 200（网关进程活着）
      ③ 最小 chat 请求（max_tokens=8）延迟
    """
    import socket
    import time as _t
    import urllib.error as _ue
    import urllib.request as _u

    base = str(params.get("url") or "http://127.0.0.1:8642").rstrip("/")
    # ⚠️ key 必须与 `evolve_review` 用的**同一把** ✗ ——
    #    2026-11-09 首次探针用了空 key ⇒ 401「Invalid gateway API key」✗ 假阴性 ✗
    key = os.environ.get("API_SERVER_KEY", "")
    if not key:
        try:
            if os.path.join(ROOT, "scripts") not in sys.path:
                sys.path.insert(0, os.path.join(ROOT, "scripts"))
            from evolve_review import HERMES_KEY as _hk     # noqa: E402
            key = _hk or ""
        except Exception:                    # noqa: BLE001
            key = ""
    out = {"url": base, "key_len": len(key)}

    t0 = _t.time()
    sk = socket.socket()
    sk.settimeout(3)
    try:
        sk.connect(("127.0.0.1", 8642))
        out["tcp"] = {"ok": True, "ms": round((_t.time() - t0) * 1000)}
    except OSError as exc:
        out["tcp"] = {"ok": False, "error": str(exc)[:120]}
    finally:
        sk.close()

    def _call(path, payload=None, timeout=120):
        t = _t.time()
        try:
            req = _u.Request(base + path, data=payload, method="POST" if payload else "GET",
                             headers={"Authorization": "Bearer %s" % key,
                                      "Content-Type": "application/json"})
            with _u.urlopen(req, timeout=timeout) as r:
                return {"ok": True, "status": r.status,
                        "ms": round((_t.time() - t) * 1000),
                        "body": r.read(400).decode("utf-8", "replace")}
        except _ue.HTTPError as exc:
            return {"ok": False, "status": exc.code,
                    "ms": round((_t.time() - t) * 1000),
                    "body": exc.read(400).decode("utf-8", "replace")}
        except Exception as exc:            # noqa: BLE001
            return {"ok": False, "ms": round((_t.time() - t) * 1000),
                    "error": str(exc)[:200]}

    out["models"] = _call("/v1/models", timeout=10)
    # 只生成 8 token ⇒ 若这里就慢/超时，说明是模型侧而不是网关
    payload = json.dumps({"model": "hermes-agent",
                          "messages": [{"role": "user", "content": "ping"}],
                          "max_tokens": 8}).encode()
    out["chat"] = _call("/v1/chat/completions", payload, timeout=120)
    # ⚠️ `ok` 表示**探针跑完了**（不是「网关可用」✗）—— 缺它队列会把任务判 failed ✗
    out["ok"] = True
    return out


def _act_bsk_probe(params):
    """跑 `scripts/bsk_probe.py` ⇒ **一次**拿到 bsk 控制上下文的全部事实 ✓。

    动机：`fetch_shoutu_history` 连挂 5 轮，每轮只带回一条错误 ✗
    ⇒ 用户要求「避免在 Mac 上反复重试」✗ ⇒ 改成一次跑完全部候选调用 ✓
    """
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "bsk_probe.py")],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "bsk_probe 超过 600 秒"}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-4000:],
            "stderr": (r.stderr or "")[-800:]}


def _act_render_probe(params):
    """渲染一次仪表盘并回传**完整 traceback** ✓（2026-11-06）。

    动机：服务端 500 只回 `type: message` ✗ ⇒
    「must be real number, not complex」查了整轮才定位到 `leverage._annualize` ✗
    ⇒ 队列直接跑一次，栈一起带回来 ✓
    """
    import traceback
    out = {"ok": True}
    try:
        from fg_system.dashboard.server import render_dashboard
        html = render_dashboard()
        out["html_len"] = len(html)
        out["loss_block_ok"] = "损耗归因不可用" not in html
    except Exception as exc:                     # noqa: BLE001
        out["ok"] = False
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        out["traceback"] = traceback.format_exc()[-4000:]
    return out


def _act_restart_dashboard(params):
    """重启仪表盘 launchd 服务并自检首页 ✓（2026-11-06）。

    🔴 为什么必须重启：**刷新页面不会重载 Python 模块** ✗ ——
    代码入库后不重启，进程里还是旧模块（实测：修完 complex 仍报同一个错 ✗）。
    重启后**再探一次首页** ✓ 才算验证通过（只 `kickstart` 不看结果等于没验 ✗）。
    """
    import subprocess as _sp
    import time as _t
    import urllib.error as _ue
    import urllib.request as _u

    label = str(params.get("label") or "com.xingguo.fg-dashboard")
    url = str(params.get("url") or "http://127.0.0.1:8000/")
    uid = os.getuid() if hasattr(os, "getuid") else 501
    try:
        r = _sp.run(["launchctl", "kickstart", "-k", "gui/%s/%s" % (uid, label)],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=30)
    except (OSError, _sp.SubprocessError) as exc:
        return {"ok": False, "reason": "launchctl 失败：%s" % exc}
    out = {"ok": r.returncode == 0, "rc": r.returncode,
           "stderr": (r.stderr or "").strip()[-300:]}

    # 冷启动要跑一次全量渲染（实测近 1 分钟）⇒ 最多等 90 秒
    for _ in range(45):
        _t.sleep(2)
        try:
            with _u.urlopen(url, timeout=15) as resp:
                body = resp.read(4000).decode("utf-8", "replace")
                out.update(http=resp.status, render_error="渲染失败" in body,
                           html_len=len(body))
                return out
        except _ue.HTTPError as exc:          # 500 也算「起来了」，要拿错误正文
            body = exc.read(4000).decode("utf-8", "replace")
            out.update(http=exc.code, render_error="渲染失败" in body,
                       body=body[:1200])
            return out
        except Exception as exc:              # noqa: BLE001 —— 还没起来，继续等
            out["last_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    out["ok"] = False
    return out


def _act_run_pytest(params):
    """跑指定测试文件并回传尾部输出 ✓（参数 `files`，逗号分隔，默认全量）。"""
    files = [x.strip() for x in str(params.get("files") or "tests/").split(",")
             if x.strip()]
    try:
        r = subprocess.run([sys.executable, "-m", "pytest"] + files + ["-q"],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "pytest 超过 900 秒"}
    tail = (r.stdout or "").strip().splitlines()[-40:]
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "failed": [ln for ln in tail if ln.startswith("FAILED")],
            "tail": "\n".join(tail)}


ACTIONS = {
    "key_shape_probe": _act_key_shape_probe,
    "agent_chat_probe": _act_agent_chat_probe,
    "agent_probe": _act_agent_probe,
    "run_task_monitor": _act_run_task_monitor,
    "deepseek_key_hunt": _act_deepseek_key_hunt,
    "deepseek_probe": _act_deepseek_probe,
    "hermes_probe": _act_hermes_probe,
    "bsk_probe": _act_bsk_probe,
    "restart_dashboard": _act_restart_dashboard,
    "render_probe": _act_render_probe,
    "run_pytest": _act_run_pytest,
    "cleanup_backlog": _act_cleanup_backlog,
    "sync_runtime": _act_sync_runtime,
    "git_pull": _act_git_pull,
    "safe_pull_data": _act_safe_pull_data,
    "inspect_sync": _act_inspect_sync,
    "archive_briefs": _act_archive_briefs,
    "weekly_review": _act_weekly_review,
    "diagnose_data": _act_diagnose_data,
    "run_fetch_step": _act_run_fetch_step,
    "update_crypto": _act_update_crypto,
    "bsk_update": _act_bsk_update,
    "restart_queue": _act_restart_queue,
    "analyze_png": _act_analyze_png,
    "probe_url": _act_probe_url,
    "test_futu_fed": _act_test_futu_fed,
    "rerun_brief": _act_rerun_brief,
    "verify_hypotheses": _act_verify_hypotheses,
    "inspect_snapshots": _act_inspect_snapshots,
    "diagnose_symbols": _act_diagnose_symbols,
    "fetch_prices": _act_fetch_prices,
    "audit_data": _act_audit_data,
    "diag_daily_log": _act_diag_daily_log,
    "prune_dead_data": _act_prune_dead_data,
    "clean_sync_partial": _act_clean_sync_partial,
    "daily_log_tail": _act_daily_log_tail,
    "install_evolve_tasks": _act_install_evolve_tasks,
    "futu_preflight": _act_futu_preflight,
    "run_invest_research": _act_run_invest_research,
    "install_daily_plist": _act_install_daily_plist,
    "eval_baa10y": _act_eval_baa10y,
    "net_probe": _act_net_probe,
    "factor_diag": _act_factor_diag,
    "run_pipeline": _act_run_pipeline,
    "inspect_csv": _act_inspect_csv,
    "c1_backtest": _act_c1_backtest,
    "c5_backtest": _act_c5_backtest,
    "f_factor_backtest": _act_f_factor_backtest,
    "factor_reduce_probe": _act_factor_reduce_probe,
    "fetch_pe_ratio": _act_fetch_pe_ratio,
    "fetch_fred": _act_fetch_fred,
    "fetch_indices": _act_fetch_indices,
    "sync_positions": _act_sync_positions,
    "key_diag": _act_key_diag,
    "backtest_plan": _act_backtest_plan,
    "fetch_shoutu_history": _act_fetch_shoutu_history,
}


#: **优先执行**的 action（重启类）—— 见 `_load_pending` 的排序说明。
PRIORITY_ACTIONS = ("restart_dashboard", "restart_queue")


def _load_pending():
    """列出待执行任务（status=pending）：**重启类优先**，其余按 id 升序。"""
    out = []
    if not os.path.isdir(QUEUE):
        return out
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".json") or name.endswith(".result.json"):
            continue
        p = os.path.join(QUEUE, name)
        try:
            with open(p, encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError) as exc:
            # 🔴 2026-10-29 实测：一个被写坏的 json（文件末尾粘了 patch 头 ✗）
            # 会被**每轮静默跳过** ✗ ⇒ 任务永久饿死、且没人知道 ✗
            # ⇒ 打一行警告并改名成 `.broken`（不再匹配 *.json，不再空转）✓
            print("[warn] 任务文件读不出，已隔离为 .broken：%s（%s）"
                  % (name, exc))
            try:
                os.replace(p, p + ".broken")
            except OSError:
                pass
            continue
        if str(spec.get("status") or "pending") != "pending":
            continue
        spec["_path"] = p
        tid = str(spec.setdefault("id", name[:-5]))
        # 已有 result ⇒ 不再执行 ✓ —— 原任务文件里的 status 永远是 pending（我们不回写它），
        # launchd 每 10s 扫一次会**重复执行** ✗（2026-10-28 测试抓到的真 bug）
        if os.path.exists(os.path.join(QUEUE, tid + ".result.json")):
            continue
        out.append(spec)
    # 🔴 2026-10-29：按 **id** 排序（先进先出）✗ —— id 是
    # `t-YYYYmmdd-HHMMSS-<action>`，字典序**恒等于**时间序 ✓；
    # 而 `created_at` 可能缺失/手写错误（缺失会排最前，抢跑 ✗）。
    # 🔴 2026-11-06：**重启类提到队首** ✓ —— 队列是串行的，而 `fetch_prices`
    #    的 timeout 是 1800 秒 ✗ ⇒ 排在它后面的 `restart_dashboard` 白等 16 分钟 ✗
    #    （实测：12:40 下发，13:55 才执行 ✗）。重启只要几秒且决定页面能不能用 ✓
    out.sort(key=lambda s: (0 if str(s.get("action") or "") in PRIORITY_ACTIONS
                            else 1, str(s.get("id") or "")))
    return out


def _write_result(spec, status, rc, output, started, finished):
    rec = {
        "id": spec["id"],
        "action": spec.get("action"),
        "params": spec.get("params") or {},
        "status": status,
        "rc": rc,
        # 🔴 2026-11-03：2000 → **8000** ✗ —— 实测 `audit_data` 的 JSON
        #    在 2000 处被**从中间切断** ⇒ `json.loads` 直接失败 ✗
        #    ⇒ 结果「看得见但解析不了」✗（`ok: None` 就是这个症状 ✗）
        #    ⚠️ 仍有上限 ✗ —— 超长输出请让动作**自己精简** ✓（见 `_act_audit_data`）
        "output": output[-8000:],
        "started_at": started,
        "finished_at": finished,
        "duration_s": round(time.time() - spec.get("_t0", time.time()), 2),
    }
    p = os.path.join(QUEUE, spec["id"] + ".result.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return p


def _auto_clean():
    """每轮顺手自愈：插件层堆积超阈值就归档（2026-10-28 A 方案）。

    为什么不做成「下发任务」：这是**周期性自愈**，不是一次性动作 ——
    每 10s 跑一次、超阈值才动，不需要人记得下发 ✓。
    为什么还要保留手动按钮：自愈是兜底，手动是「我现在就想清」。
    """
    try:
        from fg_system.dashboard import sync_health as sh
        if sh._bypass_stats(time.time())["count"] < sh.BACKLOG_WARN:
            return None
        return sh.archive_backlog()
    except Exception:
        return None            # 自愈失败绝不能影响正常任务 ✓


#: 队列里只留最近这么多个**已完成**任务 ✓（每个任务两个 json，不清理会无限涨 ✗）
KEEP_TASKS = 10


def _task_ids():
    """`{id: [文件路径…]}` —— 一个任务是 `<id>.json` + `<id>.result.json` 两个文件 ✓。"""
    out = {}
    for p in glob.glob(os.path.join(QUEUE, "*.json")):
        base = os.path.basename(p)
        tid = (base[:-len(".result.json")] if base.endswith(".result.json")
               else base[:-len(".json")])
        out.setdefault(tid, []).append(p)
    return out


#: 「正在执行」标记后缀 —— **旁路文件，不写回任务 json** ✗
#: 为什么不在 json 里写 status=running：进程若中途被杀，json 会永远停在 running ✗
#: ⇒ `_load_pending` 再也不认领它 ⇒ 任务永远不执行 ✗（比显示不准严重得多 ✗）。
#: 旁路标记最坏只是看板显示「执行中」到超时 ✓。
RUNNING_SUFFIX = ".running"
#: 标记超过这么久 ⇒ 视为**残留**（进程已死），看板不再显示执行中 ✓
RUNNING_STALE_SEC = 1200


def _running_path(tid):
    return os.path.join(QUEUE, tid + RUNNING_SUFFIX)


def _mark_running(tid):
    try:
        with open(_running_path(tid), "w", encoding="utf-8") as fh:
            json.dump({"started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, fh)
    except OSError:
        pass


def _clear_running(tid):
    try:
        os.remove(_running_path(tid))
    except OSError:
        pass


def _prune_queue(keep=KEEP_TASKS):
    """只留最近 `keep` 个**已完成**任务 ✓，返回被删文件名列表。

    🔴 未完成的任务（没有 `.result.json`）**一律不删** ✗ —— 删了就永远不会执行 ✗。
    id 形如 `t-YYYYmmdd-HHMM-<action>` ⇒ 字典序即时间序 ✓。
    """
    ids = _task_ids()
    pending = {t for t, ps in ids.items()
               if not any(p.endswith(".result.json") for p in ps)}
    done = sorted((t for t in ids if t not in pending), reverse=True)
    dropped = []
    for tid in done[max(0, keep - len(pending)):]:
        for p in ids[tid]:
            try:
                os.remove(p)
                dropped.append(os.path.basename(p))
            except OSError:
                pass
    return dropped


def _collect_reinstall():
    """把「延迟重装」的结果并回任务结果 ✓，返回被更新的任务 id 列表。

    2026-10-29：`install_daily_plist` 对队列作业只能**延迟 8 秒**重装（当场 bootout
    会把自己杀掉 ✗）⇒ 它返回的 `ok:true` 只代表**拷贝成功**，重装成没成无人回收 ✗。
    现在那个游离 shell 把结果写进 `<tid>.reinstall.json` ✓，这里下一轮读回来：
    ① 打印一行到 `/tmp/fg_task_queue.log`；② 回写进 `<tid>.result.json` 的
    `reinstall` 字段（看板可见 ✓）；③ 删掉标记 ✓。
    """
    changed = []
    if not os.path.isdir(QUEUE):
        return changed
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".reinstall.json"):
            continue
        tid = name[:-len(".reinstall.json")]
        mp = os.path.join(QUEUE, name)
        try:
            with open(mp, encoding="utf-8") as fh:
                mark = json.load(fh)
        except (OSError, ValueError):
            mark = {"ok": False, "reason": "标记文件读不出"}
        rp = os.path.join(QUEUE, tid + ".result.json")
        try:
            with open(rp, encoding="utf-8") as fh:
                res = json.load(fh)
            res["reinstall"] = mark
            with open(rp, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=2)
            changed.append(tid)
            print("[reinstall] %s %s（rc=%s）"
                  % (tid, "重装成功 ✓" if mark.get("ok") else "重装**失败** ✗",
                     mark.get("rc")))
        except (OSError, ValueError) as exc:
            print("[warn] 重装结果回写失败（%s）：%s" % (tid, exc))
        try:
            os.remove(mp)
        except OSError:
            pass
    return changed


#: 补推节流：launchd 每 10s 一轮，失败时别把日志刷爆 ✗
_PUSH_RETRY = {"ts": 0.0}


def _try_push_pending(interval=300):
    """有未推送提交就顺手补推一次 ✓ —— 上次推送失败后**自愈** ✓。

    动机（2026-10-29 实测 ✗）：launchd 的 PATH 里没有 `/opt/homebrew/bin` ✗
    ⇒ 凭据助手 `gh auth git-credential` 找不到 gh ✗ ⇒ `git push` rc=128 ✗
    ⇒ 任务结果提交了却推不上去，只能等别的进程捎带 ✗（结果总是「晚到」✗）。
    """
    now = time.time()
    if now - _PUSH_RETRY["ts"] < interval:
        return
    _PUSH_RETRY["ts"] = now
    try:
        r = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return                      # 没有上游 / 不是仓库 ⇒ 静默跳过 ✓
        if int((r.stdout or "0").strip() or 0) <= 0:
            return                      # 没有待推提交 ✓
        p = subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
        if p.returncode == 0:
            print("[push] 补推成功（之前失败的提交已同步）")
        else:
            print("[warn] 补推仍失败（rc=%s）：%s"
                  % (p.returncode, (p.stderr or "").strip()[-200:]))
    except (subprocess.SubprocessError, OSError, ValueError):
        pass


def run_once(commit=True):
    """跑一轮。返回 [(id, status), ...]。"""
    _try_push_pending()
    # 上一轮「延迟重装」的结果在这轮收 ✓（顺带把结果并进任务结果文件 ✓）
    reinstalled = _collect_reinstall()
    auto = _auto_clean()
    if auto and auto.get("moved"):
        print("[auto-clean] 已归档 %d 个插件层文件 -> %s"
              % (auto["moved"], auto.get("dest")))
    done = []
    for spec in _load_pending():
        action = str(spec.get("action") or "")
        fn = ACTIONS.get(action)
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        spec["_t0"] = time.time()
        if fn is None:
            # 未知 action ⇒ 明确失败，不静默跳过 ✓（否则下发方以为在排队）
            # 🔴 2026-11-02 实测：最常见的原因是**代码还没入库** ✗ ——
            # 任务 json 和代码分两个包发，若任务 id 早于代码包入库时间，
            # 队列会先用**旧版** `ACTIONS` 跑 ⇒ 报「未知 action」✗
            # （`t-20261102-152253-bsk_status` 就是这么失败的 ✗）
            # ⇒ 提示里必须写清这条，否则看起来像「动作名拼错」✗
            _write_result(spec, "failed", -1,
                          "未知 action：%s（白名单：%s）\n"
                          "⚠️ 若该动作**刚加进代码**：多半是**代码包还没入库** ✗ "
                          "—— 任务 json 与代码分两个包发时，"
                          "必须**先确认代码入库**再下发任务 ✓"
                          % (action, ", ".join(sorted(ACTIONS))),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "failed"))
            continue
        # 2026-10-29：执行期打「运行中」旁路标记 ✓ —— 否则 8 分钟的简报任务
        # 在看板上一直显示「排队中」，用户以为卡住了 ✗
        _mark_running(spec["id"])
        try:
            # `_tid` 只给**声明需要**的动作（见 `NEEDS_TID`）✓ —— 全局注入会污染
            # 其它动作的 params（有测试锁着「动作收到的就是下发的那份」✗）
            _params = dict(spec.get("params") or {})
            if action in NEEDS_TID:
                _params.setdefault("_tid", spec["id"])
            # 🔴 2026-11-02：**环境变量白名单** ✓ —— 执行期间 `os.environ`
            # 被收窄成该动作声明的集合 ✗ ⇒ 动作读不到无关密钥 ✓
            with _scoped_env(action):
                r = fn(_params)
            ok = bool(r.get("ok")) if isinstance(r, dict) else True
            _write_result(spec, "done" if ok else "failed",
                          0 if ok else 1,
                          json.dumps(r, ensure_ascii=False),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "done" if ok else "failed"))
        except Exception as exc:      # noqa: BLE001 —— 任何异常都要留痕，不能静默 ✗
            _write_result(spec, "failed", -1,
                          "%s: %s" % (type(exc).__name__, exc),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "failed"))
        finally:
            _clear_running(spec["id"])

    # 只有重装结果回写、没有新任务时也要提交 ✓（否则结果永远留在 Mac 本地 ✗）
    if commit and (done or reinstalled):
        if done:
            # 2026-10-29：顺带瘦身 ✓ —— 每个任务两个 json 永不清理会无限涨 ✗
            dropped = _prune_queue()
            if dropped:
                print("[prune] 清理 %d 个旧任务文件（只留最近 %d 个）"
                      % (len(dropped), KEEP_TASKS))
        _git_commit(done or [(t, "reinstall") for t in reinstalled])
    return done


#: 任务会写出的**产物目录** ✓ —— 只提交这些，**绝不用 `git add -A`** ✗
#: （Mac 上常年有测试产物/临时文件 ✗）
#: 2026-10-30 实测教训：`factor_backtest_probe --json evolution/...` 写的裁判
#: 产物**没进 git** ✗ ⇒ Windows 端只能看到被 `output[-2000:]` 截断的 stdout ✗
TASK_OUTPUT_DIRS = ("evolution/experiments/factor-adoption",)

#: 🔴 每日链的 `evolve_*` 会**改写**这些登记表 ✗ —— 队列不提交就会让 Mac 侧
#: 永远留一份「未提交修改」⇒ 之后任何对它们的 patch 都报**冲突中止** ✗
#: （2026-10-30 实测：`sync_1028dn` 因 `evolution/hypotheses.md` 冲突入库失败 ✗）
TASK_OUTPUT_FILES = ("evolution/hypotheses.md",
                     "evolution/factors.md",
                     "evolution/hypothesis_results.md")
# 🔴 2026-11-03 移除：`Data/raw/sp500_pe.csv` / `sp500_cape.csv` /
#    `fred_DGS10.csv` 曾在这里 ✗（2026-10-30 为让 Windows 看到 C2 数据 ✗）
#    但 2026-11-03 用户裁定「数据不入库」⇒ `Data/raw/` 已进 `.gitignore` ✗
#    ⇒ 这几个路径**会被 git 拒绝** ✗ 而 `_git_commit` 的 `git add` 用了
#       `check=True` ✗ ⇒ **抛异常 ⇒ 整个提交（含 `docs/task-queue` 的结果）
#       全被跳过** ✗
#    ⇒ 现象：Mac 上任务跑了、页面显示失败 ✗ 但 gitee 上**没有任何 result** ✗
#    （用户 2026-11-03 反馈的正是这个 ✗）


def _git_commit(done):
    """提交 `docs/task-queue/` + **任务产物目录** ✓ —— 不碰其他脏文件 ✗。"""
    try:
        paths = ["docs/task-queue"] + [
            d for d in TASK_OUTPUT_DIRS
            if os.path.isdir(os.path.join(ROOT, d))] + [
            f for f in TASK_OUTPUT_FILES
            if os.path.isfile(os.path.join(ROOT, f))]
        # 🔴 2026-11-03：**不能 `check=True`** ✗ —— 只要有一个路径被
        #    `.gitignore` 拒绝（如 `Data/raw/*` ✗），git 就**整体失败** ✗
        #    ⇒ 连 `docs/task-queue` 的结果都提交不了 ✗
        #    ⇒ 改为：**逐个 add** ✓ 失败的单独报警但不中断 ✓
        bad = []
        for pth in paths:
            r = subprocess.run(["git", "add", "--", pth], cwd=ROOT,
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                bad.append((pth, (r.stderr or "").strip()[:120]))
        if bad:
            print("[warn] 以下路径 add 失败（其余照常提交 ✓）：")
            for pth, err in bad:
                print("   %s —— %s" % (pth, err))
        msg = "task: %s" % "; ".join("%s=%s" % (i, s) for i, s in done)
        r = subprocess.run(["git", "commit", "-m", msg], cwd=ROOT,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:          # 无变更可提交 ⇒ 不是错误 ✓
            return
        p = subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
        # 🔴 推送失败**必须留痕** ✗ —— 原来 `except: pass` 把一切吞掉 ⇒
        # 结果文件只躺在 Mac 本地，Windows 端永远看不到任务结果 ✗
        # （2026-10-28 实测：`t-…-clean_sync_partial.result.json` 至今没进 gitee ✗）
        # 日志落在 plist 的 StandardOutPath `/tmp/fg_task_queue.log` ✓。
        if p.returncode != 0:
            print("[warn] 结果已提交但**推送失败**（rc=%s）：%s"
                  % (p.returncode, (p.stderr or "").strip()[-200:]))
    except (subprocess.SubprocessError, OSError) as exc:
        # 失败不影响任务本身的结果文件 ✓，但必须可查 ✗
        print("[warn] 结果提交/推送失败：%s" % exc)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mac 侧任务队列执行器")
    ap.add_argument("--no-commit", action="store_true", help="只执行不提交（调试）")
    args = ap.parse_args(argv)
    done = run_once(commit=not args.no_commit)
    for i, s in done:
        print("%s -> %s" % (i, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
