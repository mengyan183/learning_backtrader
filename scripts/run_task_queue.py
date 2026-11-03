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
            "guards_tail": guards[-40:]}


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
)


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

    return {"ok": rc == 0, "script": script, "args": extra, "rc": rc,
            "seconds": round(secs, 1),
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
    return {"ok": all(v.startswith("ok") or v.startswith("已拷贝")
                      for v in out.values()), "result": out}


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
    # 恒等式不成立时脚本 return 1 ✗ —— 那是**保护**不是崩溃 ✓
    return {"ok": r.returncode == 0, "rc": r.returncode,
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
            headers["Authorization"] = "Bearer " + ir._read_nim_key()
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
            reply = ir._chat(ir.NIM_URL, ir._read_nim_key(),
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


ACTIONS = {
    "cleanup_backlog": _act_cleanup_backlog,
    "sync_runtime": _act_sync_runtime,
    "git_pull": _act_git_pull,
    "archive_briefs": _act_archive_briefs,
    "weekly_review": _act_weekly_review,
    "diagnose_data": _act_diagnose_data,
    "run_fetch_step": _act_run_fetch_step,
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


def _load_pending():
    """列出待执行任务（status=pending），按 created_at 升序（先来先做）。"""
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
    out.sort(key=lambda s: str(s.get("id") or ""))
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
