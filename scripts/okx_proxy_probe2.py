#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OKX 代理/直连细分探测（2026-11-28 第二次）。

【上次结论（2026-11-27 `okx_trades_diag.py`）】
  ① 代理 → OKX       ❌ rc=35  Connection reset by peer
  ① 直连 → OKX       ❌ rc=7   Couldn't connect
  ①b 代理 → example  ✅ 200
  ⇒ 判读「节点屏蔽 OKX」

【本次要回答的两个新问题】
  Q1 **为什么代理对 OKX 不生效？** —— 澄清：代理**是生效的**，
     `_okx_request` 用 `curl -x <proxy>`，请求确实经过代理 ✗
     真正发生的是「**代理出口 → OKX 被 RST**」✓
     ⇒ 本脚本用 `-v` 抓握手阶段，看是在 TCP / TLS / HTTP 哪一层被断 ✓
  Q2 **直连是否可以？** —— 上次 rc=7（连不上）✗
     但直连失败也分两种：DNS 解析失败 / TCP 连不上 / TLS 被重置
     ⇒ 分开测 ✓

【测什么】
  A. 直连：DNS 解析 → TCP 443 → TLS → HTTP（逐层）
  B. 经代理：同上，逐层
  C. 对照：经代理访问 **其他交易所**（binance / coinbase）⇒ 是「只有 OKX」还是「所有交易所」
  D. 对照：经代理访问 OKX 的**备用域名**（okx.com / aws.okx.com）
  E. 读 `~/.okx_credentials.json` 的 `proxy` 字段（确认脚本实际用的代理地址）
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

PROXY = "http://127.0.0.1:7890"
CRED = os.path.expanduser("~/.okx_credentials.json")

TARGETS = [
    ("OKX 主域", "https://www.okx.com/api/v5/public/time"),
    ("OKX 备用", "https://okx.com/api/v5/public/time"),
    ("OKX AWS", "https://aws.okx.com/api/v5/public/time"),
    ("Binance", "https://api.binance.com/api/v3/time"),
    ("Coinbase", "https://api.exchange.coinbase.com/time"),
    ("example", "https://example.com"),
]


def _curl(url, proxy=None, timeout=20):
    """返回 (rc, http_code, 错误摘要)。`-v` 抓握手阶段。"""
    cmd = ["curl", "-sS", "-v", "-m", str(timeout), "-o", "/dev/null",
           "-w", "%{http_code}", url]
    if proxy:
        cmd[1:1] = ["-x", proxy]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout + 10)
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    err = (r.stderr or "").strip()
    # 只留关键行：连接阶段 + 错误
    keys = ("Trying", "Connected", "TLS", "SSL", "HTTP/", "curl:",
            "Recv failure", "reset", "refused", "timed out")
    keep = [ln.strip() for ln in err.splitlines()
            if any(k.lower() in ln.lower() for k in keys)]
    return r.returncode, (r.stdout or "").strip(), " | ".join(keep[-4:])[:300]


def _dns(host):
    try:
        ips = sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443)})
        return "✅ " + ", ".join(ips[:3])
    except Exception as e:                      # noqa: BLE001
        return "❌ %s: %s" % (type(e).__name__, str(e)[:60])


def main():
    print("=== E. 脚本实际用的代理地址 ===")
    if os.path.exists(CRED):
        try:
            c = json.load(open(CRED))
            print("  creds['proxy'] = %r" % c.get("proxy"))
            print("  ⇒ `sync_positions._okx_request` 用的是这个值（不是硬编码）")
        except Exception as e:                  # noqa: BLE001
            print("  读凭据失败：%s" % e)
    else:
        print("  ⚠️ %s 不存在" % CRED)
    print("  本脚本探测用的代理：%r" % PROXY)

    print("\n=== A. DNS 解析（直连前必看）===")
    for h in ("www.okx.com", "okx.com", "aws.okx.com", "api.binance.com"):
        print("  %-16s %s" % (h, _dns(h)))

    print("\n=== B. 经代理 逐目标（含握手阶段）===")
    for tag, url in TARGETS:
        rc, code, err = _curl(url, PROXY)
        ok = "✅" if (rc == 0 and code == "200") else "❌"
        print("  %s %-10s rc=%-3s http=%-4s %s"
              % (ok, tag, rc, code or "-", err))

    print("\n=== C. 直连 逐目标（不经代理）===")
    for tag, url in TARGETS[:3] + [("example", "https://example.com")]:
        rc, code, err = _curl(url, None)
        ok = "✅" if (rc == 0 and code == "200") else "❌"
        print("  %s %-10s rc=%-3s http=%-4s %s"
              % (ok, tag, rc, code or "-", err))

    print("\n判读：")
    print("  · 经代理 example/binance 都 ✅ 但 OKX 全 ❌ ⇒ **节点对 OKX 做了分流/屏蔽**")
    print("  · 经代理所有交易所都 ❌ ⇒ **节点整体不通**（换节点）")
    print("  · 直连 DNS ❌ ⇒ 域名被污染；直连 TLS reset ⇒ 被中间设备重置")
    print("  · 直连 OKX ✅ ⇒ **代理是累赘** ⇒ 给 OKX 加 DIRECT 规则或移除 proxy")
    print("  ⚠️ 注意：`_okx_request` 用 `-x`，代理**确实生效** ✗")
    print("     「代理不生效」是误解；实际是「代理出口到 OKX 被 RST」✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
