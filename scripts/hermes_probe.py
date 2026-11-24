#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 Hermes 的**上游 LLM 通道**（不只探端口）✓（2026-11-24 用户要求）。

【为什么需要】
  `restart_hermes.py` 只探 `/v1/models`，得到 `HTTP 401`（鉴权门）⇒ 只能说「服务活着」✗
  而 `evolve_review.py` 实际失败在 **`/v1/chat/completions` 超时**（2 次 × 90s）✗
  ⇒ 401 ≠ 能推理。**必须真发一次 completion** 才能确认上游通 ✓

【做什么】
  ① 读 key（env `API_SERVER_KEY` → `~/.hermes/.env`）
  ② 发一个**极小 prompt**（`say ok`，max_tokens=8），分档超时 10 / 30 / 90 秒
  ③ 报：每档耗时、HTTP 码、返回内容前 80 字
  ⇒ 若 10s 通 ⇒ 上游正常（`evolve_review` 的失败可能是 prompt 太大）
  ⇒ 若 90s 也不通 ⇒ 上游 LLM 不可用（Hermes 转发层卡住）

用法（Mac，经队列）：
    python scripts/hermes_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8642/v1/chat/completions"
MODEL = os.environ.get("HERMES_MODEL", "hermes-agent")


def _key():
    """照 `evolve_review.py` 的顺序取 key（env → `~/.hermes/.env`）✓。"""
    k = os.environ.get("API_SERVER_KEY")
    if k:
        return k, "env"
    p = os.path.expanduser("~/.hermes/.env")
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k2, v2 = ln.split("=", 1)
                if k2.strip() in ("API_SERVER_KEY", "HERMES_KEY"):
                    return v2.strip().strip("'\""), p
    except OSError:
        pass
    return None, None


def _call(key, timeout):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": "say ok"}],
        "max_tokens": 8,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer %s" % key})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        dt = time.time() - t0
        try:
            txt = json.loads(raw)["choices"][0]["message"]["content"]
        except Exception:                       # noqa: BLE001
            txt = raw[:80]
        return {"timeout": timeout, "ok": True, "secs": round(dt, 1),
                "reply": str(txt).strip()[:80]}
    except urllib.error.HTTPError as e:
        return {"timeout": timeout, "ok": False, "secs": round(time.time() - t0, 1),
                "http": e.code, "err": (e.read() or b"").decode("utf-8", "replace")[:120]}
    except Exception as e:                      # noqa: BLE001
        return {"timeout": timeout, "ok": False, "secs": round(time.time() - t0, 1),
                "err": "%s: %s" % (type(e).__name__, str(e)[:100])}


def main():
    out = {"url": URL, "model": MODEL}
    key, src = _key()
    out["key_source"] = src or "未找到（将不带 Authorization）"
    if not key:
        out["note"] = "没拿到 key ⇒ 大概率 401；请确认 ~/.hermes/.env 有 API_SERVER_KEY"

    results = []
    for t in (10, 30, 90):
        r = _call(key or "", t)
        results.append(r)
        if r.get("ok"):
            break          # 通了就不必再试更长超时
    out["attempts"] = results
    out["verdict"] = ("✅ 上游可用（%ss 内返回）" % results[-1]["secs"]
                      if results[-1].get("ok")
                      else "❌ 上游不可用（90s 内未返回）")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if results[-1].get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
