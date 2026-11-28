#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""代理可用性探针（2026-11-28）—— 每日链**第一步**跑。

【为什么需要】
  2026-11-26~28 三天里，三个步骤同时失败：
    `sync_positions.py`            rc=1  ← OKX 抓不到
    `fetch_kalshi_fed.py`          rc=2  ← kalshi 抓不到
    `fetch_stablecoin_usage.py`    rc=2  ← CoinGecko 抓不到
  每个都像「独立的 bug」✗ 实际是**同一个根因：ClashX 订阅到期** ✗
  ⇒ 报了 3 条告警，没有一条说「代理挂了」✗

【本脚本做什么】
  ① TCP 探 `127.0.0.1:7890`
  ② 经代理访问**一个被墙站点**（`www.google.com`）—— 这是关键 ✗
     只测 `example.com` 没用：它国内能直连，测不出代理是否生效 ✗
  ③ 经代理访问 OKX / CoinGecko（业务实际依赖的）
  ④ 结果写入 `Data/proxy_health.json` + 一行结论

【判读】
  ② 不通 ⇒ **代理失效**（订阅到期 / 节点全挂）⇒ 所有网络步骤的失败都归因于此 ✓
  ② 通但 ③ 不通 ⇒ 代理正常但**特定站点被分流** ⇒ 只影响对应业务 ✓
  全通 ⇒ 代理正常 ✓

【退出码】
  0 = 代理正常；2 = 代理失效（**让每日链报红**，不要静默）✓
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "Data", "proxy_health.json")
PROXY = "http://127.0.0.1:7890"

#: ② 的判据：**被墙站点**（国内直连不通，只有代理能通）✓
WALLED = "https://www.google.com/generate_204"
#: ③ 业务实际依赖的站点
BIZ = [
    ("okx", "https://www.okx.com/api/v5/public/time"),
    ("coingecko", "https://api.coingecko.com/api/v3/ping"),
    ("kalshi", "https://external-api.kalshi.com/trade-api/v2/exchange/status"),
]


def _tcp(host="127.0.0.1", port=7890, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except Exception as e:                      # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:80])


def _curl(url, proxy=PROXY, timeout=15):
    cmd = ["curl", "-sS", "-m", str(timeout), "-o", "/dev/null",
           "-w", "%{http_code}", url]
    if proxy:
        cmd[1:1] = ["-x", proxy]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout + 8)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()[:120]
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def main():
    res = {"proxy": PROXY}

    ok_tcp, why = _tcp()
    res["tcp"] = {"ok": ok_tcp, "why": why}

    rc, code, err = _curl(WALLED)
    # 204 是 google 的正常响应；200 也接受（有些节点改写）
    ok_walled = rc == 0 and code in ("204", "200")
    res["walled"] = {"ok": ok_walled, "http": code, "err": err}

    biz = {}
    for name, url in BIZ:
        rc2, code2, err2 = _curl(url)
        biz[name] = {"ok": rc2 == 0 and code2 == "200",
                     "http": code2, "err": err2}
    res["biz"] = biz

    # ---- 结论 ----
    if not ok_tcp:
        verdict = "🔴 **代理端口不通**（ClashX 没运行？）⇒ 所有网络步骤都会失败 ✗"
        code_out = 2
    elif not ok_walled:
        verdict = ("🔴 **代理失效**（端口通但被墙站点不通）⇒ "
                   "订阅到期 / 节点全挂 ⇒ 所有需翻墙的步骤都会失败 ✗")
        code_out = 2
    else:
        bad = [k for k, v in biz.items() if not v["ok"]]
        if bad:
            verdict = ("🟡 代理正常，但 **%s 不通** ⇒ 只影响对应业务 ✓"
                       % "、".join(bad))
        else:
            verdict = "✅ 代理正常（被墙站点 + 全部业务站点均可达）✓"
        code_out = 0
    res["verdict"] = verdict

    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print("[proxy] 写 %s 失败：%s" % (OUT, e))

    print("[proxy] TCP %s:%s = %s" % ("127.0.0.1", 7890,
                                      "通" if ok_tcp else "不通"))
    print("[proxy] 被墙站点 = %s（http=%s）"
          % ("通" if ok_walled else "不通", res["walled"]["http"] or "-"))
    for name, v in biz.items():
        print("[proxy]   %-10s %s（http=%s）"
              % (name, "✅" if v["ok"] else "❌", v["http"] or "-"))
    print("[proxy] " + verdict)
    return code_out


if __name__ == "__main__":
    sys.exit(main())
