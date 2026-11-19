# -*- coding: utf-8 -*-
"""诊断 / 外部依赖探活 action ✓ —— 从 `run_task_queue.py` 拆出的第三个动作包。

【边界】
  · 只依赖 `queue_core`（`ROOT` / `run` / `BSK_BIN`）+ 标准库 ✓
  · **不碰队列状态** ✗ —— `QUEUE` / `run_once` / flock 在调度器里
  · 私有 helper（`_mask` / `_walk_shape` / `_resolve_llm_key` /
    `_openclaw_key`）与 `AGENT_CANDIDATES` 只被本包用 ⇒ 一起搬 ✓
"""
import json
import os
import re
import subprocess
import sys
import time

from queue_core import BSK_BIN, ROOT, run as _run


def _act_probe_url(params):
    """**用 bsk 探测任意 URL** ✓（2026-11-05 用户要求分析 `cmegroup.cn`）。

    🔴 为什么需要 ✗：
       `cmegroup.cn/fed-watch/` 在 **Windows 完全不可达** ✗：
         DNS 解析 OK（`119.23.206.245` ✗ 阿里云 ✗）
         但 `ping` 100% 丢包 ✗ 80/443 全超时 ✗ `web_fetch` 也超时 ✗
       ⇒ 只能让 **Mac** 去试（网络环境不同 ✗）

    【测什么】
      ① `bsk navigate` 能否打开 ✓
      ② `get-html` 长度 + 有无 `<table>` + 有无百分比 ✓
      ③ `observe` 语义视图前 500 字 ✓
      ④ `network` 里的业务 API（排除字体/脚本/样式 ✗）

    参数：`url`（必填 ✗）、`wait_ms`（默认 15000 ✗）
    """
    url = str(params.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "必须给 `url` ✗"}
    wait_ms = int(params.get("wait_ms") or 15000)

    def _bsk(args, timeout=120):
        """跑一条 `bsk` 命令 ✓（本文件的本地 helper ✗）。"""
        try:
            r = _run([BSK_BIN] + list(args), timeout)
            return r.returncode, (r.stdout or ""), (r.stderr or "")
        except FileNotFoundError:
            return -1, "", "**找不到 bsk** ✗（BSK_BIN=%s ✗）" % BSK_BIN
        except subprocess.TimeoutExpired:
            return -2, "", "bsk 超时（%ds ✗）" % timeout

    rc, o, e = _bsk(["session", "start"], timeout=60)
    sid = (o or "").strip().splitlines()[-1].strip() if o else ""
    if rc != 0 or not sid:
        return {"ok": False, "error": "session start 失败 ✗",
                "stderr": e[-300:]}
    out = {"url": url, "steps": {}}
    try:
        rc, o, e = _bsk(["navigate", url, "--session", sid,
                         "--timeout", "90s"], timeout=180)
        out["steps"]["navigate"] = {"rc": rc, "out": o[-250:], "err": e[-250:]}
        if rc != 0:
            return out
        _bsk(["wait-ms", str(wait_ms)], timeout=90)

        rc, html, e = _bsk(["get-html", "--session", sid], timeout=120)
        pcts = re.findall(r"\d{1,3}\.\d\s*%", html or "")
        out["steps"]["html"] = {
            "rc": rc, "len": len(html or ""),
            "has_table_tag": "<table" in (html or "").lower(),
            "pct_count": len(pcts), "pct_samples": pcts[:15],
            "has_iframe": "<iframe" in (html or "").lower(),
        }

        rc, o, e = _bsk(["observe", "--session", sid], timeout=120)
        out["steps"]["observe"] = {
            "rc": rc, "lines": len((o or "").splitlines()),
            "data_hits": sum(o.count(k) for k in ("%", "ZQ", "利率", "概率")),
            "head": (o or "")[:600],
        }

        rc, o, e = _bsk(["network", "--session", sid, "--json",
                         "--limit", "200"], timeout=120)
        urls = re.findall(r"https?://[^\s\"'<>\\]+", o or "")
        api = [u for u in urls if any(k in u.lower() for k in
                                      ("cme", "fed", "api/", "json", "watch"))]
        out["steps"]["network"] = {
            "rc": rc, "total_urls": len(urls),
            "api_urls": sorted(set(api))[:20],
        }
    finally:
        _bsk(["session", "stop", sid], timeout=60)

    h = out["steps"].get("html") or {}
    out["ok"] = True
    out["verdict"] = (
        "✓ **有数据特征**（%d 个百分比 ✗ 有 table=%s ✗）⇒ 值得深挖 ✓"
        % (h.get("pct_count", 0), h.get("has_table_tag"))
        if h.get("pct_count", 0) > 0 else
        "✗ **页面打开了但零个百分比** ✗（HTML %d 字节 ✗）"
        % h.get("len", 0))
    return out


def _act_key_diag(params):
    """找本机 API key ✓ —— **只回前缀与长度，绝不回明文** ✗。

    动机（2026-10-29）：NIM 免费通道走不通（唯一可用模型卡死、其余 404），
    要切 DeepSeek 官方，但得先确认 key 在哪、是什么结构 ——
    `~/.dsh/.credentials.yaml` 里既有 `nvapi-`（NVIDIA）也可能有 `sk-`（DeepSeek）✗。
    """
    import re

    root = os.path.expanduser(str(params.get("dir") or "~/.dsh"))
    if not os.path.isdir(root):
        return {"ok": False, "reason": "目录不存在：%s" % root}
    pats = {"nvapi": re.compile(r"nvapi-[A-Za-z0-9_\-]{8,}"),
            "sk": re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
            "sk-or": re.compile(r"sk-or-[A-Za-z0-9_\-]{16,}")}
    files, hits, seen = [], [], set()
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for f in names:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            files.append("%s（%d B）" % (rel, sz))
            if sz > 512 * 1024:                 # 大文件（模型/日志）不扫 ✓
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read()
            except OSError:
                continue
            for kind, rx in pats.items():
                for m in rx.finditer(txt):
                    v = m.group(0)
                    sig = (rel, kind, v[:10], len(v))
                    if sig in seen:
                        continue
                    seen.add(sig)
                    hits.append({"file": rel, "kind": kind,
                                 "prefix": v[:10] + "…", "len": len(v)})
    return {"ok": True, "result": {"dir": root,
                                   "files": files[:40],
                                   "hits": hits[:40]}}


def _act_net_probe(params):
    """探「本地代理端口」+「经代理取一次」✓ —— 只读、秒级。

    动机（2026-10-29）：简报两个 LLM 阶段都 `timed out`（不是 connection refused ✗）
    ⇒ 怀疑本地代理（Clash 127.0.0.1:7890）能连上但上游卡住 ✗。
    队列跑在 launchd 里，环境与登录 shell 不同 ✗ ⇒ 只能在 Mac 本地实测 ✓。
    """
    import socket
    import urllib.error
    import urllib.parse
    import urllib.request

    proxy = str(params.get("proxy") or "http://127.0.0.1:7890")
    url = str(params.get("url") or "https://integrate.api.nvidia.com/v1/models")
    out = {"proxy": proxy, "url": url}

    # ① 代理端口能不能连（3 秒）
    u = urllib.parse.urlsplit(proxy)
    t0 = time.time()
    try:
        s = socket.create_connection((u.hostname, u.port or 80), timeout=3)
        s.close()
        out["proxy_port"] = {"ok": True,
                             "ms": int((time.time() - t0) * 1000)}
    except OSError as exc:
        out["proxy_port"] = {"ok": False, "reason": str(exc)}

    # ② 经代理真取一次 ✓
    # `method`/`body`/`auth`/`secs` 可调 —— 2026-10-29 实测 GET 521ms 通、
    # POST chat 60 秒无响应 ✗ ⇒ 必须能**分别**验 GET 与 POST ✗
    method = str(params.get("method") or "GET").upper()
    body = params.get("body")
    secs = int(params.get("secs") or 10)
    headers = {}
    if body is not None:
        body = str(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if str(params.get("auth") or "") in ("1", "true", "yes"):
        try:
            if os.path.join(ROOT, "scripts") not in sys.path:
                sys.path.insert(0, os.path.join(ROOT, "scripts"))
            import invest_research as ir
            # 按 URL 选 key（本地 ⇒ Hermes 的 key）✓ 2026-11-09 统一走 Hermes
            headers["Authorization"] = "Bearer " + (ir._read_llm_key() or "")
        except Exception as exc:                   # noqa: BLE001
            out["auth"] = "读 key 失败：%s" % exc

    t0 = time.time()
    status = None
    try:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method=method)
        with op.open(req, timeout=secs) as r:
            status = r.status
            out["via_proxy"] = {"ok": True, "status": status, "method": method,
                                "ms": int((time.time() - t0) * 1000)}
            # `body_out=1` ⇒ 解析出**模型 id 列表** ✓（不回传原始正文 ✗）
            # 2026-10-29 踩坑：原始正文 3000 字，而 `_write_result` 只留尾部
            # `output[-2000:]` ✗ ⇒ 开头的 `deepseek-ai/*` 正好被截掉 ✗
            # ⇒ 只回「数量 + 按关键词筛过的 id」，几十个字就够 ✓
            if str(params.get("body_out") or "") in ("1", "true", "yes"):
                try:
                    import re
                    n = max(1000, min(int(params.get("body_len") or 20000), 60000))
                    txt = r.read(n).decode("utf-8", "replace")
                    ids = re.findall(r'"id"\s*:\s*"([^"]+)"', txt)
                    kw = str(params.get("models_like") or "deepseek,qwen,llama-3.3")
                    keys = [k.strip().lower() for k in kw.split(",") if k.strip()]
                    out["via_proxy"]["model_count"] = len(ids)
                    out["via_proxy"]["models"] = [
                        i for i in ids
                        if any(k in i.lower() for k in keys)][:40]
                except Exception as exc:           # noqa: BLE001
                    out["via_proxy"]["models"] = "解析失败：%s" % exc
    except urllib.error.HTTPError as exc:
        # 401/404 这类**也是有效情报** ✓ —— 说明链路通、只是鉴权/路径不对 ✓
        out["via_proxy"] = {"ok": False, "status": exc.code, "method": method,
                            "ms": int((time.time() - t0) * 1000),
                            "reason": "HTTP %s" % exc.code}
    except Exception as exc:                       # noqa: BLE001
        out["via_proxy"] = {"ok": False, "status": status, "method": method,
                            "ms": int((time.time() - t0) * 1000),
                            "reason": "%s: %s" % (type(exc).__name__, exc)}

    # ③ `chat=1` ⇒ 真打一次 chat/completions（max_tokens=8）✓
    # 2026-10-29 实测：GET 模型列表 641ms 通，但简报的归因阶段仍 240s 超时 ✗
    # ⇒ 必须区分「网络不通」和「**生成太慢**」✗，只有真打一次才知道 ✓
    if str(params.get("chat") or "") in ("1", "true", "yes"):
        t0 = time.time()
        try:
            if os.path.join(ROOT, "scripts") not in sys.path:
                sys.path.insert(0, os.path.join(ROOT, "scripts"))
            import invest_research as ir
            # `model` 可覆盖 ⇒ 换模型前先单测候选 ✓（2026-10-29）
            reply = ir._chat(ir.NIM_URL, ir._read_llm_key(),
                             str(params.get("model") or ir.NIM_MODEL),
                             "你是连通性探针。", "只回复 OK", max_tokens=8,
                             proxy=ir.PROXY, timeout=60, retries=1)
            out["chat"] = {"ok": True, "ms": int((time.time() - t0) * 1000),
                           "reply": str(reply)[:40]}
        except Exception as exc:                   # noqa: BLE001
            out["chat"] = {"ok": False,
                           "ms": int((time.time() - t0) * 1000),
                           "reason": "%s: %s" % (type(exc).__name__, exc)}

    ok = out["proxy_port"].get("ok") and out["via_proxy"].get("ok")
    if "chat" in out:
        ok = ok and out["chat"].get("ok")
    return {"ok": ok, "result": out}


def _act_run_task_monitor(params):
    """手动跑一次 `scripts/task_monitor.py` ✓（2026-11-09 用户要求）。

    🔴 为什么需要：改了新鲜度白名单后要等下一次定时才生效 ✗
       ⇒ 手动触发一次，直接看判定结果（默认**不推飞书** ✓）

    参数：`push=1` 才带 `--push-alert`
    退出码语义：0 = 全绿；1 = **有异常项**（脚本跑成功了 ✗ 不算任务失败 ✓）
    """
    args = [sys.executable, os.path.join(ROOT, "scripts", "task_monitor.py")]
    if str(params.get("push") or "").lower() in ("1", "true", "yes"):
        args.append("--push-alert")
    try:
        r = _run(args, 300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "task_monitor 超过 300 秒"}
    return {"ok": r.returncode in (0, 1),          # 1 = 有异常项，不是跑挂
            "rc": r.returncode,
            "stdout": (r.stdout or "")[-3000:],
            "stderr": (r.stderr or "")[-800:]}


def _resolve_llm_key():
    """逐个来源找 LLM key ⇒ `(key, 明细)` ✓（**不再静默吞异常** ✗）。

    2026-11-09 实测：第一次探针 `key_len=0` ✗ 但看不出是「文件不存在」还是
    「文件里没有 sk- key」还是「yaml 没装」✗ ⇒ 现在每个来源都回报状态 ✓
    """
    detail = {}
    key = os.environ.get("FG_LLM_KEY", "")
    detail["env_FG_LLM_KEY"] = bool(key)

    if os.path.join(ROOT, "scripts") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
    for name, fn in (("invest_research._read_nim_key", "_read_nim_key"),
                     ("invest_research._read_hermes_key", "_read_hermes_key")):
        try:
            mod = __import__("invest_research", fromlist=[fn])
            got = getattr(mod, fn)() or ""
            detail[name] = {"ok": bool(got), "len": len(got)}
            if got and not key:
                key = got
        except Exception as exc:            # noqa: BLE001
            detail[name] = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:120])}

    home = os.path.expanduser("~")
    for rel in (".dsh/.credentials.yaml", ".hermes/config.yaml", ".hermes/.env"):
        p = os.path.join(home, rel)
        detail[rel] = {"exists": os.path.exists(p)}
    return key, detail
#: 三个 agent 的候选端点 ✓（2026-11-09 `agent_probe` 实测端口）
#: 用户确认：三个都配的是 **deepseek 云端 deepseek-flash** ⇒ 模型名统一 ✓


AGENT_CANDIDATES = (
    ("hermes", 8642),
    ("dsh", 8326),
    ("openclaw", 18789),
)


def _openclaw_key():
    """从 `~/.openclaw/openclaw.json` 里捞 `sk-` 开头的 key ✓（不打印）。"""
    import glob as _g
    p = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")
    if not os.path.exists(p):
        return ""
    try:
        obj = json.load(open(p, encoding="utf-8", errors="replace"))
    except Exception:                     # noqa: BLE001
        return ""
    found = []

    def walk(d):
        if isinstance(d, dict):
            for v in d.values():
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)
        elif isinstance(d, str) and d.startswith("sk-") and len(d) > 20:
            found.append(d)

    walk(obj)
    return found[0] if found else ""


def _mask(v):
    """脱敏：只回前 4 + 后 4 + 长度 ✓（**绝不回明文** ✗）。"""
    s = str(v)
    if len(s) <= 10:
        return "*" * len(s) + "(%d)" % len(s)
    return "%s…%s(%d)" % (s[:4], s[-4:], len(s))


def _walk_shape(obj, prefix="", out=None, depth=0):
    """把嵌套结构压成 `a.b.c = 脱敏值` 列表 ✓（只收 key/token/url/model 类）。"""
    if out is None:
        out = []
    if depth > 6:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_shape(v, "%s.%s" % (prefix, k) if prefix else str(k), out,
                        depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            _walk_shape(v, "%s[%d]" % (prefix, i), out, depth + 1)
    else:
        low = prefix.lower()
        hit = any(t in low for t in ("key", "token", "secret", "url", "base",
                                     "port", "model", "host", "endpoint",
                                     "provider", "agent"))
        looks_token = isinstance(obj, str) and len(obj) >= 20 and " " not in obj
        if hit or looks_token:
            out.append("%s = %s" % (prefix, _mask(obj)))
    return out


def _act_key_shape_probe(params):
    """**只列键名与脱敏值** ✓ —— 找出 dsh 的 key 到底叫什么（2026-11-09 用户选 A）。

    🔴 背景：`agent_chat_probe` 显示 `dsh` 的 `key_len=0` ✗
       —— 我从 `~/.dsh/.credentials.yaml` 里只找 `sk-` 开头 ✗ 可能前缀不对 ✗
       ⇒ 把**结构与键名**摆出来，绝不回明文 ✓
    """
    import glob as _g

    home = os.path.expanduser("~")
    out = {"files": {}, "dirs": {}}

    # ① 目录清单（只看文件名）
    for rel in (".dsh", ".openclaw", ".hermes"):
        p = os.path.join(home, rel)
        try:
            out["dirs"][rel] = sorted(os.path.basename(x) for x in _g.glob(p + "/*"))
        except Exception as exc:          # noqa: BLE001
            out["dirs"][rel] = {"error": str(exc)[:80]}

    # ② 配置文件结构（脱敏）
    targets = [".dsh/.credentials.yaml", ".dsh/credentials.yaml",
               ".dsh/config.yaml", ".hermes/config.yaml",
               ".openclaw/openclaw.json"]
    for rel in targets:
        p = os.path.join(home, rel)
        if not os.path.exists(p):
            out["files"][rel] = {"exists": False}
            continue
        try:
            raw = open(p, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            out["files"][rel] = {"error": str(exc)[:80]}
            continue
        obj = None
        if rel.endswith(".json"):
            try:
                obj = json.loads(raw)
            except ValueError:
                obj = None
        else:
            try:
                import yaml
                obj = yaml.safe_load(raw)
            except Exception:             # noqa: BLE001
                obj = None
        if obj is None:
            # yaml 不可用时退回：只回**键名**（`k:` 行），不回值 ✓
            names = [ln.split(":")[0].strip() for ln in raw.splitlines()
                     if ":" in ln and not ln.strip().startswith("#")]
            out["files"][rel] = {"exists": True, "parse": "text",
                                 "keys": names[:30]}
        else:
            out["files"][rel] = {"exists": True, "parse": "ok",
                                 "shape": _walk_shape(obj)[:40]}
    out["ok"] = True
    return out


def _act_agent_chat_probe(params):
    """逐个 agent 发一次最小 chat ✓ —— 定死「哪条通道真能用」。

    🔴 用户确认三个 agent 都配 `deepseek-flash` ✗
       ⇒ 模型名统一，只需确认**端点 + key** 是否可用 ✓
       2026-11-09 `agent_probe` 已知端口：hermes 8642 / dsh 8326 / openclaw 18789
    """
    import urllib.error as _ue
    import urllib.request as _u

    model = str(params.get("model") or "deepseek-flash")
    if os.path.join(ROOT, "scripts") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        import invest_research as ir
        keys = {"hermes": ir._read_hermes_key() or "",
                "dsh": ir._read_nim_key() or "",
                "openclaw": _openclaw_key()}
    except Exception as exc:              # noqa: BLE001
        return {"ok": False, "reason": "读 key 失败：%s" % str(exc)[:200]}

    out = {"model": model, "results": {}}
    for name, port in AGENT_CANDIDATES:
        url = "http://127.0.0.1:%d/v1/chat/completions" % port
        key = keys.get(name) or ""
        payload = json.dumps({"model": model,
                              "messages": [{"role": "user", "content": "ping"}],
                              "max_tokens": 8}).encode()
        req = _u.Request(url, data=payload, method="POST",
                         headers={"Authorization": "Bearer %s" % key,
                                  "Content-Type": "application/json"})
        try:
            with _u.urlopen(req, timeout=60) as resp:
                body = resp.read(200).decode("utf-8", "replace")
                out["results"][name] = {"url": url, "key_len": len(key),
                                        "status": resp.status, "body": body}
        except _ue.HTTPError as exc:
            out["results"][name] = {
                "url": url, "key_len": len(key), "status": exc.code,
                "body": exc.read(200).decode("utf-8", "replace")}
        except Exception as exc:          # noqa: BLE001
            out["results"][name] = {"url": url, "key_len": len(key),
                                    "error": "%s: %s" % (type(exc).__name__,
                                                         str(exc)[:120])}
    out["ok"] = True
    return out


def _act_agent_probe(params):
    """发现本机三个 agent（openclaw / deepseek-harness / hermes）的地址与端口 ✓。

    🔴 2026-11-09 用户要求「简报不同模块用不同 agent」✗，但仓库里**只有 hermes
       的 8642** ✗ —— openclaw / dsh 的端口代码里查不到 ✗
       ⇒ 一次探完，避免猜端口（bsk 那 6 轮的教训）✓

    三段：
      ① `lsof` 列本机 LISTEN 端口
      ② 逐个 `GET /v1/models`（2 秒超时）—— 谁回 OpenAI 风格就说明是 agent
      ③ 读 `~/.openclaw/openclaw.json`、`~/.dsh/*.yaml` 里的 url/port 键
    ⚠️ **只回端口与状态**，绝不回 key/secret ✗
    """
    import socket
    import urllib.error as _ue
    import urllib.request as _u

    out = {"listening": [], "probes": {}, "configs": {}}

    # ① 监听端口
    # 🔴 2026-11-09 实测：launchd 的 PATH 里**没有** /usr/sbin ✗ ⇒ `lsof` 找不到 ✗
    #    （回执 `FileNotFoundError: 'lsof'`）⇒ 用绝对路径 + netstat 兜底 ✓
    ports, errs = set(), []
    for cmd in (["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
                ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"]):
        try:
            r = _run(cmd, 20)
            for ln in (r.stdout or "").splitlines()[1:]:
                parts = ln.split()
                if len(parts) >= 9:
                    tail = parts[8].rsplit(":", 1)[-1]
                    if tail.isdigit():
                        ports.add(int(tail))
            break
        except Exception as exc:          # noqa: BLE001
            errs.append("%s: %s" % (cmd[0], type(exc).__name__))
    if not ports:                          # 兜底：netstat
        try:
            r = _run(["netstat", "-an", "-p", "tcp"], 20)
            for ln in (r.stdout or "").splitlines():
                if "LISTEN" not in ln:
                    continue
                # macOS 是 `127.0.0.1.8642`，Windows 是 `0.0.0.0:135` ⇒ 两种都认 ✓
                for tok in ln.split()[:5]:
                    m = re.search(r"[:.](\d{2,5})$", tok)
                    if m:
                        ports.add(int(m.group(1)))
                        break
        except Exception as exc:          # noqa: BLE001
            errs.append("netstat: %s" % type(exc).__name__)
    out["listening"] = sorted(ports)
    if errs:
        out["listening_error"] = "; ".join(errs)

    # ② 逐个探 /v1/models（只探本机监听端口，2 秒超时）
    for port in out["listening"]:
        if not (1024 <= port <= 65535):
            continue
        url = "http://127.0.0.1:%d/v1/models" % port
        try:
            with _u.urlopen(url, timeout=2) as resp:
                body = resp.read(300).decode("utf-8", "replace")
                out["probes"][str(port)] = {"status": resp.status, "body": body}
        except _ue.HTTPError as exc:
            out["probes"][str(port)] = {"status": exc.code,
                                        "body": exc.read(200).decode("utf-8",
                                                                     "replace")}
        except Exception as exc:          # noqa: BLE001 —— 不是 HTTP 服务，正常
            out["probes"][str(port)] = {"error": type(exc).__name__}

    # ③ 配置文件里的 url / port（**不取 secret** ✗）
    home = os.path.expanduser("~")
    for rel in (".openclaw/openclaw.json", ".dsh/config.yaml",
                ".dsh/config.yml", ".hermes/config.yaml"):
        p = os.path.join(home, rel)
        if not os.path.exists(p):
            out["configs"][rel] = {"exists": False}
            continue
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            out["configs"][rel] = {"error": str(exc)[:100]}
            continue
        hits = re.findall(r'"?[\w.-]*(?:url|base|endpoint|port|host)'
                          r'"?\s*[:=]\s*"?([^"\s,}]{1,80})', txt, re.I)
        out["configs"][rel] = {"exists": True, "hits": sorted(set(hits))[:12]}
    return out


def _act_deepseek_key_hunt(params):
    """在 Mac 家目录里**找 `sk-` 开头的 key** ✓（2026-11-09 用户选方案 B）。

    🔴 背景：方案 B = 保留 `api.deepseek.com` 直连，但需要有效 key ✗
       `deepseek_probe` 显示 `~/.dsh/.credentials.yaml` 里**没有** `sk-` ✗
       而用户说三个 agent 都配了 DeepSeek 云端 ⇒ key **一定在某个文件里** ✓
       ⇒ 扫一遍候选位置，只回**文件 + 脱敏值 + 长度**，绝不回明文 ✗

    ⚠️ 不扫业务数据目录（`Data/`、`docs/`），只看配置类路径 ✓
    """
    import glob as _g
    import re as _re

    home = os.path.expanduser("~")
    patterns = [
        ".hermes/*.yaml", ".hermes/*.yml", ".hermes/.env", ".hermes/*.json",
        ".hermes/profiles/*", ".dsh/*.yaml", ".dsh/*.yml", ".dsh/*.json",
        ".dsh/profiles/*", ".dsh/openai-gateway/*",
        ".openclaw/*.json", ".openclaw/credentials/*", ".openclaw/agents/*",
        ".config/deepseek/*", ".deepseek/*", ".env", ".zshrc", ".bash_profile",
    ]
    # `sk-` 后至少 16 位字母数字（DeepSeek 官方格式）
    pat = _re.compile(r"sk-[A-Za-z0-9_\-]{16,}")

    hits, scanned = [], []
    for pattern in patterns:
        for path in _g.glob(os.path.join(home, pattern)):
            if not os.path.isfile(path):
                continue
            scanned.append(os.path.relpath(path, home))
            try:
                txt = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in pat.finditer(txt):
                val = m.group(0)
                hits.append({"file": os.path.relpath(path, home),
                             "mask": _mask(val), "len": len(val)})

    # 去重（同一条 key 可能出现在多处）
    seen, uniq = set(), []
    for h in hits:
        if h["mask"] in seen:
            continue
        seen.add(h["mask"])
        uniq.append(h)

    # 环境变量里有没有（只看名字，不回值）
    env_names = [k for k in os.environ
                 if "DEEPSEEK" in k.upper() or k.upper().endswith("_API_KEY")]
    return {"ok": True, "files_scanned": len(scanned), "hits": uniq[:30],
            "hit_count": len(uniq), "env_names": env_names[:20],
            "note": "只回脱敏值；若 hit_count=0 说明 key 不在这些路径"}


def _act_deepseek_probe(params):
    """探 **DeepSeek 云端**：哪个 `model` id 被接受 ✓（2026-11-09 用户要求）。

    🔴 为什么要探：`invest_research` 默认已切到 `api.deepseek.com`，但模型名
       用的是内部约定的 `deepseek/deepseek-flash` ✗ —— 官方只保证
       `deepseek-chat` / `deepseek-reasoner` ✓ ⇒ 必须实测，不能猜 ✗

    参数：`url`（默认官方端点）、`models`（逗号分隔，默认三个候选）
    每个候选只发 `max_tokens=8` 的 ping ⇒ 便宜且快 ✓
    """
    import urllib.error as _ue
    import urllib.request as _u

    url = str(params.get("url") or "https://api.deepseek.com/v1/chat/completions")
    models = [m.strip() for m in str(
        params.get("models")
        or "deepseek/deepseek-flash,deepseek-chat,deepseek-reasoner"
    ).split(",") if m.strip()]

    key, key_detail = _resolve_llm_key()

    out = {"url": url, "key_len": len(key), "key_sources": key_detail,
           "results": {}}
    for model in models:
        payload = json.dumps({"model": model,
                              "messages": [{"role": "user", "content": "ping"}],
                              "max_tokens": 8}).encode()
        req = _u.Request(url, data=payload, method="POST",
                         headers={"Authorization": "Bearer %s" % key,
                                  "Content-Type": "application/json"})
        try:
            with _u.urlopen(req, timeout=60) as resp:
                out["results"][model] = {
                    "ok": True, "status": resp.status,
                    "body": resp.read(300).decode("utf-8", "replace")}
        except _ue.HTTPError as exc:
            out["results"][model] = {
                "ok": False, "status": exc.code,
                "body": exc.read(300).decode("utf-8", "replace")}
        except Exception as exc:            # noqa: BLE001
            out["results"][model] = {"ok": False, "error": str(exc)[:200]}
    out["ok"] = True
    return out


def _act_hermes_probe(params):
    """探本机 **Hermes 网关**（127.0.0.1:8642）✓（2026-11-09 用户要求排查）。

    回答三件事，区分「网关死」和「模型慢」：
      ① TCP 端口通不通
      ② `/v1/models` 是否 200（网关进程活着）
      ③ 最小 chat 请求（max_tokens=8）延迟
    """
    import socket
    import time as _t
    import urllib.error as _ue
    import urllib.request as _u

    base = str(params.get("url") or "http://127.0.0.1:8642").rstrip("/")
    # ⚠️ key 必须与 `evolve_review` 用的**同一把** ✗ ——
    #    2026-11-09 首次探针用了空 key ⇒ 401「Invalid gateway API key」✗ 假阴性 ✗
    key = os.environ.get("API_SERVER_KEY", "")
    if not key:
        try:
            if os.path.join(ROOT, "scripts") not in sys.path:
                sys.path.insert(0, os.path.join(ROOT, "scripts"))
            from evolve_review import HERMES_KEY as _hk     # noqa: E402
            key = _hk or ""
        except Exception:                    # noqa: BLE001
            key = ""
    out = {"url": base, "key_len": len(key)}

    t0 = _t.time()
    sk = socket.socket()
    sk.settimeout(3)
    try:
        sk.connect(("127.0.0.1", 8642))
        out["tcp"] = {"ok": True, "ms": round((_t.time() - t0) * 1000)}
    except OSError as exc:
        out["tcp"] = {"ok": False, "error": str(exc)[:120]}
    finally:
        sk.close()

    def _call(path, payload=None, timeout=120):
        t = _t.time()
        try:
            req = _u.Request(base + path, data=payload, method="POST" if payload else "GET",
                             headers={"Authorization": "Bearer %s" % key,
                                      "Content-Type": "application/json"})
            with _u.urlopen(req, timeout=timeout) as r:
                return {"ok": True, "status": r.status,
                        "ms": round((_t.time() - t) * 1000),
                        "body": r.read(400).decode("utf-8", "replace")}
        except _ue.HTTPError as exc:
            return {"ok": False, "status": exc.code,
                    "ms": round((_t.time() - t) * 1000),
                    "body": exc.read(400).decode("utf-8", "replace")}
        except Exception as exc:            # noqa: BLE001
            return {"ok": False, "ms": round((_t.time() - t) * 1000),
                    "error": str(exc)[:200]}

    out["models"] = _call("/v1/models", timeout=10)
    # 只生成 8 token ⇒ 若这里就慢/超时，说明是模型侧而不是网关
    payload = json.dumps({"model": "hermes-agent",
                          "messages": [{"role": "user", "content": "ping"}],
                          "max_tokens": 8}).encode()
    out["chat"] = _call("/v1/chat/completions", payload, timeout=120)
    # ⚠️ `ok` 表示**探针跑完了**（不是「网关可用」✗）—— 缺它队列会把任务判 failed ✗
    out["ok"] = True
    return out


def _act_bsk_probe(params):
    """跑 `scripts/bsk_probe.py` ⇒ **一次**拿到 bsk 控制上下文的全部事实 ✓。

    动机：`fetch_shoutu_history` 连挂 5 轮，每轮只带回一条错误 ✗
    ⇒ 用户要求「避免在 Mac 上反复重试」✗ ⇒ 改成一次跑完全部候选调用 ✓
    """
    try:
        r = _run([sys.executable, os.path.join(ROOT, "scripts", "bsk_probe.py")], 600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "bsk_probe 超过 600 秒"}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-4000:],
            "stderr": (r.stderr or "")[-800:]}


def _act_render_probe(params):
    """渲染一次仪表盘并回传**完整 traceback** ✓（2026-11-06）。

    动机：服务端 500 只回 `type: message` ✗ ⇒
    「must be real number, not complex」查了整轮才定位到 `leverage._annualize` ✗
    ⇒ 队列直接跑一次，栈一起带回来 ✓
    """
    import traceback
    out = {"ok": True}
    try:
        from fg_system.dashboard.server import render_dashboard
        html = render_dashboard()
        out["html_len"] = len(html)
        out["loss_block_ok"] = "损耗归因不可用" not in html
    except Exception as exc:                     # noqa: BLE001
        out["ok"] = False
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        out["traceback"] = traceback.format_exc()[-4000:]
    return out


ACTIONS = {
    "deepseek_key_hunt": _act_deepseek_key_hunt,
    "deepseek_probe": _act_deepseek_probe,
    "hermes_probe": _act_hermes_probe,
    "bsk_probe": _act_bsk_probe,
    "render_probe": _act_render_probe,
    "probe_url": _act_probe_url,
    "net_probe": _act_net_probe,
    "agent_probe": _act_agent_probe,
    "agent_chat_probe": _act_agent_chat_probe,
    "key_shape_probe": _act_key_shape_probe,
    "key_diag": _act_key_diag,
    "run_task_monitor": _act_run_task_monitor,
}
