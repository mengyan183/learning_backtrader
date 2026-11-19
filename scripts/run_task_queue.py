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

#: 🔴 动作侧基础设施在 `queue_core.py` ✓（2026-11-19 第三轮抽出）
#:   下一步按 8 个包拆 action 时，包与调度器共用这一层，避免互相 import 成环 ✓
#:   这里用**别名导入** ⇒ `q._run` / `q._safe_rel` 等旧名字仍然可用（测试靠它 patch）✓
#: ⚠️ 看板是 `from scripts import run_task_queue` 导入的 ✗ —— 那种方式下
#:   `scripts/` 不一定在 `sys.path` ⇒ `import queue_core` 会 ModuleNotFoundError ✗
#:   ⇒ 先把自己所在目录塞进去，两种 import 方式都成立 ✓
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import queue_core as _qc                                          # noqa: E402
from queue_core import (ROOT, BSK_BIN, READ_ALLOW as _READ_ALLOW,  # noqa: E402
                        run as _run, safe_rel as _safe_rel,
                        allow_json as _allow_json, rel_ok as _rel_ok,
                        script_allowed as _script_allowed,
                        tail_logs as _tail_logs,
                        task_outputs as _task_outputs)
from queue_actions.futu import ACTIONS as _FUTU_ACTIONS          # noqa: E402
#: `agent_status` / `install_agent` **不是 action**（看板调的）✓
#: ⇒ re-export 保持 `from scripts import run_task_queue` 的调用方不变 ✓
from queue_actions.launchd import (ACTIONS as _LAUNCHD_ACTIONS,   # noqa: E402
                                   agent_status, install_agent)
from queue_actions.diag import ACTIONS as _DIAG_ACTIONS          # noqa: E402
from queue_actions.git import ACTIONS as _GIT_ACTIONS            # noqa: E402
from queue_actions.data import ACTIONS as _DATA_ACTIONS          # noqa: E402

QUEUE = os.path.join(ROOT, "docs", "task-queue")


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
        r = _run(cmd, 600)
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
        r = _run(cmd, 600)
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
    r = _run(cmd, 1800)
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
        r = _run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.'); "
             "from fg_system import pipeline; pipeline.run(write=True)"],
            900)
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
    r = _run(cmd, 1200)
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


def _act_verify_hyp(params):
    """跑 `verify_hypotheses.py` 验证**指定假说** ✓（2026-11-13 用户要求）

    🔴 背景：`hypotheses.md` 里有 **10 条「有 handler 但状态还是 open/verifying」** ✗
       （H-009/H-011/H-017/H-022/H-028/H-031/H-038/H-042/H-049/H-085）
       怀疑是 `evolve_review` 的 LLM 超时导致日更停摆 ⇒ 状态没落盘 ✗
       ⇒ 手动跑一次，看是「insufficient」还是「false」还是「根本没执行」✓

    用法：`--param ids=H-009,H-011,H-017`
    """
    ids = params.get("ids") or []
    if isinstance(ids, str):
        ids = [x.strip() for x in ids.replace("，", ",").split(",") if x.strip()]
    if not ids:
        return {"ok": False,
                "error": "缺 params.ids（如 `ids=H-009,H-011`）"}
    py = sys.executable or "python3"
    cmd = [py, os.path.join(ROOT, "scripts", "verify_hypotheses.py")]
    for h in ids:
        cmd += ["-H", h]
    try:
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "ids": ids, "error": "verify_hypotheses 超时（900s）"}
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return {"ok": r.returncode == 0, "ids": ids, "rc": r.returncode,
            "stdout": out[-4000:]}


#: 允许删除的**遗留文件白名单** ✓（防任意路径删除 ✗）
_LEGACY_FILES = {
    # 🔴 2026-11-13 用户确认：hermes 已改付费 `deepseek-flash`，
    #    `our-free-model` 这个免费模型目录整体废弃 ✗
    #    ⇒ 该文件不再刷新是**预期**，之前被误当成 `dsh.web` 的心跳 ✗
    "free_model_availability": "~/.dsh/our-free-model/availability.json",
}


def _act_rm_legacy(params):
    """删除**白名单内**的遗留文件 ✓（2026-11-13 用户要求）

    🔴 为什么需要：`~/.dsh/our-free-model/availability.json` 是
       免费模型时代的遗留 ✗ —— hermes 已改付费 `deepseek-flash` ✓
       它留在磁盘上会被误当成「服务心跳」，之前就害得 `dsh.web` 误报 ✗

    ⚠️ **只允许 `_LEGACY_FILES` 白名单** ✗ —— 不接受任意路径 ✓
    """
    import glob as _g
    key = str(params.get("key") or "free_model_availability")
    rel = _LEGACY_FILES.get(key)
    if not rel:
        return {"ok": False,
                "error": "未知 key `%s`（白名单：%s）"
                         % (key, "、".join(sorted(_LEGACY_FILES)))}
    p = os.path.expanduser(rel)
    out = {"key": key, "path": p, "steps": {}}
    try:
        if os.path.exists(p):
            os.remove(p)
            out["steps"]["removed"] = True
        else:
            out["steps"]["removed"] = False
            out["steps"]["note"] = "文件本来就不存在 ✓"
    except OSError as exc:
        return {"ok": False, "error": "删除失败：%s: %s"
                                     % (type(exc).__name__, str(exc)[:200])}
    # 目录若已空 ⇒ 一并删掉（`our-free-model` 整个模块都废弃了）
    d = os.path.dirname(p)
    try:
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            out["steps"]["dir_removed"] = d
    except OSError:
        pass
    # 附带确认：还有没有别的残留
    out["steps"]["leftover"] = [os.path.basename(x) for x in
                                _g.glob(os.path.join(d, "*"))][:10]
    out["ok"] = True
    return out


def _compute_gold_ratio(root, pd):
    """F-021：`GDX/GLD` 的 **120 日滚动分位** ✓（`factors/gold_ratio.py`）"""
    sys.path.insert(0, root)
    from fg_system.factors import gold_ratio as _gr
    prices = pd.read_csv(os.path.join(root, "Data", "raw", "prices.csv"))
    sdf = _gr.gold_ratio_pct(prices).to_frame(name="gold_ratio").reset_index()
    sdf.columns = ["date", "gold_ratio"][:len(sdf.columns)]
    sdf["date"] = sdf["date"].astype(str).str[:10]
    return sdf


def _compute_f012(root, pd):
    """F-012：VIX 期限结构 `vix/vix3m` 的 **5 日变化率** ✓

    判据来源 `evolution/factors.md` 原文：
      「波动率结构（VIX 期限结构 term=vix3m/vix 的滚动变化率）」
      「2026-11-02 重测…**方向改为「正向」** ✓…统一用 `vix/vix3m` 的 N 日变化率」
      「N=5：+0.308/+0.403/+0.236/**+0.668**（5/10/20/40）…⇒ **定 N=5** ✓」

    ⚠️ 与 `features.csv` 的 `term` 列**不是一回事** ✗ ——
       `term` 是 `vix3m/vix` 的**水平** ✗；本因子要的是 `vix/vix3m` 的**变化率** ✓
    数据：`Data/raw/vix.csv` + `Data/raw/vix3m.csv`（都是 `date,open,high,low,close`）
    """
    def _close(name):
        d = pd.read_csv(os.path.join(root, "Data", "raw", name),
                        parse_dates=["date"])
        s = d.set_index("date")["close"].astype(float)
        return s[~s.index.duplicated(keep="last")].sort_index()

    v, v3 = _close("vix.csv"), _close("vix3m.csv")
    ratio = (v / v3).dropna()
    chg = ratio.pct_change(5).dropna()          # N=5（2026-11-02 定版）
    sdf = chg.rename("f012").reset_index()
    sdf.columns = ["date", "f012"]
    sdf["date"] = sdf["date"].astype(str).str[:10]
    return sdf


def _compute_erp(root, pd):
    """F-017：ERP 股权风险溢价 **滚动分位** ✓（`factors/erp.py`）

    判据来源 `evolution/factors.md`：
      「ERP 股权风险溢价（`1/PE − 月均10Y`，`fg_system/factors/erp.py`）」
      「**正向**（ERP 高=股票便宜=看多）」
    状态：`rejected`（日频 rank_ICIR +0.334/+0.244/+0.200/+0.242 未达 0.5 ✗，
          月频更差）—— **本次复核是用新判据（择时 alpha）重判** ✓

    ⚠️ `erp_pct()` 原生是**月频**（`available_date`）✗
       ⇒ 必须传 `target_index` 对齐到**日频** ✓
          （否则 join 日频价格后只剩每月一行 ✗ 样本不够）
       目标指数取 SPY（缺则退 TQQQ）✓
    """
    sys.path.insert(0, root)
    from fg_system.factors import erp as _erp
    px = pd.read_csv(os.path.join(root, "Data", "raw", "prices.csv"),
                     parse_dates=["date"])
    idx = None
    for sym in ("SPY", "TQQQ"):
        s = px[px["symbol"] == sym].set_index("date").sort_index()
        if not s.empty:
            idx = s.index
            break
    if idx is None:
        raise RuntimeError("prices.csv 缺 SPY/TQQQ，无法对齐 ERP 到日频")
    s = _erp.erp_pct(target_index=idx).dropna().rename("erp")
    sdf = s.reset_index()
    sdf.columns = ["date", "erp"]
    sdf["date"] = pd.to_datetime(sdf["date"]).dt.strftime("%Y-%m-%d")
    return sdf


def _fg_pos_tendency(pd, root, with_erp):
    """把「6 因子合成」转成**仓位倾向** 0~100（高=该加仓）✓

    🔴 为什么必须转：`fg_index` 是**贪婪度**（高=贪婪=该减仓）✗
       而 `factor_backtest_probe` 的 `positive` 方向是「因子高 ⇒ 仓位高」✗
       ⇒ 直接把 `fg_index` 丢进去会**方向反了** ✗
       ⇒ 统一转成 `100 - fg_index`（恐惧度，高=该加仓）✓

    `with_erp=True` 时：`0.9 × (100-fg_index) + 0.1 × (erp×100)` ✓
       - ERP 是 0~1 分位（高=便宜=该加仓 ✓，与「恐惧度」同向 ✓）
       - 权重 10%：参照 `config.WEIGHTS` 里 putcall 的 0.10 ✓
         其余 6 项按比例缩到 0.90 ✓（不新增权重总量，只做再分配 ✓）
    """
    base = pd.read_csv(os.path.join(root, "Data", "features.csv"))
    base["date"] = base["date"].astype(str).str[:10]
    base["fg_index"] = pd.to_numeric(base["fg_index"], errors="coerce")
    df = base[["date", "fg_index"]].dropna()
    df["fg_base"] = 100.0 - df["fg_index"]
    if not with_erp:
        return df[["date", "fg_base"]]

    erp = _compute_erp(root, pd)
    m = df.merge(erp, on="date", how="inner").dropna()
    m["fg_erp"] = 0.90 * m["fg_base"] + 0.10 * (m["erp"] * 100.0)
    return m[["date", "fg_erp"]]


def _compute_fg_base(root, pd):
    """基线：**现有 6 因子合成** ⇒ 仓位倾向 0~100 ✓（不加 ERP）"""
    return _fg_pos_tendency(pd, root, with_erp=False)


def _compute_fg_erp(root, pd):
    """增量：**6 因子 + ERP（10% 权重）** ⇒ 仓位倾向 0~100 ✓"""
    return _fg_pos_tendency(pd, root, with_erp=True)


def _compute_putcall(root, pd):
    """F-011：CBOE 总 Put/Call 比率的**逆向滚动分位** ✓（高分=贪婪）

    🔴 2026-11-12 实测：`Data/features.csv` **没有 `putcall` 列** ✗
       （`factor_probe --factor putcall` 报「features 无因子列」✗）
       ⇒ 只能从原始 `Data/raw/putcall.csv` 现算 ✓

    口径（照抄 `fg_system/factors/putcall.py:29-37`）：
      `total_ratio` → ffill → `rolling_pct(RANK_WINDOW)` → **`1 - pct`**（逆向）
      ⇒ 高分 = P/C 低 = 贪婪 ✓ ⇒ `direction = negative`（贪婪 ⇒ 仓位低）
    """
    sys.path.insert(0, root)
    from fg_system import config as _cfg
    from fg_system.factors.base import rolling_pct as _rp
    d = pd.read_csv(os.path.join(root, "Data", "raw", "putcall.csv"))
    d["date"] = pd.to_datetime(d["date"])
    s = d.set_index("date")["total_ratio"].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")].ffill()
    out = (1.0 - _rp(s, _cfg.RANK_WINDOW)).dropna().rename("putcall").reset_index()
    out.columns = ["date", "putcall"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out


#: 需现算的因子（其余因子名若在 `features.csv` 里已存在 ⇒ 直接复用 ✓）
def _compute_ene(root, pd, symbol=None):
    """F-018：ENE 包络通道位置（0=触下轨超卖，1=触上轨超买）✓

    🔴 **这是「标的自身」因子** ⇒ 必须传 `symbol` ✗（不同标的值不同 ✗）
       与 `gold_ratio` / `erp` / `f012` 这些「市场级」因子不同 ✓
       ⇒ `_act_factor_probe` 对这类因子会**按 symbol 分别生成**研究 features ✓

    口径（`fg_system/factors/ene.py:126`）：`ene_pos(prices_df, sym)`
    方向：高分=触上轨=超买 ⇒ 该降仓 ⇒ `negative` ✓
    """
    if not symbol:
        raise RuntimeError("ENE 是标的自身因子，必须传 symbol ✗")
    sys.path.insert(0, root)
    from fg_system.factors import ene as _ene
    prices = pd.read_csv(os.path.join(root, "Data", "raw", "prices.csv"))
    s = _ene.ene_pos(prices, symbol)
    out = s.dropna().rename("ene").reset_index()
    out.columns = ["date", "ene"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out


def _compute_f020(root, pd):
    """F-020：**独立极恐标记** ✓（`putcall.csv` 的 `total_ratio > 1.2` ⇒ 1，否则 0）

    与 F-008（`zone==0` 二进制）的区别：
      F-008 的 `zone` 由 `fg_index` 分档而来 ⇒ **循环论证** ✗（已 rejected）
      F-020 用的是**独立的原始 P/C 比率** ⇒ 不依赖合成指数 ✓
    数据：`Data/raw/putcall.csv`（`date,total_ratio,...`）
    方向：`total_ratio > 1.2` = 极度恐慌 = 该加仓 ⇒ `positive` ✓
          （注意：与 F-011 的 `1-pct` 逆向分位**不同** ✗ —— 这是原始阈值的二进制）
    """
    d = pd.read_csv(os.path.join(root, "Data", "raw", "putcall.csv"))
    d["date"] = pd.to_datetime(d["date"])
    s = d.set_index("date")["total_ratio"].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    out = (s > 1.2).astype(float).rename("f020").reset_index()
    out.columns = ["date", "f020"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out


#: 依赖 `symbol` 的因子（需按标的分别生成研究 features）✓
_SYM_FACTORS = {"ene"}


_COMPUTE = {
    "gold_ratio": _compute_gold_ratio,
    "f012": _compute_f012,
    "erp": _compute_erp,
    # 🔴 2026-11-12 用户要求「6 因子 vs 6 因子+ERP 增量评测」✓
    #    两个都用 `direction=positive`（高=该加仓）⇒ 口径一致可比 ✓
    "fg_base": _compute_fg_base,     # 基线：6 因子合成
    "fg_erp": _compute_fg_erp,       # 增量：6 因子 + ERP 10%
    "putcall": _compute_putcall,     # F-011（features.csv 无此列，须现算）
    "ene": _compute_ene,             # F-018（**标的自身**因子，需 symbol）
    "f020": _compute_f020,           # F-020（独立极恐标记，P/C > 1.2 二进制）
}


def _compute_factor(root, factor, pd, symbol=None):
    """按名算因子列 ⇒ 返回 `DataFrame(date, <factor>)`，未知返回 `None` ✓"""
    fn = _COMPUTE.get(factor)
    if fn is None:
        return None
    if factor in _SYM_FACTORS:
        return fn(root, pd, symbol=symbol)
    return fn(root, pd)


def _act_factor_probe(params):
    """**算 gold_ratio 列 → 跑回测裁判** ✓（2026-11-12 用户要求推进 F-021）。

    🔴 为什么需要这个动作：
       `factor_backtest_probe.py --factor <name>` 只从 **features 文件**取因子列 ✗
       而 `gold_ratio` 从没写进 `Data/features.csv`（只有 vix/term/price/breadth）✗
       ⇒ 无法直接跑裁判 ✗

    ✅ 做法（**不动生产 features.csv** ✗）：
      ① `factors/gold_ratio.gold_ratio_pct(prices)` 算信号 ✓
      ② 写成研究专用特征文件
         `evolution/experiments/factor-adoption/features_gold_ratio.csv` ✓
      ③ `factor_backtest_probe.py --factor gold_ratio --features <上一步文件>` ✓
         **同时跑 TQQQ 与 GDXU 两个标的** ✓（GDXU 才是直接持仓 ✓）
      ④ 回执带上裁判产出的 md 路径 + 关键指标行 ✓

    方向：`gold_ratio.py` docstring 明写「方向待测，由 eval_gold_ratio 的实测 IC 决定」✗
       实测 `rank_ic_mean = -0.53`（负）⇒ 默认 `--direction negative` ✓
       （可用 `params.direction` 覆盖 ✓）
    """
    import glob as _glob

    out = {"steps": {}}
    root = ROOT
    py = os.path.join(root, ".venv", "bin", "python")
    if not os.path.exists(py):
        py = sys.executable

    # ① 算信号 —— 🔴 2026-11-12 用户要求：**支持任意因子列** ✓
    #    两条路径：
    #      A. `features.csv` **已有该列**（vix/term/price/breadth/fed/putcall）
    #         ⇒ 直接复制到研究文件 ✓（不重算，与生产同源 ✓）
    #      B. 需现算（`gold_ratio` / `f012`）⇒ 走 `_COMPUTE` 分派 ✓
    factor = str(params.get("factor") or "gold_ratio").strip()
    out["factor"] = factor
    try:
        import pandas as _pd
        sys.path.insert(0, root)
        base = _pd.read_csv(os.path.join(root, "Data", "features.csv"))
        base["date"] = base["date"].astype(str).str[:10]

        # 🔴 2026-11-13 修：**标的自身因子**在 ① 段不能算 ✗（这里还没拿到 symbol）
        #    实测 `factor_probe --factor ene` 报
        #    `RuntimeError: ENE 是标的自身因子，必须传 symbol` ✗
        #    ⇒ 跳过 ①，由 ③ 段逐 symbol 算 ✓
        if factor in _SYM_FACTORS:
            out["steps"]["signal_from"] = "per-symbol（见 ③）"
            sdf = None
        elif factor in base.columns:
            sdf = base[["date", factor]].copy()
            out["steps"]["signal_from"] = "features.csv（已有列，直接复用）"
        else:
            sdf = _compute_factor(root, factor, _pd)
            if sdf is None:
                return {"ok": False,
                        "error": "未知因子 `%s` ✗ —— features.csv 无此列，"
                                 "且 `_COMPUTE` 里没有对应算列逻辑（支持：%s）"
                                 % (factor, "、".join(sorted(_COMPUTE)) +
                                    " + features 已有列")}
            out["steps"]["signal_from"] = "_COMPUTE[%s]（现算）" % factor
        if sdf is not None:
            out["steps"]["signal"] = {"n": int(len(sdf)),
                                      "head": sdf.head(2).to_dict("records"),
                                      "tail": sdf.tail(2).to_dict("records")}
    except Exception as exc:              # noqa: BLE001
        return {"ok": False,
                "error": "算 %s 失败：%s: %s"
                         % (factor, type(exc).__name__, str(exc)[:250])}

    # ② 写研究专用特征文件（合并原 features 的非因子列）
    feat_out = os.path.join(root, "evolution", "experiments",
                            "factor-adoption", "features_%s.csv" % factor)
    if factor in _SYM_FACTORS:
        # 🔴 2026-11-13：**标的自身**因子（ENE）不能在这里生成 ✗
        #    每个 symbol 的因子值不同 ⇒ 必须按 symbol 分别生成 ✓
        #    ⇒ 跳过这里，在 ③ 循环内逐 symbol 生成 ✓
        out["steps"]["features_file"] = ("per-symbol（%s 依赖 symbol，见 ③）"
                                         % factor)
    else:
        try:
            os.makedirs(os.path.dirname(feat_out), exist_ok=True)
            base = _pd.read_csv(os.path.join(root, "Data", "features.csv"))
            base["date"] = base["date"].astype(str).str[:10]
            # 🔴 2026-11-13 修真 bug：**因子已存在于 features.csv 时不能 merge** ✗
            #    `sdf` 本来就是从 `base` 取的（`base[["date", factor]]`）✗
            #    ⇒ `base.merge(sdf)` = **自己和自己 merge** ✗
            #    ⇒ pandas 产生 `baa10y_pct_x` / `baa10y_pct_y` ✗
            #    ⇒ 子进程 `factor_probe --factor baa10y_pct` 报「无因子列」✗
            #    （实测 F-016 / F-011 都栽在这里 ✗）
            if factor in base.columns:
                merged = base
            else:
                merged = base.merge(sdf, on="date", how="left")
            merged.to_csv(feat_out, index=False)
            out["steps"]["features_file"] = feat_out
            out["steps"]["features_cols"] = list(merged.columns)[-6:]
        except Exception as exc:          # noqa: BLE001
            return {"ok": False,
                    "error": "写研究特征文件失败：%s: %s"
                             % (type(exc).__name__, str(exc)[:250])}

    # ③ 跑裁判（TQQQ + GDXU）
    # 方向默认按因子定 ✓（`gold_ratio` 实测 rank_ic -0.53 ⇒ 逆向；F-012 定「正向」）
    _DIR_DEFAULT = {"gold_ratio": "negative", "f012": "positive",
                    "erp": "positive",   # F-017 登记为「正向」（ERP 高=便宜=看多）
                    # 下面两个已转成「仓位倾向」（高=该加仓）⇒ positive ✓
                    "fg_base": "positive", "fg_erp": "positive",
                    # F-011：因子值 = 1-P/C分位（高分=贪婪）⇒ 贪婪该减仓 ⇒ negative
                    "putcall": "negative",
                    # F-018：因子值 = 通道位置（高=触上轨=超买）⇒ 超买该降仓 ⇒ negative
                    "ene": "negative",
                    # F-020：因子值 = 极恐标记（1=极恐）⇒ 极恐该加仓 ⇒ positive
                    "f020": "positive"}
    direction = str(params.get("direction")
                    or _DIR_DEFAULT.get(factor, "positive")).strip().lower()
    if direction not in ("positive", "negative"):
        direction = "negative"
    out["direction"] = direction
    runs = {}
    # 🔴 2026-11-12 用户要求：**标的可参数化** ✓
    #    背景：F-012/F-017 在 TQQQ PASS 但 GDXU FAIL ⇒ 疑似「只在宽基有效」✗
    #    ⇒ 需要扩到 SPY/QQQ/YINN/CONL 交叉验证 ✓
    #    用法：`--param symbols=SPY,QQQ,YINN,CONL`（不传则用默认两个 ✓）
    _syms = [s.strip().upper() for s in
             str(params.get("symbols") or "TQQQ,GDXU").split(",") if s.strip()]
    for sym in _syms:
        # 🔴 2026-11-13：**标的自身**因子（ENE）逐 symbol 生成研究 features ✓
        _feat = feat_out
        if factor in _SYM_FACTORS:
            try:
                _sdf = _compute_factor(root, factor, _pd, symbol=sym)
                _feat = os.path.join(root, "evolution", "experiments",
                                     "factor-adoption",
                                     "features_%s-%s.csv" % (factor, sym))
                os.makedirs(os.path.dirname(_feat), exist_ok=True)
                _b = _pd.read_csv(os.path.join(root, "Data", "features.csv"))
                _b["date"] = _b["date"].astype(str).str[:10]
                _b.merge(_sdf, on="date", how="left").to_csv(_feat, index=False)
            except Exception as exc:      # noqa: BLE001
                runs[sym] = {"rc": -1,
                             "tail": "生成 %s 的 %s 列失败：%s: %s"
                                     % (sym, factor, type(exc).__name__,
                                        str(exc)[:150])}
                continue
        try:
            r = _run([py, os.path.join(root, "scripts",
                                       "factor_backtest_probe.py"),
                      "--factor", factor, "--symbol", sym,
                      "--direction", direction, "--features", _feat],
                     300, cwd=root)
            tail = ((r.stdout or "") + (r.stderr or "")).strip()[-500:]
            runs[sym] = {"rc": r.returncode, "tail": tail}
        except Exception as exc:          # noqa: BLE001
            runs[sym] = {"rc": -1, "tail": "%s: %s"
                                          % (type(exc).__name__, str(exc)[:150])}
    out["steps"]["probe"] = runs

    # ④ 收集产出
    arts = sorted(_glob.glob(os.path.join(
        root, "evolution", "experiments", "factor-adoption",
        "%s-*-oos.md" % factor)))
    out["steps"]["artifacts"] = [os.path.basename(a) for a in arts[-4:]]
    # 🔴 2026-11-12 实测修正：**`rc=1` 不代表执行失败** ✗
    #    `factor_backtest_probe.py` 在「因子未通过裁判」时也返回 1 ✗
    #    （首次跑 F-021 时两个标的都 rc=1，但 md/json 都正常产出 ✓
    #      回执却被判成 failed，白排查一轮 ✗）
    #    ⇒ 判据改成「**有没有产出 artifacts**」✓（产出即跑通 ✓）
    out["ok"] = bool(arts)
    if not out["ok"]:
        out["hint"] = ("两个标的都没产出 md ✗ ⇒ 看 `steps.probe.*.tail`；"
                       "常见原因：prices.csv 缺 GDX/GLD、或 features 日期对不上")
    else:
        # rc=1 时把语义写清楚，避免下次又误读成「执行失败」✗
        _rcs = {s: v.get("rc") for s, v in runs.items()}
        if any(rc != 0 for rc in _rcs.values()):
            out["note"] = ("rc=%s 表示**因子未通过裁判**（不是执行失败 ✓）—— "
                           "产出已生成，结论见 artifacts" % _rcs)
    return out


def _act_news_diag(params):
    """排查「某个标的的新闻整行消失」✓（2026-11-11 用户要求查 BTC）。

    🔴 现象：11-11 三轮简报里 **BTC 行全部消失** ✗
       而 BTC 是唯一盈利仓，此前一直有
       `Live news: Bitcoin falls to nearly three-month low - CoinDesk` ✓
       同一轮 GDXU / AXTX 也消失了（那两只是「过滤后无内容」，合理）
       ⇒ 但 BTC 不该空 ✗

    查五件事（逐层往下，定位是哪一层滤掉的）：
      ① `snap["positions"]` 里有没有 BTC（防止上游就没给）
      ② 富途 `get_search_news("比特币")` 的**原始**标题（不滤）
      ③ Google News `bitcoin price` 的**原始**标题（不滤）
      ④ 每个原始标题过 `_news_is_noise` 的判定（模板标题层）
      ⑤ 每个原始标题过 `_news_relevant("BTC", t)` 的判定（相关性层）
    ⚠️ 只读，不改任何数据 ✓
    """
    out = {"steps": {}}

    # ① 持仓里有没有 BTC
    # 🔴 2026-11-11 修正：原来写 `sys.path.insert(0, SCRIPTS)` ✗
    #    但本模块**没有 `SCRIPTS` 常量**（只有 `ROOT`）⇒ `NameError` ✗
    #    其他 action 都是直接 `import invest_research`（入口已把 scripts/ 加进 path）✓
    try:
        import invest_research as _ir
        snap = _ir.build_snapshot()
        syms = [str(r.get("symbol") or "") for r in (snap.get("positions") or [])]
        out["steps"]["positions"] = syms
        out["steps"]["has_btc"] = any("BTC" in s for s in syms)
    except Exception as exc:              # noqa: BLE001
        out["steps"]["positions"] = "ERR %s: %s" % (type(exc).__name__,
                                                    str(exc)[:200])
        _ir = None
        snap = None

    target = str(params.get("symbol") or "BTC").strip().upper()
    out["target"] = target

    # ② 富途原始返回
    if _ir is not None:
        try:
            from futu import OpenQuoteContext
            kw = {"BTC": "比特币", "ETH": "以太坊"}.get(target, target)
            with _ir._alarm(45, "futu 新闻抓取超时"):
                q = OpenQuoteContext(host="127.0.0.1", port=11111)
                ret, data = q.get_search_news(kw, max_count=6)
                titles = ([str(t).strip() for t in data["title"].tolist()]
                          if ret == 0 and len(data) else [])
                q.close()
            out["steps"]["futu"] = {"kw": kw, "ret": ret, "n": len(titles),
                                    "titles": titles[:6]}
        except Exception as exc:          # noqa: BLE001
            out["steps"]["futu"] = "ERR %s: %s" % (type(exc).__name__,
                                                   str(exc)[:200])

        # ③ Google News 原始
        try:
            q = {"BTC": "bitcoin price", "ETH": "ethereum price"}.get(
                target, "%s stock" % target)
            tick = None if target in ("BTC", "ETH") else target
            urls = _ir._rss_sources(q, tick)
            raw = _ir._rss_titles_any(urls, 4)
            out["steps"]["gnews"] = {"q": q, "n": len(raw or []),
                                     "titles": list(raw or [])[:4],
                                     "sources": [u.split("?")[0][:70] for u in urls]}
        except Exception as exc:          # noqa: BLE001
            out["steps"]["gnews"] = "ERR %s: %s" % (type(exc).__name__,
                                                    str(exc)[:200])

        # ④⑤ 逐条判定：哪一层滤掉的
        try:
            rows = []
            for src in ("futu", "gnews"):
                blk = out["steps"].get(src)
                if not isinstance(blk, dict):
                    continue
                for t in (blk.get("titles") or []):
                    noise = _ir._news_is_noise(t)
                    rel = _ir._news_relevant(target, t)
                    rows.append({
                        "src": src,
                        "title": str(t)[:80],
                        "noise": noise,
                        "relevant": rel,
                        "verdict": ("滤·模板标题" if noise
                                    else ("保留" if rel else "滤·不含标的词")),
                    })
            out["steps"]["judge"] = rows
            out["steps"]["kept"] = sum(1 for r in rows if r["verdict"] == "保留")
        except Exception as exc:          # noqa: BLE001
            out["steps"]["judge"] = "ERR %s: %s" % (type(exc).__name__,
                                                    str(exc)[:200])

        # ⑥ **直接跑完整 `fetch_news`** ✓ —— 上面 ②~⑤ 是「手工重放」，
        #    可能和真实路径不同（比如 `fetch_news` 里富途段**整段超时**被吞 ✗）
        #    ⇒ 这一步才是「简报里到底拿到了什么」的**真凭实据** ✓
        try:
            import time as _t
            _t0 = _t.time()
            _news = _ir.fetch_news(snap)
            out["steps"]["fetch_news"] = {
                "seconds": round(_t.time() - _t0, 1),
                "keys": list(_news.keys()),
                "has_target": target in _news,
                "counts": {k: (len(v) if isinstance(v, list) else 1)
                           for k, v in _news.items()},
            }
        except Exception as exc:          # noqa: BLE001
            out["steps"]["fetch_news"] = "ERR %s: %s" % (
                type(exc).__name__, str(exc)[:250])

    out["ok"] = True
    _k = out["steps"].get("kept")
    out["hint"] = ("`judge` 里 verdict 全是「滤·…」⇒ 就是过滤层的问题 ✓；"
                   "`futu`/`gnews` 的 n 都是 0 ⇒ 是**抓取源**的问题 ✗（不是过滤）")
    return out


def _act_run_script(params):
    """跑**白名单内**的 `scripts/*.py` 并回传 stdout/stderr ✓。

    参数：
      - `script`：脚本文件名（必须在 `_SCRIPT_ALLOWED` 里）
      - `args`：字符串数组，原样传给脚本（可选）
      - `timeout`：秒数（默认 900，最大 1800）

    🔴 安全边界 ✗：
      · 脚本名必须在白名单 ⇒ 不能跑任意路径 ✗
      · `cwd=ROOT` ⇒ 脚本的相对路径行为与手动跑一致 ✓
      · 用 `sys.executable`（队列自己的 venv）⇒ 依赖一致 ✓
      · **不拼接 shell** ⇒ `args` 原样传参，无注入面 ✓
    """
    script = str(params.get("script") or "").strip()
    allowed = _script_allowed()
    if script not in allowed:
        return {"ok": False,
                "error": "不允许的脚本：`%s` ✗（白名单 = scripts/queue_allow/*.py：%s）"
                         % (script, ", ".join(sorted(allowed)))}
    path = os.path.join(ROOT, "scripts", script)
    if not os.path.isfile(path):
        return {"ok": False, "error": "脚本不存在：%s" % path}
    raw_args = params.get("args") or []
    if not isinstance(raw_args, list):
        return {"ok": False, "error": "`args` 必须是数组 ✗"}
    args = [str(a) for a in raw_args]
    try:
        timeout = min(int(params.get("timeout") or 900), 1800)
    except (TypeError, ValueError):
        timeout = 900
    try:
        r = _run([sys.executable, path] + args, timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 %d 秒未完成" % timeout}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "script": script, "args": args,
            "stdout": (r.stdout or "")[-3000:],
            "stderr": (r.stderr or "")[-3000:]}


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
            r = _run([BSK_BIN, "--version"], 30)
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
        r = _run(cmd, 900, env=env)
        rc, so, se = r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return {"ok": False, "error": "**找不到 bsk** ✗（设 FG_BSK ✗）"}
    except subprocess.TimeoutExpired:
        rc, so, se = 124, "", "超过 900 秒 ✗（代理不通？✗）"
    secs = time.time() - t0

    after = _ver()

    def _bsk(args, timeout=90):
        """跑一条 bsk 子命令并回显（daemon 操作用）✓。"""
        try:
            r = _run([BSK_BIN] + list(args), timeout, env=env)
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
        out["daemon_stop"] = _bsk(["daemon", "stop"])
        out["status_after"] = _bsk(["status", "--json"])
    return out


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
        r = _run(["launchctl", "print", "gui/%d/com.xingguo.fg-daily"
                  % os.getuid()], 60)
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


#: `read_tail` 允许读的路径前缀 ✓ —— 定义已上移 `queue_core.READ_ALLOW`
#: （`data` 包也要用）⇒ 这里只留别名 ✓


def _act_read_tail(params):
    """读文件末尾 N 行 ✓（2026-11-17 用户要求）

    🔴 背景：`fetch_putcall.py` 只报「无新数据」**不打印内容** ✗
       而本地 `putcall_daily_latest.csv` 只到 2026-10-12（Windows 不同步）✗
       ⇒ 无法验证简报的 `PUT-CALL 64.4` 是否合理 ✗
       ⇒ 需要能在 Mac 上「看一眼数据」的通用动作 ✓

    ⚠️ **白名单**：只允许 `Data/raw/`、`Data/features.csv`、`evolution/`、
       `docs/task-queue/` ✗ —— **刻意排除** `Data/accounts.csv` 和
       `Data/positions.csv`（含账户净值/持仓明细，不该出现在任务回执里）✗

    参数：
      - `path`：相对路径（必填）
      - `lines`：末尾行数（默认 10，上限 100）
    """
    rel = str(params.get("path") or "").strip().lstrip("/")
    if not rel:
        return {"ok": False, "error": "`path` 必填"}
    # 🔴 2026-11-19：改用 `_safe_rel`（原 `startswith` 可被 `..` 绕过 ✗）
    try:
        full = _safe_rel(rel, _READ_ALLOW)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        n = int(params.get("lines") or 10)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(n, 100))

    if not os.path.exists(full):
        return {"ok": False, "error": "文件不存在：%s" % rel}
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            alll = f.readlines()
    except OSError as exc:
        return {"ok": False, "error": "读取失败：%s" % str(exc)[:150]}

    tail = [x.rstrip("\n") for x in alll[-n:]]
    return {"ok": True, "path": rel, "total_lines": len(alll),
            "returned": len(tail), "lines": tail}


def _act_sync_runtime(params):
    """把仓库版 bypass 覆盖到运行时副本（见 sync_health.sync_runtime_copy）。"""
    from fg_system.dashboard import sync_health
    return sync_health.sync_runtime_copy()


#: 需要「从仓库副本装到 LaunchAgents」的 plist ✓
PLISTS = ["com.xingguo.fg-daily.plist", "com.xingguo.fg-task-queue.plist",
          # 2026-11-03 新增：每周一 07:30 跑 `weekly_review.py` ✓
          # （必须在 Mac ✗ Windows 的 Data/raw 只是旧快照 ✗）
          "com.xingguo.fg-weekly-review.plist"]


#: ⚠️ 这个动作**留在调度器**（没进 `queue_actions/launchd.py`）✗ ——
#:    它要往 `QUEUE/<tid>.reinstall.json` 写延迟重装回执 ✗，
#:    而 `QUEUE` 是调度器状态（测试靠 `monkeypatch.setattr(q, "QUEUE", ...)` 重定向）
#:    ⇒ 搬进包会让它读 core 的未 patch 值 ✓
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
            _run(["launchctl", "bootout", "%s/%s" % (domain, label)], 30)
            r = _run(["launchctl", "bootstrap", domain, dst], 60)
            _run(["launchctl", "enable", "%s/%s" % (domain, label)], 30)
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
            r = _run(["launchctl", "print", "%s/%s" % (domain, label)], 60)
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
            r = _run(cmd, 1800)
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
        r = _run(cmd, 1800)
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
            r = _run(cmd, 1800)
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
            r = _run(cmd, 1800)
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
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-3000:], "stderr": (r.stderr or "")[-500:]}


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
        r = _run([sys.executable, "-c", code], 1800)
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
        r = _run(
            [sys.executable, os.path.join(ROOT, "scripts", "check_freshness.py")],
            180)
        out["check_freshness"] = {"rc": r.returncode,
                                  "out": (r.stdout or "")[-800:]}
    except (subprocess.SubprocessError, OSError) as exc:
        out["check_freshness"] = "执行失败：%s" % exc
    return {"ok": True, "result": out}


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
        r = _run(cmd, 900)
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
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"
                "（阶段级进度见 daily_log_tail --which invest）"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode, "push": push,
            "stdout": (r.stdout or "")[-1500:], "stderr": (r.stderr or "")[-500:]}


def _act_daily_log_tail(params):
    """回传某个运行日志的尾巴 ✓。

    动机（2026-10-29）：简报连续两天没发，只能靠 `/tmp/fg_daily.log` 定位 ✗ ——
    而「让用户去 Mac 上敲命令」违反「Mac 侧操作一律走队列」✗。
    `which` 走白名单，`lines` 上限 200 ✓。
    """
    which = str(params.get("which") or "daily")
    try:
        logs = _tail_logs()
    except (OSError, ValueError) as exc:
        return {"ok": False, "reason": "读不到白名单 tail_logs.json：%s" % exc}
    path = logs.get(which)
    if not path:
        return {"ok": False,
                "reason": "未知日志 %r（可选：%s）" % (which, ", ".join(sorted(logs)))}
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


def _act_run_pytest(params):
    """跑指定测试文件并回传尾部输出 ✓（参数 `files`，逗号分隔，默认全量）。"""
    files = [x.strip() for x in str(params.get("files") or "tests/").split(",")
             if x.strip()]
    try:
        r = _run([sys.executable, "-m", "pytest"] + files + ["-q"], 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "pytest 超过 900 秒"}
    tail = (r.stdout or "").strip().splitlines()[-40:]
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "failed": [ln for ln in tail if ln.startswith("FAILED")],
            "tail": "\n".join(tail)}


ACTIONS = {
    # 🔴 动作包（2026-11-19 第四轮起按 8 个包拆）✓ —— 注册表仍是**唯一入口** ✗
    #    包只导出 `ACTIONS` 字典，调度器在这里合并 ⇒ 不改装饰器/自动发现 ✓
    **_FUTU_ACTIONS,
    **_LAUNCHD_ACTIONS,
    **_DIAG_ACTIONS,
    **_GIT_ACTIONS,
    **_DATA_ACTIONS,
    "run_pytest": _act_run_pytest,
    "cleanup_backlog": _act_cleanup_backlog,
    "sync_runtime": _act_sync_runtime,
    "read_tail": _act_read_tail,
    "archive_briefs": _act_archive_briefs,
    "weekly_review": _act_weekly_review,
    "diagnose_data": _act_diagnose_data,
    "bsk_update": _act_bsk_update,
    "analyze_png": _act_analyze_png,
    "rerun_brief": _act_rerun_brief,
    "verify_hypotheses": _act_verify_hypotheses,
    "inspect_snapshots": _act_inspect_snapshots,
    "diagnose_symbols": _act_diagnose_symbols,
    "diag_daily_log": _act_diag_daily_log,
    "daily_log_tail": _act_daily_log_tail,
    "run_script": _act_run_script,
    "news_diag": _act_news_diag,
    "factor_probe": _act_factor_probe,
    "rm_legacy": _act_rm_legacy,
    "verify_hyp": _act_verify_hyp,
    "run_invest_research": _act_run_invest_research,
    "install_daily_plist": _act_install_daily_plist,
    "eval_baa10y": _act_eval_baa10y,
    "factor_diag": _act_factor_diag,
    "run_pipeline": _act_run_pipeline,
    "c1_backtest": _act_c1_backtest,
    "c5_backtest": _act_c5_backtest,
    "f_factor_backtest": _act_f_factor_backtest,
    "factor_reduce_probe": _act_factor_reduce_probe,
    "backtest_plan": _act_backtest_plan,
}


#: **优先执行**的 action（重启类）—— 见 `_load_pending` 的排序说明。
PRIORITY_ACTIONS = ("restart_dashboard", "restart_queue")


#: 待执行任务超过这么久还没回执 ⇒ 视为**失效**，自动归档 ✓（2026-11-10）
#: 🔴 事故：11-09 那批任务（`deepseek_probe` / `git_state` ×3 / `clean_sync_partial`）
#:    的 json 留在队列里、但 `.result.json` 在 `git reset` 时被丢了 ✗
#:    ⇒ `_load_pending` 每一轮都把它们当新任务**重跑** ✗
#:    ⇒ 队列每 10 秒的窗口全被老任务吃掉 ⇒ 新任务看起来「一直排队中」✗
#: ⚠️ 阈值 **6 小时**（曾改 24，已改回）✓
#:    24h 的问题：11-09 那批僵尸任务才 18 小时 ⇒ 逃过归档 ✗ 继续每轮重跑 ✗
#:    6h 当初误伤「刚下发」的原因不是阈值，而是**判据用了 mtime** ✗
#:    ⇒ 判据改成 `created_at`（见 `_archive_stale_pending`）后，6h 是安全的 ✓
STALE_PENDING_HOURS = 6


def _archive_stale_pending(hours=STALE_PENDING_HOURS):
    """把**超时仍无回执**的任务 json 挪进 `_stale/` ✓（不删，可人工恢复）。

    判据：json 的 mtime 早于 `hours` 前，且**没有**同名 `.result.json`。
    ⚠️ 只挪 `docs/task-queue/*.json`，不碰 `.result.json` / `.running` ✓
    """
    import shutil
    dst = os.path.join(QUEUE, "_stale")
    moved = []
    try:
        names = sorted(os.listdir(QUEUE))
    except OSError:
        return moved
    cutoff = time.time() - hours * 3600
    for name in names:
        if not name.endswith(".json") or name.endswith(".result.json"):
            continue
        p = os.path.join(QUEUE, name)
        tid = name[:-len(".json")]
        if os.path.exists(os.path.join(QUEUE, tid + ".result.json")):
            continue
        try:
            # 🔴 2026-11-10 实测事故：**只看 mtime 会把刚到的新任务归档掉** ✗
            #    （13:49 下发的 `test_futu_fed` 在 13:53 就被归档 ✗）
            #    原因：文件是 fg-sync **重新检出**的，mtime 可能被刷新成旧值/不一致 ✗
            #    ⇒ 改用 `created_at`（任务 json 里的权威字段）+ mtime，**取较新者** ✓
            t_created = 0.0
            try:
                with open(p, encoding="utf-8") as _fh:
                    _spec = json.load(_fh)
                _c = str(_spec.get("created_at") or "")
                if _c:
                    t_created = time.mktime(time.strptime(_c, "%Y-%m-%dT%H:%M:%S"))
            except (OSError, ValueError, KeyError):
                t_created = 0.0
            # 🔴 2026-11-10 第二次修正：**只用 `created_at`**（权威）✓
            #    上一版用 `max(created_at, mtime)` ✗ —— 老任务被重新检出后
            #    mtime 变新 ⇒ 看起来像新任务 ⇒ 永远归档不掉 ✗
            #    （实测：11-09 那批 5 个任务在 11-10 15:20 仍 pending ✗）
            #    `created_at` 缺失时才退回 mtime ✓
            _age_base = t_created or os.path.getmtime(p)
            _age_h = (time.time() - _age_base) / 3600.0
            # 🔴 2026-11-11 用户要求：**「有 .running 才归档」** ✓
            #    事故：11-10 17:27 下发的 `autostart_list` 因为队列卡住没跑成 ✗
            #    到 11-11 09:02（15.5 小时 > 6h 阈值）被**静默归档** ✗
            #    ⇒ 用户以为它执行了，其实压根没轮到 ✗
            #    ⇒ 分两档：
            #      ① 有 `.running` 残留 ⇒ 说明**尝试过但卡死** ⇒ 6 小时就归档 ✓
            #      ② 没有 `.running` ⇒ 说明**压根没轮到** ⇒ 要 **24 小时**才归档 ✓
            #    （24h 是为了兜住 11-09 那批 result 丢了的真僵尸 ✓）
            _has_running = os.path.exists(os.path.join(QUEUE, tid + ".running"))
            if _has_running:
                if _age_base > cutoff:            # 6h
                    continue
            elif _age_h < 24:
                continue
            os.makedirs(dst, exist_ok=True)
            shutil.move(p, os.path.join(dst, name))
            moved.append(name)
            print("[stale]   %s（%.1f 小时，%s）"
                  % (name, _age_h,
                     "有 .running 残留" if _has_running else "从未执行过"))
        except OSError:
            continue
    if moved:
        print("[stale] 已归档 %d 个超时无回执的任务 -> _stale/" % len(moved))
        for m in moved:
            print("   %s" % m)
    return moved


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
        r = _run(["git", "rev-list", "--count", "@{u}..HEAD"], 30)
        if r.returncode != 0:
            return                      # 没有上游 / 不是仓库 ⇒ 静默跳过 ✓
        if int((r.stdout or "0").strip() or 0) <= 0:
            return                      # 没有待推提交 ✓
        p = _run(["git", "push", "origin", "HEAD"], 180)
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
    # 🔴 2026-11-10：先把「超时无回执」的失效任务归档 ✓
    #    否则它们每轮都被当新任务重跑，新任务永远排不上 ✗
    _moved = _archive_stale_pending()
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
            # 🔴 2026-11-19：**先无条件清掉**任务 JSON 里的 `_tid` ✗
            #    实测 `test_tid_cannot_be_overridden` 暴露：只在
            #    `if action in NEEDS_TID` 分支里覆盖 ⇒ 其他 action 拿到的
            #    仍是任务 JSON 里的**恶意值**（`"../../evil"`）✗
            #    ⇒ 先 pop 掉，再按需注入 ✓
            _params.pop("_tid", None)
            if action in NEEDS_TID:
                # 🔴 2026-11-19：**必须覆盖，不能用 `setdefault`** ✗
                #    原写法：任务 JSON 里预先塞 `"_tid": "任意值"` ⇒
                #    `setdefault` 不覆盖 ⇒ 攻击者控制 `_tid` ✗
                #    （`_tid` 用于生成文件名/日志路径 ⇒ 可路径穿越）
                _params["_tid"] = spec["id"]
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
    # 🔴 2026-11-10：**归档也要提交** ✗ —— 原来只在 `done or reinstalled` 时提交 ✗
    #    ⇒ 归档只发生在 Mac 本地 ⇒ origin 上任务 json 还在 ⇒ 两边分叉 ✗
    #    （实测：Mac 显示「待执行 0」，origin 上仍有 2 个）
    if commit and (done or reinstalled or _moved):
        if done:
            # 2026-10-29：顺带瘦身 ✓ —— 每个任务两个 json 永不清理会无限涨 ✗
            dropped = _prune_queue()
            if dropped:
                print("[prune] 清理 %d 个旧任务文件（只留最近 %d 个）"
                      % (len(dropped), KEEP_TASKS))
        _git_commit(done
                    or [(t, "reinstall") for t in reinstalled]
                    or [("stale", "archived%d" % len(_moved))])
    return done


#: 🔴 任务产物白名单已外置到 `scripts/queue_allow/task_outputs.json` ✓
#: （`{"dirs": [...], "files": [...]}` —— 加产物路径只改 json ✓）
# 🔴 2026-11-03 移除：`Data/raw/sp500_pe.csv` / `sp500_cape.csv` /
#    `fred_DGS10.csv` 曾在这里 ✗（2026-10-30 为让 Windows 看到 C2 数据 ✗）
#    但 2026-11-03 用户裁定「数据不入库」⇒ `Data/raw/` 已进 `.gitignore` ✗
#    ⇒ 别再把 `Data/raw/*` 加回 `task_outputs.json` ✗ —— 会被 git 拒绝
#       （`_git_commit` 已改为逐个 add，不会整体失败，但会刷一堆 warn ✓）


def _git_commit(done):
    """提交 `docs/task-queue/` + **任务产物目录** ✓ —— 不碰其他脏文件 ✗。"""
    try:
        try:
            out_dirs, out_files = _task_outputs()
        except (OSError, ValueError) as exc:
            # 白名单坏了 ⇒ 只提交任务结果，别把整个提交搞丢 ✗
            print("[warn] 产物白名单读取失败（本轮只提交任务结果）：%s" % exc)
            out_dirs, out_files = [], []
        paths = ["docs/task-queue"] + [
            d for d in out_dirs
            if os.path.isdir(os.path.join(ROOT, d))] + [
            f for f in out_files
            if os.path.isfile(os.path.join(ROOT, f))]
        # 🔴 2026-11-03：**不能 `check=True`** ✗ —— 只要有一个路径被
        #    `.gitignore` 拒绝（如 `Data/raw/*` ✗），git 就**整体失败** ✗
        #    ⇒ 连 `docs/task-queue` 的结果都提交不了 ✗
        #    ⇒ 改为：**逐个 add** ✓ 失败的单独报警但不中断 ✓
        bad = []
        for pth in paths:
            r = _run(["git", "add", "--", pth], 60)
            if r.returncode != 0:
                bad.append((pth, (r.stderr or "").strip()[:120]))
        if bad:
            print("[warn] 以下路径 add 失败（其余照常提交 ✓）：")
            for pth, err in bad:
                print("   %s —— %s" % (pth, err))
        msg = "task: %s" % "; ".join("%s=%s" % (i, s) for i, s in done)
        r = _run(["git", "commit", "-m", msg], 120)
        if r.returncode != 0:          # 无变更可提交 ⇒ 不是错误 ✓
            return
        p = _run(["git", "push", "origin", "HEAD"], 180)
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


def _acquire_lock():
    """`flock` 排他锁 ✓ —— 防止 launchd **每 10 秒起一个实例**并发抢同一任务 ✗。

    🔴 2026-11-10 实测事故（用户反馈「任务一直显示排队中」）：
       plist 是 `StartInterval = 10` ✗ 而 `run_once()` **没有并发保护** ✗
       ⇒ 只要某个任务跑超过 10 秒（`test_futu_fed` 要 90 秒 ✗），
         launchd 就会**再起一个实例** ⇒ 多个进程同时 `_load_pending()` 抢同一个
         task json ⇒ `.running` 标记互相覆盖、结果文件互相覆盖 ✗
       ⇒ 更糟：多个实例**同时调 futu SDK** ⇒ 直接加重 OpenD 重连循环 ✗
    拿不到锁就**直接退出**（本次跳过，10 秒后自然重试 ✓），不阻塞 ✓
    """
    try:
        import fcntl
    except ImportError:                    # 非 POSIX ⇒ 退化为无锁 ✓
        return object()
    p = os.path.join(QUEUE, ".queue.lock")
    try:
        fh = open(p, "w")
    except OSError:
        return object()
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mac 侧任务队列执行器")
    ap.add_argument("--no-commit", action="store_true", help="只执行不提交（调试）")
    args = ap.parse_args(argv)
    # 🔴 2026-11-12 用户告警「fg-task-queue 日志 39280 秒没动静 ⇒ 疑似卡死」是**误报** ✗
    #    本脚本是 `StartInterval` **定时一次性**任务，不是常驻 ✗
    #    没任务可做时什么都不打印 ⇒ `/tmp/fg_task_queue.log` 的 mtime 不动 ✗
    #    ⇒ 每次运行都 **touch 一个心跳文件**（只改 mtime，不写内容，不涨体积）✓
    #    放在 `_acquire_lock` **之前**：上一轮还在跑也算「活着」✓
    try:
        os.makedirs(QUEUE, exist_ok=True)
        _hb = os.path.join(QUEUE, ".heartbeat")
        with open(_hb, "a"):
            os.utime(_hb, None)
    except OSError:
        pass
    lock = _acquire_lock()
    if lock is None:
        print("[skip] 上一轮仍在执行（flock 未释放）⇒ 本轮跳过")
        return 0
    done = run_once(commit=not args.no_commit)
    for i, s in done:
        print("%s -> %s" % (i, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
