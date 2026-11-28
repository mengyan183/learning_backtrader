#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClashX 规则检查 v2 —— **找出真正的配置** + 逐节点测 OKX（2026-11-28）。

【v1 的发现与教训】
  v1 只读了**第一个存在**的配置：
    `/Users/xingguo/.config/clash/config.yaml` —— 只有 **6 条规则 / 0 个代理组**
    尾部是 **`MATCH,DIRECT`** ✗
  ⇒ 那个文件里**所有未匹配流量都直连** ⇒ `curl -x 127.0.0.1:7890`
    实际走的是 DIRECT ⇒ 之前「经代理测 OKX 失败」的结论**是假的** ✗
    真相：那些请求**根本没经过代理节点** ✓

  而且 Clash API 返回 **401**（说明有 secret，但 v1 的正则没读到）✗

【v2 改什么】
  ① **列出全部**候选配置（不只第一个），逐个打印规则数/组数/MATCH 兜底 ✗
  ② secret 用**多模式**提取（`secret:` / `external-controller` 同行 / 引号变体）
  ③ API 端口尝试：config 里的值 + 常见 9090/9091/6170
  ④ 先 `GET /version` 探活（不需要 secret），再试带 secret 的 `/proxies`
  ⑤ 找到有代理组的那个配置后再逐节点测 OKX ✓
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

TEST_URL = "https://www.okx.com/api/v5/public/time"
KEYS = ("okx", "binance", "coinbase", "crypto")

#: 所有候选（目录的会展开成里面的 yaml）
CAND = [
    os.path.expanduser("~/Library/Application Support/ClashX/config.yaml"),
    os.path.expanduser("~/Library/Application Support/ClashX/profiles"),
    os.path.expanduser("~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles"),
    os.path.expanduser("~/.config/clash/config.yaml"),
    os.path.expanduser("~/.config/clash/profiles"),
    os.path.expanduser("~/.config/clash-verge/profiles"),
    os.path.expanduser("~/.config/mihomo/config.yaml"),
]

SECRET_PATS = [
    r"^secret:\s*['\"]?([^'\"\s#]+)",
    r"^external-controller:[^\n]*\n\s*secret:\s*['\"]?([^'\"\s#]+)",
]
CTRL_PATS = [
    r"^external-controller:\s*['\"]?([^'\"\s#]+)",
    r"^external-controller:\s*['\"]?([^\s'\"]+:\d+)",
]


def _all_files():
    """展开全部候选，返回 [(路径, 大小)]，按大小降序（大的更可能是真配置）"""
    out = []
    for p in CAND:
        if os.path.isfile(p):
            out.append((p, os.path.getsize(p)))
        elif os.path.isdir(p):
            for f in os.listdir(p):
                if f.endswith((".yaml", ".yml")):
                    fp = os.path.join(p, f)
                    if os.path.isfile(fp):
                        out.append((fp, os.path.getsize(fp)))
    return sorted(set(out), key=lambda x: -x[1])


def _scan(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    rules, groups = [], []
    in_r = False
    for ln in txt.splitlines():
        if re.match(r"^rules:\s*$", ln):
            in_r = True
            continue
        if in_r:
            if ln and not ln.startswith((" ", "-", "\t")):
                in_r = False
                continue
            m = re.match(r"^\s*-\s*(.+)$", ln)
            if m:
                rules.append(m.group(1).strip())
    for m in re.finditer(r"^\s{2}-\s*name:\s*['\"]?([^'\"\n]+)", txt, re.M):
        groups.append(m.group(1).strip())
    ctrl = ""
    for pat in CTRL_PATS:
        m = re.search(pat, txt, re.M)
        if m:
            ctrl = m.group(1).strip()
            break
    sec = ""
    for pat in SECRET_PATS:
        m = re.search(pat, txt, re.M)
        if m:
            sec = m.group(1).strip()
            break
    return {"rules": rules, "groups": groups,
            "ctrl": ctrl or "127.0.0.1:9090", "secret": sec, "size": len(txt)}


def _get(base, path, secret="", timeout=8):
    req = urllib.request.Request(base.rstrip("/") + path)
    if secret:
        req.add_header("Authorization", "Bearer " + secret)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    files = _all_files()
    if not files:
        print("❌ 一个候选配置都没找到：%s" % ", ".join(CAND))
        return 1

    print("=== ① 全部候选配置（按大小降序）===")
    best = None
    for p, sz in files:
        s = _scan(p)
        tail = s["rules"][-1] if s["rules"] else "（无规则）"
        print("  %-64s %6d B  规则%-4d 组%-3d MATCH→%s"
              % (p.replace(os.path.expanduser("~"), "~"), sz,
                 len(s["rules"]), len(s["groups"]), tail))
        if best is None or (len(s["groups"]), len(s["rules"])) > \
                (len(best[1]["groups"]), len(best[1]["rules"])):
            best = (p, s)

    if not best:
        return 1
    path, info = best
    print("\n=== ② 判定为**当前生效**的配置 ===")
    print("  %s" % path)
    print("  规则 %d 条 · 代理组 %d 个 · controller=%s · secret=%s"
          % (len(info["rules"]), len(info["groups"]), info["ctrl"],
             "（有）" if info["secret"] else "（无）"))

    print("\n=== ③ 命中加密交易所的规则 ===")
    hit = [r for r in info["rules"] if any(k in r.lower() for k in KEYS)]
    if hit:
        for r in hit:
            print("  " + r)
    else:
        print("  ⚠️ 没有专门规则")
    print("  尾部 5 条：")
    for r in info["rules"][-5:]:
        print("    " + r)

    # ---- ④ API 探活 ----
    base = info["ctrl"]
    if not base.startswith("http"):
        base = "http://" + base
    print("\n=== ④ Clash API 探活（%s）===" % base)
    sec = info["secret"]
    try:
        v = _get(base, "/version", "", 5)
        print("  ✅ /version（无需 secret）：%s" % v)
    except Exception as e:                      # noqa: BLE001
        print("  ❌ /version 失败：%s" % e)
        print("  ⇒ controller 未开或端口不对")
        return 1

    proxies = None
    for s in ([sec, ""] if sec else [""]):
        try:
            proxies = _get(base, "/proxies", s, 8)
            print("  ✅ /proxies（secret=%s）"
                  % ("用配置里的" if s else "空"))
            break
        except Exception as e:                  # noqa: BLE001
            print("  ❌ /proxies（secret=%s）：%s"
                  % ("用配置里的" if s else "空", e))

    if proxies is None:
        print("\n⛔ 拿不到 /proxies ⇒ 无法逐节点测 OKX ✗")
        print("   ⇒ 请在 ClashX 设置里确认 `external-controller` 的 secret，")
        print("     或把它设为空（`secret: \"\"`）后重跑 ✓")
        return 1

    # ---- ⑤ 逐节点测 OKX ----
    data = proxies.get("proxies") or {}
    skip = {"Selector", "URLTest", "Fallback", "LoadBalance",
            "Direct", "Reject", "Compatible", "Pass"}
    nodes = [n for n, v in data.items()
             if v.get("type") not in skip and n not in ("DIRECT", "REJECT")]
    print("\n=== ⑤ 逐节点测 OKX（%d 个节点）===" % len(nodes))
    ok = []
    for n in nodes[:60]:
        q = urllib.parse.quote(n, safe="")
        u = ("/proxies/%s/delay?url=%s&timeout=5000"
             % (q, urllib.parse.quote(TEST_URL, safe="")))
        try:
            r = _get(base, u, sec, 10)
            d = r.get("delay")
            if isinstance(d, int) and d > 0:
                ok.append((n, d))
                print("  ✅ %-30s %d ms" % (n[:30], d))
        except Exception:                       # noqa: BLE001
            pass

    print("\n  **能通 OKX：%d / %d**" % (len(ok), len(nodes)))
    if ok:
        b = min(ok, key=lambda x: x[1])
        print("  最快：%s（%d ms）" % b)
        print("\n判读：✅ 方案 B 可行 ⇒ 加规则：")
        print("      - DOMAIN-SUFFIX,okx.com,%s" % b[0])
        print("      - DOMAIN-SUFFIX,okx.com 之外还要加 binance/coinbase（同类）")
    else:
        print("\n判读：❌ 所有节点都不通 OKX ⇒ 换机场/协议，改规则无用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
