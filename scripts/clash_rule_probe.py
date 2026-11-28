#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClashX 规则检查 + **逐节点测 OKX**（2026-11-28）。

【要回答的两个问题】
  Q1 **ClashX 里 OKX 走的是哪条规则？** —— 读配置里的 `rules:`
  Q2 **方案 B（改分流规则）可行吗？** —— 用 Clash 的 external-controller
     API **逐个节点**测 `https://www.okx.com` 的延迟 ✗
     若存在能通的节点 ⇒ 只要把 okx 规则指到那个节点/组就行 ✓
     若全部不通 ⇒ 换节点也没用，只能换机场/协议 ✗

【为什么用 API 而不是 curl -x】
  `curl -x` 测的是「**当前选中**的那个节点」✗
  Clash API 的 `/proxies/<name>/delay?url=...` 可以**指定任意节点**测 ✓
  ⇒ 一次跑完就能知道「哪个节点能通 OKX」

【安全】
  只 GET（读 proxies / rules）+ 只 GET delay（触发一次探测）✗
  **不 PUT**（不切换节点、不改配置）✓
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

#: Clash 常见配置位置（ClashX / ClashX Pro / Clash Verge）
CONF_CANDIDATES = [
    os.path.expanduser("~/.config/clash/config.yaml"),
    os.path.expanduser("~/.config/clash/profiles"),
    os.path.expanduser("~/Library/Application Support/ClashX/config.yaml"),
    os.path.expanduser("~/.config/clash-verge/profiles"),
]

#: 被测 URL（OKX 公开端点，不需签名）
TEST_URL = "https://www.okx.com/api/v5/public/time"
#: 关键词：命中就打印对应规则
KEYS = ("okx", "binance", "coinbase", "crypto", "binance")


def _find_conf():
    """找一个含 `rules:` 的 yaml（ClashX 的 profiles 是目录，取最大的那个）"""
    for p in CONF_CANDIDATES:
        if os.path.isfile(p):
            return p
        if os.path.isdir(p):
            files = [os.path.join(p, f) for f in os.listdir(p)
                     if f.endswith((".yaml", ".yml"))]
            files = [f for f in files if os.path.isfile(f)]
            if files:
                return max(files, key=os.path.getsize)
    return None


def _parse(conf):
    """极简 yaml 解析：只取 `external-controller` / `secret` / `rules` / 组名。

    ⚠️ 不引 yaml 依赖（lazy）—— 这几项都是单行/`- ` 列表，正则够用 ✓
    """
    txt = open(conf, encoding="utf-8", errors="replace").read()
    out = {"conf": conf, "rules": [], "groups": []}
    m = re.search(r"^external-controller:\s*['\"]?([^'\"\s]+)", txt, re.M)
    out["controller"] = m.group(1) if m else "127.0.0.1:9090"
    m = re.search(r"^secret:\s*['\"]?([^'\"\s]+)", txt, re.M)
    out["secret"] = m.group(1) if m else ""
    # rules 段：`- DOMAIN-SUFFIX,okx.com,PROXY`
    in_rules = False
    for ln in txt.splitlines():
        if re.match(r"^rules:\s*$", ln):
            in_rules = True
            continue
        if in_rules:
            if ln and not ln.startswith((" ", "-", "\t")):
                in_rules = False
                continue
            m = re.match(r"^\s*-\s*(.+)$", ln)
            if m:
                out["rules"].append(m.group(1).strip())
    # proxy-groups 名
    for m in re.finditer(r"^\s{2}-\s*name:\s*['\"]?([^'\"\n]+)", txt, re.M):
        out["groups"].append(m.group(1).strip())
    return out


def _api(base, path, secret="", timeout=8):
    req = urllib.request.Request(base.rstrip("/") + path)
    if secret:
        req.add_header("Authorization", "Bearer " + secret)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    conf = _find_conf()
    if not conf:
        print("❌ 找不到 Clash 配置（查过：%s）" % ", ".join(CONF_CANDIDATES))
        return 1
    info = _parse(conf)
    print("=== 配置文件 ===")
    print("  %s" % conf)
    print("  external-controller: %s   secret: %s"
          % (info["controller"], "（有）" if info["secret"] else "（无）"))
    print("  规则 %d 条 · 代理组 %d 个"
          % (len(info["rules"]), len(info["groups"])))

    print("\n=== Q1. 命中加密交易所的规则 ===")
    hit = [r for r in info["rules"]
           if any(k in r.lower() for k in KEYS)]
    if hit:
        for r in hit:
            print("  " + r)
    else:
        print("  ⚠️ **没有任何针对 okx/binance/coinbase 的规则**")
        print("     ⇒ 它们走的是最后一条 `MATCH`（通常是默认组/REJECT）")

    print("\n=== 规则尾部（MATCH 兜底）===")
    for r in info["rules"][-5:]:
        print("  " + r)

    # ---- Q2：逐节点测 OKX ----
    base = info["controller"]
    if not base.startswith("http"):
        base = "http://" + base
    print("\n=== Q2. 逐节点测 OKX（%s）===" % TEST_URL)
    try:
        px = _api(base, "/proxies", info["secret"])
    except Exception as e:                      # noqa: BLE001
        print("  ❌ 连不上 Clash API（%s）：%s" % (base, e))
        print("  ⇒ 可能没开 `external-controller`，或端口不是 9090")
        return 1

    data = px.get("proxies") or {}
    # 只挑**真实节点**（type 是 SS/Vmess/Trojan 等，不是 Selector/URLTest/DIRECT/REJECT）
    skip = {"Selector", "URLTest", "Fallback", "LoadBalance",
            "Direct", "Reject", "Compatible", "Pass"}
    nodes = [n for n, v in data.items()
             if v.get("type") not in skip and n not in ("DIRECT", "REJECT")]
    print("  候选节点 %d 个" % len(nodes))

    ok_nodes = []
    for n in nodes[:60]:                        # 最多测 60 个，防太慢
        q = urllib.parse.quote(n, safe="")
        u = ("/proxies/%s/delay?url=%s&timeout=5000"
             % (q, urllib.parse.quote(TEST_URL, safe="")))
        try:
            r = _api(base, u, info["secret"], timeout=10)
            d = r.get("delay")
            if isinstance(d, int) and d > 0:
                ok_nodes.append((n, d))
                print("  ✅ %-28s %d ms" % (n[:28], d))
        except Exception:                       # noqa: BLE001
            pass                                # 超时/失败都算不通，不打印（太多）

    print("\n  **能通 OKX 的节点：%d / %d**" % (len(ok_nodes), len(nodes)))
    if ok_nodes:
        best = min(ok_nodes, key=lambda x: x[1])
        print("  最快：%s（%d ms）" % best)
        print("\n判读：✅ **方案 B 可行** —— 把 okx 规则指到上面任一个节点/组即可 ✓")
        print("      在 ClashX 里加：`- DOMAIN-SUFFIX,okx.com,%s`" % best[0])
    else:
        print("\n判读：❌ **方案 B 不可行** —— 所有节点都不通 OKX ✗")
        print("      ⇒ 换节点/改规则都没用，需要换机场或换协议 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
