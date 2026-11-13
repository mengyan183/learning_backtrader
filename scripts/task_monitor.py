#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""贪恐系统定时任务与数据新鲜度监控（2026-10-14 新增）。

为什么需要：launchd 定时任务失败/停更曾导致数据缺失多天未被发现
（VIX 上游 T+1 停在 10-12、shoutu_history 停更 6 天）。本脚本每日多次检查：

  1. **数据新鲜度**：每类数据文件的 date 列最大日期 vs 今天，容忍自然日窗口
     （吸收周末、节假日与上游 T+1 发布滞后；shoutu_history 为 bsk 条件抓取，
     容忍 7 天）。
  2. **launchd 注册状态**：贪恐 7 个定时任务是否仍在 `launchctl list` 中。
  3. **mtime 兜底**：date 列读取/解析失败时，用文件最后修改时间判断。

异常 → 飞书推送（复用 invest_research.push_feishu）；同日同项只推一次
（Data/monitor_state.json 去重，跨日重置），避免每日多次检查重复轰炸。

用法：
  .venv/bin/python scripts/task_monitor.py               # 仅检查 + 打印
  .venv/bin/python scripts/task_monitor.py --push-alert  # 异常时推飞书（launchd 用）
退出码：0 = 全部正常；1 = 存在异常。
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

STATE_FILE = REPO / "Data" / "monitor_state.json"

#: `shoutu_history` 的**标的白名单** ✓ —— 只有服务端确实提供历史的标的才参与
#: 停更判定 ✗。2026-11-09 实测：8 个美股标的服务端全部返回 `data: []`
#: ⇒ 文件尾行永远停在 2026-10-14 ⇒ 天天报「停更 26 天」的**假告警** ✗
#: 空列表 = 当前无任何标的被服务端提供历史 ⇒ **跳过停更判定**（仍显示真实尾行）✓
SHOUTU_HISTORY_WHITELIST = []

# (名称, 相对路径, date 列, 容忍自然日)
DATA_CHECKS = [
    ("features",        "Data/features.csv",              "date", 3),
    ("prices",          "Data/raw/prices.csv",            "date", 3),
    ("vix",             "Data/raw/vix.csv",               "date", 4),
    ("sentiment",       "Data/raw/sentiment.csv",         "date", 4),
    ("putcall",         "Data/raw/putcall.csv",           "date", 4),
    ("fedwatch",        "Data/raw/fedwatch.csv",          "date", 3),
    ("kalshi_fed",      "Data/raw/kalshi_fed.csv",        "date", 3),
    ("funding_rate",    "Data/raw/funding_rate.csv",      "date", 3),
    ("shoutu_fng",      "Data/raw/shoutu_fng.csv",        "date", 3),
    ("shoutu_history",  "Data/raw/shoutu_history.csv",    "date", 7),
    ("news_sentiment",  "Data/raw/news_sentiment.csv",    "date", 3),
    ("stablecoin_usage","Data/raw/stablecoin_usage.csv",  "date", 3),
    # FRED 宏观利率（列名 observation_date；工作日发布，周末/节假日/T+1 滞后，容忍 5 自然日）。
    # 2026-10-26 补：此前这三项既不在每日链也不在监控 ⇒ 静默停更多日无人发现。
    ("fred_dff",        "Data/raw/fred_DFF.csv",          "observation_date", 5),
    ("fred_dgs10",      "Data/raw/fred_DGS10.csv",        "observation_date", 5),
    ("fred_t10y2y",    "Data/raw/fred_T10Y2Y.csv",      "observation_date", 5),
]

# 贪恐系统定时任务（launchctl 注册检查）
TASKS = [
    "com.xingguo.fg-auto-update",     # 每日 02:00 代码自更新
    "com.xingguo.fg-daily",           # 每日 05:30 全链路
    "com.xingguo.fg-kb-update",       # 每周日 03:00 知识库
    "com.xingguo.fg-shoutu-refresh",  # 每日 09/17/22 守猪待兔刷新
    "com.fg.shoutu-daily",            # 每日 06:30 守猪待兔 API
    "com.fg.shoutu-history",          # 每日 06:35 守猪待兔历史（条件）
    "com.fg.quarterly-walkforward",   # 季度首日 08:00 重标定
    "com.xingguo.fg-evolve-verify",   # 每日 06:10 假说验证（数据过期闸门 return2 不回写）
    "com.xingguo.fg-evolve-weekly",   # 每周一 07:00 进化周报（默认不推飞书）
    # 🔴 2026-11-10 补：下面四个**早已部署但没被监控** ✗
    #    ⇒ 队列卡死 100 分钟、watcher 停了，任务页照样显示「全部正常」✗
    "com.xingguo.fg-task-queue",      # 每 10 秒 任务队列（fg-sync 执行端）
    "com.xingguo.fg-sync-watcher",    # 常驻 飞书分片 watcher（fg-sync 入口）
    "com.xingguo.fg-realtime",        # 常驻 盘中实时行情
    "com.xingguo.fg-weekly-review",   # 每周一 07:30 周报
    # 🔴 2026-11-10 用户要求补齐最后两个 ✓
    "com.xingguo.fg-dashboard",       # 常驻 看板服务（本页面自己）
    "com.xingguo.fg-monitor",         # 每日 07:00 任务与数据新鲜度告警
    # 🔴 2026-11-11 用户要求纳入 ✓ —— 它不是贪恐系统业务，但**是我们装的** ✗
    #    实测 `RunAtLoad=true` + `KeepAlive=true` 却**进程静默消失** ✗
    #    （`autostart_list` 回执：`dsh_related_count=1` 但 `running: []`）
    #    ⇒ 不监控的话，它死了 40 小时也没人知道（web 控制台打不开才被发现）
    "com.xingguo.dsh.web",            # 常驻 dsh web 控制台（DeepSeek Harness）
]

#: 🔴 高频/常驻任务的**活性阈值**（秒）✓（2026-11-10 新增）
#: 为什么单独处理：「注册了」≠「活着」✗ —— 队列 plist 一直在，进程却可能卡死 ✗
#: ⇒ 这些任务额外检查「日志文件 mtime 距今多少秒」✓
HEARTBEAT_TASKS = {
    "com.xingguo.fg-task-queue":   300,    # 每 10 秒跑一次 ⇒ 5 分钟没动静就是卡了
    "com.xingguo.fg-sync-watcher": 1800,   # 常驻，收分片才写日志 ⇒ 30 分钟
    "com.xingguo.fg-realtime":     1800,   # 常驻，盘中才写 ⇒ 30 分钟
    # 🔴 2026-11-11：dsh web 用 `~/.dsh/our-free-model/availability.json` 做心跳 ✓
    #    为什么不用 `/tmp/dsh-web-launchd.log` ✗ —— 它**只在启动时写一行** ✗
    #    ⇒ 进程活着时 mtime 也一直不动 ⇒ 会天天误报「卡死」✗
    #    `availability.json` 是 dsh 运行期持续刷新的（实测 1 分钟级）✓
    #    阈值给 **3600 秒**（1 小时）—— 它依赖上游模型源，刷新间隔可能拉长 ✓
    # 🔴 2026-11-13：3600 → **86400**（24 小时）✓
    #    实测 `availability.json` 5059 秒（1.4h）没更新就报警 ✗
    #    但它反映的是「免费模型源」可用性，**不是 web 服务存活** ✗
    #    （同一次回执显示进程 PID 59881 / state=running / never exited ✓）
    #    ⇒ 已改 **HTTP 探活**（见 `TASK_LOG`），阈值回到 **300 秒** ✓
    #       （探活是即时的，5 分钟内不通就是真挂 ✗）
    "com.xingguo.dsh.web":         300,
}

#: 任务频率（2026-10-28 新增展示）。
#: 为什么需要：页面只显示「最后日期」，于是**每周日**跑的 kb-update（10-25）、
#: **每季度**跑的 quarterly-walkforward（10-21）、**每周一**跑的 evolve-weekly（10-26）
#: 看起来像「停更了」✗ —— 用户得靠记忆区分日/周/季任务 ✗。
TASK_SCHEDULE = {
    "com.xingguo.fg-auto-update":    "每日 02:00",
    "com.xingguo.fg-daily":          "每日 05:30",
    "com.xingguo.fg-kb-update":      "每周日 03:00",
    "com.xingguo.fg-shoutu-refresh": "每日 09/17/22",
    "com.fg.shoutu-daily":           "每日 06:30",
    "com.fg.shoutu-history":         "每日 06:35（条件）",
    "com.fg.quarterly-walkforward":  "每季度首日 08:00",
    "com.xingguo.fg-evolve-verify":  "每日 06:10",
    "com.xingguo.fg-evolve-weekly":  "每周一 07:00",
    "com.xingguo.fg-task-queue":     "每 10 秒（常驻）",
    "com.xingguo.fg-sync-watcher":   "常驻（收分片即触发）",
    "com.xingguo.fg-realtime":       "常驻（盘中）",
    "com.xingguo.fg-weekly-review":  "每周一 07:30",
    "com.xingguo.fg-dashboard":      "常驻（看板服务）",
    "com.xingguo.fg-monitor":        "每日 07:00",
    "com.xingguo.dsh.web":           "常驻（dsh web 控制台）",
}

# 任务 → 日志文件候选（plist StandardOutPath）。launchd 不暴露"最后运行时间"，
# 以日志文件最后写入时间（mtime）作为最近一次运行的近似（2026-10-16 新增展示）。
# ⚠️ 2026-10-20 修正：部分脚本把输出重定向到**自写日志**（如 logs/auto-update.log），
#    而 plist 的 StandardOutPath（*.out.log）因此**永远 0 字节** ⇒ 单看 .out.log 会读到
#    很久以前的旧时间（实测 fg-auto-update 停在 10-13、shoutu-history 停在 10-15，
#    页面显示"最新执行时间差 3 天以上"，但任务实际每天在跑 ✗）。
#    故每个任务给**候选列表**，取所有存在文件 mtime 的**最大值** ✓。
TASK_LOG = {
    "com.xingguo.fg-auto-update":     ["logs/auto-update.log",
                                       "logs/auto-update.out.log"],
    "com.xingguo.fg-daily":           ["/tmp/fg_daily.log"],
    "com.xingguo.fg-kb-update":       ["logs/fg_kb_update.log",
                                       "/tmp/fg_kb_update.out"],
    "com.xingguo.fg-shoutu-refresh":  ["logs/shoutu-refresh.out.log"],
    "com.fg.shoutu-daily":            ["logs/shoutu_daily.log"],
    "com.fg.shoutu-history":          ["logs/shoutu_history_daily.log",
                                       "logs/shoutu_history_daily.out.log"],
    "com.fg.quarterly-walkforward":   ["logs/walkforward_launchd.log",
                                       "logs/walkforward_launchd.out.log"],
    "com.xingguo.fg-evolve-verify":   ["logs/evolve_verify.log"],
    "com.xingguo.fg-evolve-weekly":   ["logs/evolve_weekly.log"],
    # 🔴 2026-11-11 **补 6 个漏配的日志候选** ✗ ——
    #    之前把它们加进 `TASKS`（fix_1110s/t）却**没加 TASK_LOG** ✗
    #    后果不只是「任务页最新执行时间永远显示 —」✗，
    #    更严重的是 **`HEARTBEAT_TASKS` 判据失效** ✗：
    #      `_task_log_age()` 找不到任何候选文件 ⇒ 返回 None
    #      ⇒ `alive` 恒为 True ⇒ 队列卡死也不会报红 ✗
    #    （`test_every_monitored_task_declares_a_candidate` 早就挂了 ✗）
    #    路径取自各自 plist 的 `StandardOutPath` ✓
    # 🔴 2026-11-12 修正：这两个是 `StartInterval` **定时一次性**脚本 ✗
    #    「无事可做」时一行都不打印 ⇒ 用 StandardOutPath 的 mtime 当心跳会**误报卡死** ✗
    #    （实测报 `fg-task-queue 日志 39280 秒没动静`，而它当时明显在跑）
    #    ⇒ 改用两个脚本每次运行都 touch 的 `.heartbeat` ✓（只改 mtime，不写内容）
    "com.xingguo.fg-task-queue":      ["docs/task-queue/.heartbeat"],
    "com.xingguo.fg-sync-watcher":    ["~/.openclaw/tmp/.heartbeat"],
    "com.xingguo.fg-realtime":        ["/tmp/fg_realtime.log"],
    "com.xingguo.fg-weekly-review":   ["/tmp/fg_weekly_review.out"],
    "com.xingguo.fg-dashboard":       ["/tmp/fg_dashboard.log"],
    "com.xingguo.fg-monitor":         ["logs/task_monitor.out.log"],
    # 🔴 2026-11-11：dsh web 的日志都在仓库外 ⇒ 用 `~` 前缀（下面 `_resolve_log` 会展开）✓
    #    ① `/tmp/dsh-web-launchd.log`  —— 启动时写一行（只看「最后一次启动时间」）
    #    ② `~/.dsh/our-free-model/availability.json` —— 运行期持续刷新（心跳用这个）✓
    # 🔴 2026-11-13 实测（`dsh_web_diag` 回执）：
    #    `availability.json` 本身 **5059 秒没刷新** ✗（不是心跳配错）
    #    ⇒ 那是 dsh 的 `our-free-model` 模块停刷（上游模型源问题）✗
    #      而 `dsh.web` 进程**完全正常**：PID 59881、`state=running`、
    #      `last exit code = (never exited)` ✓
    #    ⇒ 用 `availability.json` 当 `dsh.web` 的心跳**混淆了两件事** ✗
    #      （web 服务活着 ≠ 免费模型源可用）
    #    ⇒ **整条移除** ✓：`dsh.web` 有 `KeepAlive=true`，
    #      进程挂了 launchd 会立刻重启 ⇒ 不需要额外的日志心跳 ✓
    #      ⇒ **保留监控但大幅放宽阈值**（见 `STALE_SEC` 86400）✓
    #         因为 `availability.json` 反映的是「免费模型源可用性」，
    #         它停刷 ≠ web 服务挂了（实测进程一直 running）✗
    #         24 小时阈值能容忍上游源长时间不可用，同时仍能发现真死 ✓
    # 🔴 2026-11-13 用户澄清：`availability.json` 是**免费模型时代的遗留文件** ✗
    #    hermes 现在配的是**付费 `deepseek-flash`** ⇒ 它不刷新是**预期行为** ✓
    #    ⇒ 拿它当 `dsh.web` 的心跳**根本错误** ✗（web 活着 ≠ 免费模型源可用）
    #    ⇒ 改用 **HTTP 探活** ✓：`dsh web` 监听 127.0.0.1:3080
    #       `_task_log_age` 已支持 `http://` 前缀（GET 一次，status<500 算活）✓
    "com.xingguo.dsh.web":            ["http://127.0.0.1:3080/"],
}


def _resolve_log(rel):
    """把 `TASK_LOG` 里的相对/绝对/`~` 路径统一成 `Path` ✓（2026-11-11 新增）。

    为什么需要：`dsh.web` 的日志在仓库外（`~/.dsh/...`、`/tmp/...`）✗
    原来只支持「`/` 开头当绝对路径，其余拼 `REPO`」⇒ `~` 会被拼成
    `REPO/~/.dsh/...`（不存在的路径）✗
    """
    if rel.startswith("/"):
        return Path(rel)
    if rel.startswith("~"):
        return Path(os.path.expanduser(rel))
    return REPO / rel


def _task_last_run(label: str):
    """读任务日志 mtime 作为最近运行时间近似：候选文件里取**最新**的那个。

    返回 (格式化时间, 命中文件路径)；无任何候选文件存在时返回 (None, None)。
    """
    best_mt, best_p = None, None
    for rel in TASK_LOG.get(label) or []:
        p = _resolve_log(rel)
        if not p.exists():
            continue
        mt = p.stat().st_mtime
        if best_mt is None or mt > best_mt:
            best_mt, best_p = mt, p
    if best_mt is None:
        return None, None
    return datetime.fromtimestamp(best_mt).strftime("%Y-%m-%d %H:%M"), best_p


def _task_log_age(label: str):
    """日志 mtime 距今**多少秒** ✓（`None` = 一个候选日志文件都不存在）。

    给 `HEARTBEAT_TASKS` 用 —— 「注册了」不等于「活着」✗
    """
    best_mt = None
    for rel in TASK_LOG.get(label) or []:
        # 🔴 2026-11-13 用户澄清：`availability.json` 是**免费模型时代的遗留** ✗
        #    hermes 现在配的是**付费 `deepseek-flash`** ⇒ 那个文件不刷新是**预期** ✓
        #    ⇒ 拿它当 `dsh.web` 的心跳**根本错误** ✗
        #    ⇒ 改用 **HTTP 探活** ✓（`dsh web` 在 127.0.0.1:3080）
        #       `http://` 开头的候选 ⇒ GET 一次，2xx/3xx 就算活着 ✓
        if str(rel).startswith(("http://", "https://")):
            try:
                with urllib.request.urlopen(rel, timeout=3) as r:
                    if r.status < 500:
                        return 0          # 活着 ⇒ age=0
            except Exception:             # noqa: BLE001
                pass                      # 探活失败 ⇒ 继续试下一个候选
            continue
        p = _resolve_log(rel)
        if not p.exists():
            continue
        mt = p.stat().st_mtime
        if best_mt is None or mt > best_mt:
            best_mt = mt
    if best_mt is None:
        return None
    return int(time.time() - best_mt)


def _last_date_csv(path: Path, col: str, symbols=None):
    """全量扫描取 date 列最大值（文件按日期追加，仍取 max 防乱序）。

    `symbols` 非空 ⇒ **只看这些标的** ✓（守猪待兔白名单，见 `SHOUTU_HISTORY_WHITELIST`）
    """
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if col not in (reader.fieldnames or []):
            return None
        mx = None
        for row in reader:
            if symbols and (row.get("symbol") or "").strip() not in symbols:
                continue
            v = (row.get(col) or "").strip()[:10]
            if v:
                mx = v if mx is None else max(mx, v)
        return mx


def _mtime_days(path: Path, today: date) -> int:
    st = path.stat()
    return (today - datetime.fromtimestamp(st.st_mtime).date()).days


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_status(today=None):
    """纯检查（不推送、不写 state）：返回监控明细 dict，供 CLI 与 dashboard API 复用。

    返回：{"data": [{"name","last","lag","tol","ok"}],
           "tasks": [{"label","registered","ok"}],
           "issues": [...], "all_ok": bool}
    """
    today = today or date.today()
    data_rows, issues, keys = [], [], []

    for name, rel, col, tol in DATA_CHECKS:
        p = REPO / rel
        if not p.exists():
            data_rows.append({"name": name, "last": None, "lag": None,
                              "tol": tol, "ok": False})
            issues.append("%s：文件缺失 %s" % (name, rel))
            keys.append("%s:missing" % name)
            continue
        if name == "shoutu_history":
            wl = [s for s in SHOUTU_HISTORY_WHITELIST if s]
            if not wl:
                # 服务端对这些标的没有历史 ⇒ 尾行不动是**正常**的 ✗ 不算异常 ✓
                data_rows.append({"name": name, "last": _last_date_csv(p, col),
                                  "lag": None, "tol": tol, "ok": True,
                                  "note": "白名单为空 ⇒ 不判停更"})
                continue
            dmax = _last_date_csv(p, col, symbols=wl)
        else:
            dmax = _last_date_csv(p, col)
        if dmax:
            lag = (today - date.fromisoformat(dmax)).days
            data_rows.append({"name": name, "last": dmax, "lag": lag,
                              "tol": tol, "ok": lag <= tol})
            if lag > tol:
                issues.append("%s：数据停更 %s（最后 %s，容忍 ≤%d 天）"
                              % (name, lag, dmax, tol))
                keys.append("%s:%s" % (name, dmax))
        else:
            md = _mtime_days(p, today)
            data_rows.append({"name": name, "last": "date列缺失",
                              "lag": md, "tol": tol, "ok": md <= tol + 1})
            if md > tol + 1:
                issues.append("%s：date 列缺失且文件 %d 天未写入" % (name, md))
                keys.append("%s:mtime%d" % (name, md))

    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=15).stdout
    except Exception as e:
        issues.append("launchctl list 执行失败：%s" % e)
        keys.append("launchctl:fail")
        out = ""
    registered = {line.split()[-1] for line in out.splitlines()
                  if line.split() and len(line.split()) >= 3}
    task_rows = []
    for t in TASKS:
        is_reg = t in registered
        last_run, last_run_file = _task_last_run(t)
        # 🔴 2026-11-10：`HEARTBEAT_TASKS` 额外查「日志多久没动」✗
        #    「注册了」≠「活着」✗ —— 队列 plist 一直在，进程却可能卡死 ✗
        #    （实测：队列卡了 100 分钟，任务页仍显示「全部正常」✗）
        age = _task_log_age(t) if t in HEARTBEAT_TASKS else None
        tol = HEARTBEAT_TASKS.get(t)
        alive = True
        if tol is not None and age is not None:
            alive = age <= tol
        ok = is_reg and alive
        task_rows.append({"label": t, "registered": is_reg, "ok": ok,
                          "schedule": TASK_SCHEDULE.get(t, "—"),
                          "last_run": last_run,
                          "heartbeat_age": age,
                          "heartbeat_tol": tol,
                          "last_run_file": str(last_run_file) if last_run_file else None})
        if not is_reg:
            issues.append("定时任务未注册：%s" % t)
            keys.append("task:%s" % t)
        elif not alive:
            issues.append("%s：日志 %d 秒没动静（阈值 %d 秒）⇒ 进程疑似卡死"
                          % (t, age, tol))
            keys.append("task:%s:stale%d" % (t, age // 60))

    return {"data": data_rows, "tasks": task_rows,
            "issues": issues, "keys": keys, "all_ok": not issues}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="贪恐系统定时任务与数据新鲜度监控")
    ap.add_argument("--push-alert", action="store_true",
                    help="存在异常时推飞书（launchd 调度默认带此参数）")
    args = ap.parse_args(argv)

    today = date.today()
    day_key = today.isoformat()
    st = collect_status(today)
    issues = st["issues"]
    keys = st["keys"]

    # 3) 去重 + 推送
    state = load_state()
    sent_today = set(state.get(day_key, []))
    new_keys = [k for k in keys if k not in sent_today]
    if new_keys:
        state[day_key] = sorted(set(sent_today) | set(new_keys))
        save_state(state)
    else:
        # 无新异常，清空当日状态（恢复正常后不再记住旧告警；跨日自动换 key）
        if day_key in state and not new_keys and not issues:
            state[day_key] = []
            save_state(state)

    if issues:
        print("[监控] %s 异常 %d 项：" % (today, len(issues)))
        for line in issues:
            print("  ✗ " + line)
        if args.push_alert and new_keys:
            from scripts.invest_research import push_feishu
            body = "贪恐系统数据监控告警（%s）\n" % today + "\n".join("• " + x for x in issues)
            ok, msg = push_feishu(body)
            print("[监控] 飞书推送：%s" % ("成功" if ok else "失败 " + str(msg)))
        return 1

    print("[监控] %s 全部正常：%d 项数据新鲜，%d 个定时任务注册在位"
          % (today, len(DATA_CHECKS), len(TASKS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
