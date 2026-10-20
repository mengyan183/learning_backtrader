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
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

STATE_FILE = REPO / "Data" / "monitor_state.json"

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
]

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
}


def _task_last_run(label: str):
    """读任务日志 mtime 作为最近运行时间近似：候选文件里取**最新**的那个。

    返回 (格式化时间, 命中文件路径)；无任何候选文件存在时返回 (None, None)。
    """
    best_mt, best_p = None, None
    for rel in TASK_LOG.get(label) or []:
        p = Path(rel) if rel.startswith("/") else REPO / rel
        if not p.exists():
            continue
        mt = p.stat().st_mtime
        if best_mt is None or mt > best_mt:
            best_mt, best_p = mt, p
    if best_mt is None:
        return None, None
    return datetime.fromtimestamp(best_mt).strftime("%Y-%m-%d %H:%M"), best_p


def _last_date_csv(path: Path, col: str):
    """全量扫描取 date 列最大值（文件按日期追加，仍取 max 防乱序）。"""
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if col not in (reader.fieldnames or []):
            return None
        mx = None
        for row in reader:
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
        ok = t in registered
        last_run, last_run_file = _task_last_run(t)
        task_rows.append({"label": t, "registered": ok, "ok": ok,
                          "last_run": last_run,
                          "last_run_file": str(last_run_file) if last_run_file else None})
        if not ok:
            issues.append("定时任务未注册：%s" % t)
            keys.append("task:%s" % t)

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
