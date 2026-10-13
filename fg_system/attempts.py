# -*- coding: utf-8 -*-
"""A3c 尝试台账（规划 v2.0 A3c）：机器可读的「曾试过 N 次」计数器。

A3a Deflated Sharpe / A3b BH-FDR 需要的 **N** 来自本台账：从批准日起每次
检验追加一条记录，回顾性校正才有数据基础。

路径 `evolution/attempts-ledger.jsonl`，每行一个 JSON 记录：
  {ts, kind, key, verdict, git_sha}
- `ts`：登记时间（ISO 秒级）
- `kind`：`factor_screen` | `variant` | `hypothesis`
- `key`：被检验对象标识（因子名 / 变体名 / 假说编号）
- `verdict`：本次检验结论（如 ok / worse / pending / insufficient / reported）
- `git_sha`：登记时 HEAD（同一提交同一对象只计一次尝试）

**幂等键 = `git_sha + kind + key`**：同一提交对同一对象重复跑脚本不虚增 N
（防「试了很多次」被夸大）。已存在的 (git_sha, kind, key) 跳过、返回 False。
"""
import json
import os
import subprocess
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(REPO, "evolution", "attempts-ledger.jsonl")

KINDS = ("factor_screen", "variant", "hypothesis")


def git_head(repo=None):
    """当前 HEAD（登记时版本）。git 不可用/无提交时回退 "unknown"。"""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"],
                           cwd=repo or REPO, capture_output=True, text=True,
                           timeout=10)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _existing_keys(ledger=None):
    """已有幂等键集合（容忍损坏行，跳过）。"""
    ledger = ledger or LEDGER
    keys = set()
    if os.path.exists(ledger):
        with open(ledger, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                keys.add((rec.get("git_sha"), rec.get("kind"), rec.get("key")))
    return keys


def append_attempt(kind, key, verdict, ledger=None, git_sha=None, ts=None):
    """追加一条尝试记录（幂等）。

    返回 True=已登记；False=重复（同一 git_sha+kind+key 已存在，跳过）。
    """
    assert kind in KINDS, "kind 必须是 %s 之一" % (KINDS,)
    ledger = ledger or LEDGER
    git_sha = git_sha or git_head()
    ts = ts or datetime.now().isoformat(timespec="seconds")
    key = str(key)
    rec = {"ts": ts, "kind": kind, "key": key,
           "verdict": str(verdict), "git_sha": git_sha}
    if (git_sha, kind, key) in _existing_keys(ledger):
        return False
    os.makedirs(os.path.dirname(ledger), exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


def count_attempts(ledger=None, kind=None):
    """台账行数（可按 kind 过滤）。"""
    ledger = ledger or LEDGER
    n = 0
    if not os.path.exists(ledger):
        return n
    with open(ledger, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if kind is None or rec.get("kind") == kind:
                n += 1
    return n
