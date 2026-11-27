#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装一个**白名单内**的 Python 依赖（2026-11-27）。

【为什么需要】
  队列里没有通用 `pip install` 动作 ✗（只有 futu 专用的那个）
  而 `exchange_calendars` 要在 **Mac 的 .venv** 里装 ✓

【安全边界】
  · `--pkg` 必须在 `ALLOWED` 白名单里 ✗ 否则拒绝
  · 只装到**当前解释器**（`sys.executable -m pip`），不碰系统 python ✓
  · 默认 dry-run，`--apply` 才真装 ✓
  · 装完 `import` 一次验证能导入 ✓
"""
from __future__ import annotations

import subprocess
import sys

#: 允许安装的包（新增依赖必须先加到这里，避免变成万能 pip 后门）✓
ALLOWED = {
    "exchange_calendars",
}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    pkg = args.pkg.strip()
    base = pkg.split("==")[0].split(">=")[0].strip()
    if base not in ALLOWED:
        print("⛔ 不允许安装 `%s`（白名单：%s）" % (pkg, ", ".join(sorted(ALLOWED))))
        return 1

    # 已装则跳过
    r = subprocess.run([sys.executable, "-m", "pip", "show", base],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        ver = next((ln.split(":", 1)[1].strip()
                    for ln in r.stdout.splitlines()
                    if ln.lower().startswith("version")), "?")
        print("✓ `%s` 已装（版本 %s）⇒ 跳过" % (base, ver))
        return 0

    cmd = [sys.executable, "-m", "pip", "install", pkg]
    print("将执行：%s" % " ".join(cmd))
    if not args.apply:
        print("**dry-run**：确认后加 `--apply` ✓")
        return 0

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    print("rc=%s" % r.returncode)
    print((r.stdout or "")[-1200:])
    if r.returncode != 0:
        print((r.stderr or "")[-800:])
        return 1

    # 验证能导入
    v = subprocess.run([sys.executable, "-c", "import %s as m; print(m.__version__)"
                        % base], capture_output=True, text=True, timeout=120)
    if v.returncode != 0:
        print("⚠️ 装完但**导入失败**：%s" % (v.stderr or "")[:300])
        return 1
    print("✅ 导入成功，版本 %s" % (v.stdout or "").strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
