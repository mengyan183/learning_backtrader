#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从**进程**反查 Clash 真正的配置目录 + 逐节点测 OKX（2026-11-28 v3）。

【v1/v2 为什么失败】
  v1：只读第一个存在的配置 ⇒ 读到 `~/.config/clash/config.yaml`（663 B / 6 规则 / 0 组）
  v2：列全部候选 ⇒ **只有那一个文件存在**，其余路径都不存在 ✗
      但 9090 端口返回 **401**（不是 refused）⇒ **有 Clash 在跑**，
      只是配置不在我猜的路径里 ✗

【v3 的思路：不问文件，问进程】
  ① `ps aux` 找 clash / mihomo / verge / sing-box 进程，
     从命令行拿 `-d <配置目录>` / `-f <配置文件>` ✓
  ② `lsof -nP -iTCP:9090 -sTCP:LISTEN` 找**谁在占 9090** ✓
  ③ 拿到 pid 后 `lsof -p <pid>` 看它**打开了哪些 config.yaml** ✓
  ④ 读那个配置的 rules / proxy-groups / secret ✓
  ⑤ 逐节点测 OKX ✓

【安全】
  只读：ps / lsof / 读文件 / GET API ✗
  **不 kill、不 PUT、不改配置** ✓
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

TEST_URL = "https://www.okx.com/api/v5/public/time"
KEYS = ("okx", "binance", "coinbase", "crypto")
NAMES = ("clash", "mihomo", "verge", "sing-box", "stash", "surge")


def _sh(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout or ""
    except subprocess.TimeoutExpired:
        return ""


def _get(base, path, secret="", timeout=8):
    req = urllib.request.Request(base.rstrip("/") + path)
    if secret:
        req.add_header("Authorization", "Bearer " + secret)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _scan_conf(path):
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    rules, groups, in_r = [], [], False
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
    m = re.search(r"^external-controller:\s*['\"]?([^'\"\s#]+)", txt, re.M)
    ctrl = m.group(1).strip() if m else ""
    m = re.search(r"^secret:\s*['\"]?([^'\"\s#]+)", txt, re.M)
    sec = m.group(1).strip() if m else ""
    return {"path": path, "rules": rules, "groups": groups,
            "ctrl": ctrl, "secret": sec, "size": len(txt)}


def main():
    # ---- ① 找进程 ----
    print("=== ① 相关进程（ps aux）===")
    pat = "|".join(NAMES)
    out = _sh("ps aux | grep -iE '%s' | grep -v grep" % pat)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    for ln in lines[:10]:
        print("  " + ln[:200])
    if not lines:
        print("  ⚠️ 没找到 clash/mihomo/verge 进程")

    # 从命令行提取 -d / -f / -config
    cands = set()
    for ln in lines:
        for m in re.finditer(r"(?:-d|--config-dir)\s+(\S+)", ln):
            cands.add(os.path.expanduser(m.group(1).strip("'\"")))
        for m in re.finditer(r"(?:-f|--config)\s+(\S+\.ya?ml)", ln):
            cands.add(os.path.expanduser(m.group(1).strip("'\"")))

    # ---- ② 谁占 9090 ----
    print("\n=== ② 谁在监听 9090 / 常见 controller 端口 ===")
    for port in (9090, 9091, 6170, 9097):
        o = _sh("lsof -nP -iTCP:%d -sTCP:LISTEN 2>/dev/null" % port)
        rows = [r for r in o.splitlines() if r.strip()][1:]
        if rows:
            print("  :%d  %s" % (port, rows[0][:160]))
            pid = rows[0].split()[1]
            # ---- ③ 该 pid 打开的 config.yaml ----
            po = _sh("lsof -p %s 2>/dev/null | grep -iE '\\.ya?ml$'" % pid)
            for pl in po.splitlines():
                p = pl.split()[-1]
                if os.path.isfile(p):
                    cands.add(p)
                    print("       ↳ 打开的文件：%s" % p)

    # ---- ④ 读配置 ----
    print("\n=== ③ 候选配置（按代理组数降序）===")
    scanned = []
    for p in sorted(cands):
        s = _scan_conf(p)
        if s:
            scanned.append(s)
            tail = s["rules"][-1] if s["rules"] else "（无）"
            print("  %-58s %6dB 规则%-4d 组%-3d MATCH→%s"
                  % (p.replace(os.path.expanduser("~"), "~"),
                     s["size"], len(s["rules"]), len(s["groups"]), tail))
    if not scanned:
        print("  ⚠️ 一个都没读到")

    best = max(scanned, key=lambda s: (len(s["groups"]), len(s["rules"])),
               default=None)
    if not best:
        return 1
    print("\n=== ④ 判定为生效配置 ===")
    print("  %s" % best["path"])
    print("  规则 %d · 组 %d · controller=%r · secret=%s"
          % (len(best["rules"]), len(best["groups"]), best["ctrl"],
             "（有）" if best["secret"] else "（无）"))
    print("  加密交易所相关规则：")
    hit = [r for r in best["rules"] if any(k in r.lower() for k in KEYS)]
    print("    " + ("\n    ".join(hit) if hit else "⚠️ 无"))
    print("  尾部 5 条：")
    for r in best["rules"][-5:]:
        print("    " + r)

    # ---- ⑤ API ----
    ctrl = best["ctrl"] or "127.0.0.1:9090"
    base = ctrl if ctrl.startswith("http") else "http://" + ctrl
    print("\n=== ⑤ API 探活 + 逐节点测 OKX（%s）===" % base)
    secs = [best["secret"]] if best["secret"] else []
    secs += ["", "clash", "123456"]          # 常见默认值，只试 GET
    proxies = None
    for s in secs:
        try:
            v = _get(base, "/version", s, 5)
            print("  ✅ /version（secret=%r）：%s" % (s, v))
            proxies = _get(base, "/proxies", s, 8)
            print("  ✅ /proxies 拿到 %d 项"
                  % len((proxies.get("proxies") or {})))
            best["secret"] = s
            break
        except Exception as e:                  # noqa: BLE001
            print("  ❌ secret=%r：%s" % (s, str(e)[:60]))

    if proxies is None:
        print("\n⛔ 拿不到 /proxies ⇒ 无法逐节点测 OKX ✗")
        print("   ⇒ 请在 ClashX/Verge 的设置里看 `secret`，或把它清空后重跑")
        return 1

    data = proxies.get("proxies") or {}
    skip = {"Selector", "URLTest", "Fallback", "LoadBalance",
            "Direct", "Reject", "Compatible", "Pass"}
    nodes = [n for n, v in data.items()
             if v.get("type") not in skip and n not in ("DIRECT", "REJECT")]
    print("\n  节点 %d 个" % len(nodes))
    ok = []
    for n in nodes[:60]:
        q = urllib.parse.quote(n, safe="")
        u = ("/proxies/%s/delay?url=%s&timeout=5000"
             % (q, urllib.parse.quote(TEST_URL, safe="")))
        try:
            r = _get(base, u, best["secret"], 10)
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
    else:
        print("\n判读：❌ 所有节点都不通 OKX ⇒ 换机场/协议")
    return 0


if __name__ == "__main__":
    sys.exit(main())
