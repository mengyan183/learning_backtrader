#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**每日链失败汇总告警** ✓（2026-11-03 用户要求）。

【为什么需要】
  `prices.csv` 断流 22 天 ✗ 而简报每天照常生成 ✗ —— 因为
  `fetch.update_prices()` 每天失败 ✗ 但错误只打在
  `/tmp/fg_daily.log` 里 ✗ 被后面 10 个成功步骤的日志淹没 ✗
  ⇒ 加了 `run_guarded.py` 的失败台账 ✓
  ⇒ 本脚本在链末**汇总发一条飞书** ✓

【做什么】
  ① 读 `Data/daily_failures.jsonl`（`run_guarded` 每步失败时追加 ✓）
  ② 有失败 ⇒ 发飞书（一条消息列全部失败步骤 ✓）
  ③ 发完**清空台账** ✓ —— 否则明天会把今天的也发一遍 ✗

【设计取舍】
  - 只发「**一条汇总**」✗ 不逐步发 —— 否则链里有 3 步失败就刷 3 条 ✗
  - 无失败时**静默** ✓ 不打扰 ✓
  - 发飞书失败时**保留台账** ✓ 下次重试 ✓

用法：
  .venv/bin/python scripts/report_daily_failures.py
  .venv/bin/python scripts/report_daily_failures.py --dry-run
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

FAIL_LOG = REPO / "Data" / "daily_failures.jsonl"


def _load():
    """读台账 ✓ —— 坏行跳过（不因一行坏了就丢全部 ✗）。"""
    if not FAIL_LOG.exists():
        return []
    out = []
    for ln in FAIL_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def _format(recs):
    """拼飞书消息 ✓ —— 每条一行，超长截断 ✓。"""
    lines = ["**每日链失败告警**（%d 步）" % len(recs), ""]
    for r in recs:
        tag = "⏱超时" if r.get("timeout") else "rc=%s" % r.get("rc")
        lines.append("· `%s` —— %s（%.0fs）"
                     % (r.get("cmd", "?")[:70], tag,
                        float(r.get("seconds") or 0)))
    lines += ["", "详情：`/tmp/fg_daily.log`"]
    return "\n".join(lines)


def _send(text):
    """复用 `invest_research.push_feishu` ✓ —— 仓库里唯一现成的飞书链路 ✗。

    （`drift_monitor.py:420` 也是这么用的 ✓ 保持一致 ✗）
    """
    try:
        from scripts.invest_research import push_feishu
    except Exception as exc:                # noqa: BLE001
        return False, "导入 push_feishu 失败：%s" % exc
    try:
        ok, msg = push_feishu(text)
        return bool(ok), str(msg or "")[:300]
    except Exception as exc:                # noqa: BLE001
        return False, "推送异常：%s" % exc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印不发飞书 ✓ 也不清台账 ✓")
    args = ap.parse_args(argv)

    recs = _load()
    if not recs:
        print("[failures] 无失败记录 ✓")
        return 0

    print("# 每日链失败汇总（%d 步）\n" % len(recs))
    print("| 时间 | 命令 | rc | 耗时 |")
    print("|---|---|---|---|")
    for r in recs:
        print("| %s | `%s` | %s%s | %.0fs |"
              % (r.get("ts", "?"), str(r.get("cmd", "?"))[:60],
                 r.get("rc"), "（超时）" if r.get("timeout") else "",
                 float(r.get("seconds") or 0)))

    text = _format(recs)
    if args.dry_run:
        print("\n--- 将发送 ---\n%s" % text)
        return 0

    ok, detail = _send(text)
    if not ok:
        print("\n✗ 飞书推送失败（台账**保留** ✓ 下次重试）：%s" % detail)
        return 1
    print("\n✓ 已推送；清空台账")
    try:
        FAIL_LOG.unlink()
    except OSError:
        FAIL_LOG.write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
