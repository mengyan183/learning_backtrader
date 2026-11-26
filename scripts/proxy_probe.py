#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测 `127.0.0.1:7890` 是否可用，以及 Kalshi 是否被节点屏蔽（2026-11-26）。

【背景】
  `fetch_kalshi_fed.py` 硬编码 `PROXY = "http://127.0.0.1:7890"` ✓
  任务队列已注入同样的代理（`has_proxy: true`）✓
  但抓取仍报 `[Errno 54] Connection reset by peer`，5.1 秒 ✗

  ⇒ 三种可能，必须分开：
    ① **代理没跑**（ClashX 关了 / 换端口）⇒ TCP 连不上
    ② **代理在跑，但节点屏蔽 Kalshi** ⇒ 别的站点通，kalshi 不通
    ③ **代理在跑，Kalshi 自己也挂了** ⇒ 都通，kalshi 报 5xx

【本脚本查什么】
  ① TCP 连通：`127.0.0.1:7890` 能否 connect
  ② 经代理访问**通用站点**（example.com）⇒ 代理本身能不能转发 https
  ③ 经代理访问 **Kalshi** 端点 ⇒ 是否只有它被屏蔽
  ④ 直连 Kalshi（不走代理）⇒ 对比基线
"""
from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.request

PROXY = "http://127.0.0.1:7890"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


def _get(url, proxy=None, timeout=15):
    """GET 一个 URL；`proxy=None` ⇒ 直连。返回 (ok, 摘要)。"""
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}))       # 显式**不用**环境代理
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read(200)
            return True, "HTTP %s, %d bytes" % (r.status, len(body))
    except urllib.error.HTTPError as e:
        return False, "HTTPError %s" % e.code
    except Exception as e:                          # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:120])


def main():
    # ① TCP
    host, port = "127.0.0.1", 7890
    try:
        with socket.create_connection((host, port), timeout=3):
            tcp_ok, tcp_msg = True, "可连接 ✓"
    except Exception as e:                          # noqa: BLE001
        tcp_ok, tcp_msg = False, "%s: %s" % (type(e).__name__, e)
    print("=== ① TCP %s:%d ===" % (host, port))
    print("  %s %s" % ("✅" if tcp_ok else "❌", tcp_msg))

    # ② 经代理访问通用站点
    ok2, m2 = _get("https://example.com", PROXY)
    print("\n=== ② 经代理 → example.com ===")
    print("  %s %s" % ("✅" if ok2 else "❌", m2))

    # ③ 经代理访问 Kalshi
    ok3, m3 = _get("https://external-api.kalshi.com/trade-api/v2"
                   "/exchange/status", PROXY)
    print("\n=== ③ 经代理 → Kalshi /exchange/status ===")
    print("  %s %s" % ("✅" if ok3 else "❌", m3))

    # ④ 直连 Kalshi
    ok4, m4 = _get("https://external-api.kalshi.com/trade-api/v2"
                   "/exchange/status", None)
    print("\n=== ④ 直连 → Kalshi /exchange/status ===")
    print("  %s %s" % ("✅" if ok4 else "❌", m4))

    print("\n判读：")
    print("  · ① ❌ ⇒ **ClashX 没跑或端口不对** ⇒ 打开 ClashX / 改 FG_FETCH_PROXY")
    print("  · ① ✅ 但 ② ❌ ⇒ 代理进程在但**不转发**（规则/订阅问题）")
    print("  · ② ✅ 但 ③ ❌ ⇒ **该节点屏蔽 Kalshi** ⇒ 换节点或加分流规则")
    print("  · ③ ❌ 且 ④ ✅ ⇒ 直连反而通 ⇒ 代理是**累赘**，把 kalshi 移出 NEEDS_PROXY")
    print("  · ③ ④ 都 ❌ ⇒ Kalshi 侧问题（或全网不可达）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
