#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OKX 代理连通性 + trades.csv 假 sell 核查（2026-11-27）。

【查三件事】
  ① **代理 → OKX** 是否通（用**公开**端点，不需要签名）
     `sync_positions` 报 `curl 失败:`（stderr 空，因为 `-s` 吞了错误）
     ⇒ 本脚本用 `-sS` 重跑，让 curl 把真实原因打出来 ✓
  ② **`trades.csv` 里有没有 2026-11-26 的 BTC-USDT 卖出**
     —— `merge_trades` 的 MT-63 告警说「反推有、合并无」，
        但告警**不等于没写**；若已写进 trades.csv，成交历史就被污染了 ✗
  ③ `positions.csv` / `accounts.csv` 里 11-26 的 crypto 行还在不在
"""
from __future__ import annotations

import os
import subprocess
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "Data")
PROXY = "http://127.0.0.1:7890"


def _curl(url, proxy=None, timeout=25):
    cmd = ["curl", "-sS", "-m", str(timeout), "-o", "/dev/null",
           "-w", "%{http_code}", url]
    if proxy:
        cmd[1:1] = ["-x", proxy]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout + 10)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT(%ss)" % timeout


def main():
    # ── ① 代理 → OKX ──────────────────────────────────────────
    print("=== ① 代理 → OKX 公开端点（/api/v5/public/time）===")
    for tag, px in (("经代理", PROXY), ("直连", None)):
        rc, out, err = _curl("https://www.okx.com/api/v5/public/time", px)
        ok = "✅" if (rc == 0 and out == "200") else "❌"
        print("  %s %-6s rc=%-3s http=%-4s %s"
              % (ok, tag, rc, out or "-", (err or "")[:120]))

    print("\n=== ①b 对照：代理 → example.com ===")
    rc, out, err = _curl("https://example.com", PROXY)
    print("  %s rc=%s http=%s %s"
          % ("✅" if rc == 0 and out == "200" else "❌", rc, out or "-",
             (err or "")[:100]))

    # ── ② trades.csv 里的 11-26 BTC ──────────────────────────
    tp = os.path.join(DATA, "trades.csv")
    print("\n=== ② trades.csv（%s）===" % ("存在" if os.path.exists(tp) else "缺失"))
    if os.path.exists(tp):
        t = pd.read_csv(tp)
        print("  列：%s" % list(t.columns))
        dcol = next((c for c in ("date", "trade_date", "time") if c in t.columns), None)
        scol = next((c for c in ("symbol", "code") if c in t.columns), None)
        if dcol and scol:
            hit = t[(t[dcol].astype(str).str.startswith("2026-11-26"))
                    & (t[scol].astype(str).str.contains("BTC", na=False))]
            print("  2026-11-26 的 BTC 记录：**%d 条**" % len(hit))
            if len(hit):
                print(hit.to_string(index=False)[:900])
            print("\n  最近 6 条（任意标的）：")
            print(t.tail(6).to_string(index=False)[:700])
        else:
            print("  ⚠️ 找不到日期列或标的列，列名：%s" % list(t.columns))
    else:
        print("  ⚠️ 文件不存在 ⇒ 无法核查（可能只在 Mac 上）")

    # ── ③ positions/accounts 里 11-26 的 crypto ──────────────
    for fn in ("positions.csv", "accounts.csv"):
        p = os.path.join(DATA, fn)
        print("\n=== ③ %s ===" % fn)
        if not os.path.exists(p):
            print("  缺失")
            continue
        df = pd.read_csv(p)
        sub = df[df["date"].astype(str).str.startswith("2026-11-26")]
        print("  11-26 共 %d 行；account 分布：%s"
              % (len(sub), sub["account"].value_counts().to_dict()
                 if "account" in sub.columns else "无 account 列"))
        if "symbol" in sub.columns:
            print("  标的：%s" % sorted(sub["symbol"].unique().tolist()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
