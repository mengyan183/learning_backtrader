#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境自检：确认 `fg_system` 可导入、关键目录存在、数据文件新鲜度 ✓。

【为什么】
    2026-11-19 每日链报 `失败：No module named 'fg_system'` ✗
    但 `shoutu_daily.sh` 明确有 `cd "$REPO"` ⇒ 路径没问题 ✗
    ⇒ 怀疑 `fg-sync` 入库的 `git` 操作窗口内 `fg_system/` 短暂不可用 ✗
    ⇒ 需要一个**能远程跑**的自检脚本，把「解释器 / cwd / 包位置 /
      数据目录 / 文件新鲜度」一次性打出来 ✓

【用法】
    python3 scripts/env_check.py            # 人看的表格
    python3 scripts/env_check.py --json     # 机器解析

【判据】
    `fg_system_importable` 为 False ⇒ 每日链必然失败 ⇒ 优先修这个 ✓
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 🔴 2026-11-19：**必须把仓库根插到 `sys.path`** ✗
#    实测 `python scripts/env_check.py` 时 `sys.path[0]` 是 `scripts/` ✗
#    ⇒ `import fg_system` 报 `ModuleNotFoundError` ✗
#    ⇒ 这是**脚本自身**的路径问题，不是环境问题 ✓
#    （`python -c "..."` 的 `sys.path[0]` 是 `''`（cwd）⇒ 没这个问题）
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def _age_hours(path):
    try:
        return round((time.time() - os.path.getmtime(path)) / 3600.0, 2)
    except OSError:
        return None


def check():
    out = {
        "python": sys.executable,
        "version": sys.version.split()[0],
        "cwd": os.getcwd(),
        "repo": BASE,
        "repo_exists": os.path.isdir(BASE),
        "fg_system_dir": os.path.join(BASE, "fg_system"),
        "fg_system_dir_exists": os.path.isdir(os.path.join(BASE, "fg_system")),
        "fg_system_init_exists": os.path.isfile(
            os.path.join(BASE, "fg_system", "__init__.py")),
        "sys_path_head": [p for p in sys.path[:5]],
        "data_dir_exists": os.path.isdir(os.path.join(BASE, "Data")),
    }

    # ① 能否导入 fg_system（最关键）
    try:
        import fg_system  # noqa: F401
        out["fg_system_importable"] = True
        out["fg_system_file"] = getattr(fg_system, "__file__", None)
    except Exception as e:                      # noqa: BLE001
        out["fg_system_importable"] = False
        out["fg_system_error"] = "%s: %s" % (type(e).__name__, e)

    # ② 能否导入 fg_system.data.fetch（每日链真正用到的）
    try:
        from fg_system.data import fetch    # noqa: F401
        out["fetch_importable"] = True
    except Exception as e:                      # noqa: BLE001
        out["fetch_importable"] = False
        out["fetch_error"] = "%s: %s" % (type(e).__name__, e)

    # ③ 关键数据文件的新鲜度
    files = {
        "features.csv": os.path.join(BASE, "Data", "features.csv"),
        "positions.csv": os.path.join(BASE, "Data", "positions.csv"),
        "realtime_state.json": os.path.join(BASE, "Data", "realtime_state.json"),
        "realtime_errors.log": os.path.join(BASE, "Data", "realtime_errors.log"),
        "state.json": os.path.join(BASE, "Data", "state.json"),
    }
    out["files"] = {}
    for k, p in files.items():
        out["files"][k] = {
            "exists": os.path.isfile(p),
            "size": os.path.getsize(p) if os.path.isfile(p) else None,
            "age_hours": _age_hours(p),
        }

    # ④ features.csv 尾行日期（判断六因子是否滞后）
    try:
        fp = os.path.join(BASE, "Data", "features.csv")
        with open(fp, encoding="utf-8") as f:
            last = None
            for line in f:
                if line.strip():
                    last = line
        if last:
            out["features_last_date"] = last.split(",")[0]
    except OSError as e:
        out["features_last_date"] = "ERR %s" % e

    out["checked_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = check()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r.get("fg_system_importable") else 1
    print("python      : %s (%s)" % (r["python"], r["version"]))
    print("cwd         : %s" % r["cwd"])
    print("repo        : %s  exists=%s" % (r["repo"], r["repo_exists"]))
    print("fg_system   : dir=%s  init=%s  importable=%s"
          % (r["fg_system_dir_exists"], r["fg_system_init_exists"],
             r.get("fg_system_importable")))
    if r.get("fg_system_error"):
        print("  ERROR     : %s" % r["fg_system_error"])
    if r.get("fg_system_file"):
        print("  loaded    : %s" % r["fg_system_file"])
    print("fetch       : importable=%s" % r.get("fetch_importable"))
    if r.get("fetch_error"):
        print("  ERROR     : %s" % r["fetch_error"])
    print("Data/       : exists=%s" % r["data_dir_exists"])
    print("features 尾行: %s" % r.get("features_last_date"))
    print("文件新鲜度（小时）:")
    for k, v in r["files"].items():
        print("  %-22s exists=%-5s age=%s" % (k, v["exists"], v["age_hours"]))
    return 0 if r.get("fg_system_importable") else 1


if __name__ == "__main__":
    sys.exit(main())
