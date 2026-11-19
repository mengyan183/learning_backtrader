# -*- coding: utf-8 -*-
"""futu 相关 action ✓ —— 从 `run_task_queue.py` 拆出的第一个动作包（2026-11-19 第四轮）。

【边界】
  · 只依赖 `queue_core`（`ROOT` / `run`）+ 标准库 ✓
  · **不碰队列状态** ✗ —— `QUEUE` / `run_once` / flock 全在调度器里 ✓
  · 注册表由调度器合并（`{**FUTU_ACTIONS, ...}`）⇒ `ACTIONS` 仍是唯一入口 ✓

【为什么先拆这一包】
  这几个 futu action 共享 OpenD 路径/端口探测，几乎不依赖别的 action ✗
  ⇒ 是验证「包 → 注册表组装」模式的最小样本 ✓
"""
import json
import os
import subprocess
import sys
import time

from queue_core import ROOT, run as _run


def _call_with_timeout(fn, seconds=90):
    """在**守护线程**里跑 `fn`，超时返回 `(False, None)` ✓（2026-11-10）。

    🔴 为什么必须有：OpenD 进入**无限重连循环**时，`futu` 的 SDK 调用
       **永不返回** ✗ —— 实测把队列卡死 **100+ 分钟** ✗
       （`t-20261110-0904xx-test_futu_fed.running` 从 09:02 一直挂到 10:4x）
       ⇒ 队列是**单线程串行**，一个动作卡住 ⇒ 后面全部排队不动 ✗
       ⇒ 用守护线程 + `result(timeout)` ✓：超时就让那条线程自生自灭 ✓
         （daemon=True ⇒ 进程退出时自动清理 ✓ 不会阻止退出 ✓）

    ⚠️ 这不是「取消」✗ —— 卡住的线程仍在跑，只是**不再阻塞队列** ✓
    """
    import threading
    box = {}

    def _worker():
        try:
            box["v"] = fn()
        except Exception as exc:              # noqa: BLE001
            box["e"] = exc

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(seconds)
    if th.is_alive():
        return False, None
    if "e" in box:
        raise box["e"]
    return True, box.get("v")
def _act_futu_opend_update(params):
    """用 OpenD **内置 `update` 命令**升级 ✓（2026-11-10 用户提供官方用法）。

    官方用法（用户截图）：
      `./FutuOpenD -cfg_file <OpenD.xml 绝对路径> update`
      ⚠️ 更新会**重启 OpenD** ⇒ 必须先停掉，否则端口占用导致更新失败
      ⚠️ Mac 下系统随机路径会导致找不到配置 ⇒ 必须 `-cfg_file` 显式指定

    流程：
      ① 找 CLI 二进制（`FutuOpenD` / `OpenD`）+ `OpenD.xml`
      ② `pkill -f OpenD` + 等端口释放（最多 15s）
      ③ `FutuOpenD -cfg_file <xml> update`（超时 600s，它会下载）
      ④ 启动回 OpenD（GUI `open -a` 优先，否则直接跑二进制）
      ⑤ 等端口 + 回执带 update 的完整输出
    ⚠️ 找不到二进制时**不猜**，直接回报候选路径清单 ✓
    """
    import socket
    out = {"steps": {}}

    def _port_open(host="127.0.0.1", port=11111, t=2.0):
        try:
            s = socket.create_connection((host, port), t)
            s.close()
            return True
        except OSError:
            return False

    # ① 找二进制与配置
    cands = [
        os.path.expanduser("~/futu_OpenD/FutuOpenD"),
        os.path.expanduser("~/futu_OpenD/OpenD"),
        "/Applications/FutuOpenD.app/Contents/MacOS/FutuOpenD",
        "/Applications/FutuOpenD.app/Contents/MacOS/OpenD",
    ]
    bin_path = next((c for c in cands if os.path.isfile(c)), None)
    out["steps"]["binary"] = bin_path or "(未找到)"
    if not bin_path:
        out["ok"] = False
        out["error"] = ("找不到 OpenD 的**命令行二进制** ✗ "
                        "（GUI 版 .app 里也可能有 Contents/MacOS/）")
        out["candidates"] = cands
        out["hint"] = ("在 Mac 上跑 `ls /Applications/FutuOpenD.app/Contents/MacOS/` "
                       "和 `ls ~/futu_OpenD/` 把结果贴给我")
        return out

    # 找 OpenD.xml ✓
    # 🔴 2026-11-10 `futu_opend_info` 回执：GUI 版装在 `/Applications/FutuOpenD.app`，
    #    而 `~/futu_OpenD` **不可读**（不存在）✗ ⇒ 配置多半在 GUI 版自己的目录里 ✓
    #    ⇒ 除同目录外，再扫三处 GUI 版常见位置 ✓
    base = os.path.dirname(bin_path)
    xml = None
    cands_xml = [os.path.join(base, r) for r in
                 ("OpenD.xml", "../OpenD.xml", "../../OpenD.xml")]
    cands_xml += [
        os.path.expanduser("~/.com.futunn.FutuOpenD/OpenD.xml"),
        os.path.expanduser("~/Library/Application Support/FutuOpenD/OpenD.xml"),
        os.path.expanduser("~/futu_OpenD/OpenD.xml"),
        "/Applications/FutuOpenD.app/Contents/Resources/OpenD.xml",
    ]
    for p in cands_xml:
        p = os.path.normpath(p)
        if os.path.isfile(p):
            xml = p
            break
    out["steps"]["cfg_file"] = xml or "(未找到，将不带 -cfg_file 运行)"
    out["steps"]["cfg_searched"] = [os.path.normpath(p) for p in cands_xml]

    # ② 停 OpenD
    try:
        r = _run(["pkill", "-f", "OpenD"], 30)
        out["steps"]["kill"] = "pkill rc=%s" % r.returncode
    except Exception as exc:              # noqa: BLE001
        out["steps"]["kill"] = "pkill err %s" % str(exc)[:80]
    for _ in range(15):
        if not _port_open():
            break
        time.sleep(1)
    out["steps"]["port_freed"] = not _port_open()

    # ③ 跑 update
    cmd = [bin_path] + (["-cfg_file", xml] if xml else []) + ["update"]
    out["steps"]["cmd"] = " ".join(cmd)
    try:
        r = _run(cmd, 600, cwd=base)
        out["steps"]["update"] = {
            "rc": r.returncode,
            "stdout": (r.stdout or "").strip()[-1200:],
            "stderr": (r.stderr or "").strip()[-600:],
        }
    except subprocess.TimeoutExpired:
        out["steps"]["update"] = {"rc": -1, "stdout": "update 超过 600 秒"}
    except Exception as exc:              # noqa: BLE001
        out["steps"]["update"] = {"rc": -2,
                                  "stdout": "%s: %s" % (type(exc).__name__,
                                                        str(exc)[:200])}

    # ④ 启动回来
    started = []
    for c in (["open", "-a", "FutuOpenD"], [bin_path] + (["-cfg_file", xml] if xml else [])):
        try:
            if c[0] == "open":
                r = _run(c, 30)
                started.append({"cmd": " ".join(c), "rc": r.returncode})
                if r.returncode == 0:
                    break
            else:
                # 后台起，不等它退出
                subprocess.Popen(c, cwd=base, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                started.append({"cmd": " ".join(c), "rc": 0, "bg": True})
                break
        except Exception as exc:          # noqa: BLE001
            started.append({"cmd": " ".join(c), "err": str(exc)[:100]})
    out["steps"]["start"] = started

    ok = False
    for _ in range(15):
        time.sleep(1)
        if _port_open():
            ok = True
            break
    out["steps"]["port_after"] = ok
    out["ok"] = ok
    if not ok:
        out["hint"] = ("OpenD 没起来 ✗ ⇒ 看 `update` 的 stdout："
                       "若它已把旧版删掉但新版没下完，需要手动从官网重装")
    return out
def _act_realtime_diag(params):
    """排查 `com.xingguo.fg-realtime` 为什么没更新 BTC 价 ✓（2026-11-10 用户要求）。

    🔴 现象：简报里 BTC 现价停在 **11-09 22:07 的 83489.7**（18 小时前）✗
       而其他 5 个美股标的都正常更新 ⇒ 怀疑常驻服务挂了或 OKX 段没在跑 ✗

    查四件事：
      ① `launchctl list` 里 `fg-realtime` 的 PID / 最后退出码
      ② 日志尾巴（`/tmp/fg_realtime.log` 或 plist 里的 StandardOutPath）
      ③ `Data/realtime_state.json` 的 `updated` 与 `prices.BTC.ts`
      ④ plist 里的 ProgramArguments（看它到底启了什么）
    """
    out = {"steps": {}}

    # ① launchctl
    try:
        r = _run(["launchctl", "list"], 20)
        hits = [ln for ln in (r.stdout or "").splitlines()
                if "realtime" in ln.lower()]
        out["steps"]["launchctl"] = hits[:5] or ["(launchctl list 里没有 realtime 相关项)"]
    except Exception as exc:              # noqa: BLE001
        out["steps"]["launchctl"] = "ERR %s" % str(exc)[:120]

    # ② 日志
    logs = ["/tmp/fg_realtime.log", "/tmp/fg-realtime.log",
            os.path.join(ROOT, "logs", "realtime.log")]
    found = {}
    for p in logs:
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            age = int(time.time() - os.path.getmtime(p))
            found[p] = {"age_sec": age, "size": len(lines),
                        "tail": "".join(lines[-25:])[-1800:]}
        except OSError as exc:
            found[p] = {"error": str(exc)[:100]}
    out["steps"]["logs"] = found or "(三个候选日志都不存在)"

    # ③ realtime_state.json
    try:
        with open(os.path.join(ROOT, "Data", "realtime_state.json"),
                  encoding="utf-8") as fh:
            st = json.load(fh)
        pr = st.get("prices") or {}
        out["steps"]["state"] = {
            "updated": st.get("updated"),
            "btc": pr.get("BTC"),
            "symbols": sorted(pr.keys())[:15],
            "symbol_count": len(pr),
        }
    except Exception as exc:              # noqa: BLE001
        out["steps"]["state"] = "ERR %s" % str(exc)[:150]

    # ④ plist
    pl = os.path.join(ROOT, "scripts", "com.xingguo.fg-realtime.plist")
    try:
        out["steps"]["plist"] = open(pl, encoding="utf-8").read()[:2500]
    except OSError as exc:
        out["steps"]["plist"] = "ERR %s" % str(exc)[:100]

    out["ok"] = True
    return out
def _act_futu_opend_info(params):
    """**探测 FutuOpenD 版本/路径 + 抓官网下载链接** ✓（2026-11-10 用户要求升级 OpenD）。

    🔴 为什么需要：
       `futu-api` 在 PyPI 上只有 `10.12.7208`（最新）和 `10.11.7108`（旧）✗
       **没有 `10.11.7188`** ✗ —— 而 Mac 上的 OpenD 正是 `10.11.7188` ✗
       ⇒ 无法用「降级 SDK」对齐 ⇒ 只能**升级 OpenD 到 7208 同代** ✓

    三段（全部只读 ✓）：
      ① 找 OpenD app / 二进制，读版本（Info.plist 或可执行文件 --version）
      ② 列 `~/futu_OpenD` 与 `/Applications` 下的相关目录
      ③ 抓官网 OpenAPI 下载页，正则提取 `.dmg` / `.zip` 链接
    ⚠️ **不下载、不安装** ✗ —— 安装要替换 app，风险高，等用户确认 URL ✓
    """
    import re as _re
    import urllib.request
    out = {"candidates": [], "downloads": [], "notes": []}

    # ① 找 app
    cands = ["/Applications/FutuOpenD.app",
             os.path.expanduser("~/Applications/FutuOpenD.app"),
             os.path.expanduser("~/futu_OpenD/OpenD.app"),
             "/Applications/FutuOpenD.app"]
    seen = set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        if not os.path.exists(c):
            continue
        info = {"path": c}
        plist = os.path.join(c, "Contents", "Info.plist")
        if os.path.exists(plist):
            try:
                r = _run(["/usr/bin/plutil", "-p", plist], 20)
                txt = r.stdout or ""
                for k in ("CFBundleShortVersionString", "CFBundleVersion"):
                    m = _re.search(r'"%s"\s*=>\s*"([^"]+)"' % k, txt)
                    if m:
                        info[k] = m.group(1)
            except Exception:             # noqa: BLE001
                pass
        # 可执行文件
        exe = os.path.join(c, "Contents", "MacOS")
        try:
            info["macos_dir"] = sorted(os.listdir(exe))[:5]
        except OSError:
            pass
        out["candidates"].append(info)

    # ② 目录
    for d in (os.path.expanduser("~/futu_OpenD"), "/Applications"):
        try:
            names = [n for n in os.listdir(d) if "utu" in n or "OpenD" in n]
            out.setdefault("dirs", {})[d] = sorted(names)[:10]
        except OSError:
            out.setdefault("dirs", {})[d] = "(不可读)"

    # ③ 官网下载页
    for url in ("https://www.futunn.com/download/OpenAPI",
                "https://openapi.futunn.com/futu-api-doc/quick/opend-base.html"):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
            opener = urllib.request.build_opener()
            proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
            if proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            body = opener.open(req, timeout=25).read().decode("utf-8", "ignore")
            links = set(_re.findall(r"https?://[^\s\"'<>]+?\.(?:dmg|zip)", body))
            out["downloads"].extend(sorted(links)[:10])
            out.setdefault("pages", []).append({"url": url, "ok": True,
                                                "len": len(body)})
        except Exception as exc:          # noqa: BLE001
            out.setdefault("pages", []).append(
                {"url": url, "ok": False,
                 "err": "%s: %s" % (type(exc).__name__, str(exc)[:120])})

    out["notes"].append("PyPI 只有 10.12.7208 / 10.11.7108，**没有 10.11.7188**")
    out["ok"] = True
    return out
def _act_futu_upgrade_restart(params):
    """**升级 futu-api + 重启 OpenD** ✓（2026-11-10 用户要求）。

    🔴 背景：`test_futu_fed` 回执显示
       `futu_version = 10.11.7108` ✗ 而 OpenD 是 `10.11.7188` ✗
       ⇒ SDK 比服务端旧 ⇒ 握手失败 ⇒ `on_disconnect` 刷屏 ⇒ 无限重连 ✗

    步骤（每步都回报 rc/输出，失败不中断后续 ✓）：
      ① 记录当前 futu-api 版本
      ② `pip install -U futu-api`（超时 300s）
      ③ 记录新版本
      ④ `pkill -f OpenD` + 等端口释放（最多 15s）
      ⑤ 启动 OpenD（`open -a` 优先，其次已知路径）
      ⑥ 等 12s 再探端口
    ⚠️ 本动作**会杀掉 OpenD 进程** ✗ —— 属于用户明确要求的运维操作 ✓
    """
    import socket
    out = {"steps": {}}

    def _ver():
        try:
            r = _run([sys.executable, "-m", "pip", "show", "futu-api"], 60)
            for ln in (r.stdout or "").splitlines():
                if ln.lower().startswith("version:"):
                    return ln.split(":", 1)[1].strip()
        except Exception:                 # noqa: BLE001
            pass
        return "?"

    def _port_open(host="127.0.0.1", port=11111, t=2.0):
        try:
            s = socket.create_connection((host, port), t)
            s.close()
            return True
        except OSError:
            return False

    out["steps"]["version_before"] = _ver()

    # ② 升级（超时 300s；pip 有时会卡在编译 ⇒ 必须设上限 ✓）
    try:
        r = _run([sys.executable, "-m", "pip", "install", "-U", "futu-api"], 300)
        out["steps"]["pip"] = {"rc": r.returncode,
                               "tail": (r.stdout or r.stderr or "").strip()[-500:]}
    except subprocess.TimeoutExpired:
        out["steps"]["pip"] = {"rc": -1, "tail": "pip 超过 300 秒"}

    out["steps"]["version_after"] = _ver()

    # ④ 杀 OpenD
    killed = []
    try:
        r = _run(["pkill", "-f", "OpenD"], 30)
        killed.append("pkill rc=%s" % r.returncode)
    except Exception as exc:              # noqa: BLE001
        killed.append("pkill err %s" % str(exc)[:80])
    out["steps"]["kill"] = killed

    # 等端口释放（最多 15s）
    freed = False
    for _ in range(15):
        if not _port_open():
            freed = True
            break
        time.sleep(1)
    out["steps"]["port_freed"] = freed

    # ⑤ 启动（多路径兜底）
    started = []
    for cmd in (["open", "-a", "FutuOpenD"],
                ["open", os.path.expanduser("~/futu_OpenD/OpenD.app")],
                [os.path.expanduser("~/futu_OpenD/OpenD")]):
        try:
            r = _run(cmd, 30)
            started.append({"cmd": " ".join(cmd), "rc": r.returncode,
                            "err": (r.stderr or "").strip()[:150]})
            if r.returncode == 0:
                break
        except Exception as exc:          # noqa: BLE001
            started.append({"cmd": " ".join(cmd),
                            "err": "%s: %s" % (type(exc).__name__,
                                               str(exc)[:100])})
    out["steps"]["start"] = started

    # ⑥ 等它起来
    ok = False
    for _ in range(12):
        time.sleep(1)
        if _port_open():
            ok = True
            break
    out["steps"]["port_after_start"] = ok
    out["ok"] = ok
    if not ok:
        out["hint"] = ("OpenD 没能起来 ✗ ⇒ 大概率是**登录态失效**，"
                       "需要你在 Mac 上手动打开 OpenD 并重新登录富途账号")
    return out
def _act_test_futu_fed(params):
    """**验证富途 OpenD 的 `get_fed_watch_target_rate`** ✓（2026-11-05）。

    🔴 为什么这是 CME 的最优替代 ✗：
       搜到 moomoo/futu 开放平台有**官方接口** ✓：
         `OpenQuoteContext.get_fed_watch_target_rate()`
       文档原文：「获取 CME FedWatch 工具的联邦基金目标利率概率预测数据。
                 数据来源于 CME 联邦基金期货定价。」
       返回字段：
         `meeting_date`  str    FOMC 会议日期 "yyyy-MM-dd"
         `target_range`  str    目标利率区间，如 "4.25% ~ 4.50%"
         `probability`   float  市场预期概率(%)，如 92.13

    ✅ 为什么比爬虫好 ✗：
       - **官方接口** ✓ 不会因为 CME 改版而失效 ✓
       - **项目已在用 futu** ✓（`fetch_trades_futu.py` / `sync_positions.py` ✗）
         ⇒ **零新增依赖** ✓ 零新增凭证 ✓
       - **不需要浏览器** ✗ 不需要代理 ✗ 不需要 cookie ✗

    ⚠️ 前提：**OpenD 必须在跑** ✗（`127.0.0.1:11111` ✗）

    参数：`host`（默认 127.0.0.1 ✗）、`port`（默认 11111 ✗）、`write`（1=写盘 ✗）
    """
    host = str(params.get("host") or "127.0.0.1")
    port = int(params.get("port") or 11111)
    write = str(params.get("write") or "").lower() in ("1", "true", "yes")

    out = {"host": host, "port": port}
    try:
        import futu
        out["futu_version"] = getattr(futu, "__version__", "?")
        from futu import OpenQuoteContext
    except ImportError as exc:
        return {"ok": False, "error": "**没装 futu** ✗：%s" % str(exc)[:120]}

    has = hasattr(OpenQuoteContext, "get_fed_watch_target_rate")
    out["has_method"] = has
    if not has:
        out["fed_methods"] = [m for m in dir(OpenQuoteContext)
                              if "fed" in m.lower()]
        out["ok"] = False
        out["error"] = ("**这个 futu 版本没有 `get_fed_watch_target_rate`** ✗ "
                        "⇒ 需要升级 `pip install -U futu-api` ✗")
        return out

    ctx = None

    # 🔴 2026-11-10 第二次修正：**必须用子进程**，不能用守护线程 ✗
    #    实测：`_call_with_timeout` 超时后线程**杀不掉** ✗ ⇒ 它持有的
    #    `OpenQuoteContext` 继续重连 ⇒ 日志里 `on_disconnect` 刷屏到
    #    `conn=0(79)`（重连 79 次 ✗），并持续占用队列进程资源 ✗
    #    ⇒ 改子进程：超时 `proc.kill()` **连线程一起杀干净** ✓
    _code = (
        "import json\n"
        "try:\n"
        "    from futu import OpenQuoteContext\n"
        "    c = OpenQuoteContext(host=%r, port=%d)\n"
        "    try:\n"
        "        ret, data = c.get_fed_watch_target_rate()\n"
        "        d = {'ret': str(ret)[:80]}\n"
        "        try:\n"
        "            d['columns'] = [str(x) for x in list(data.columns)]\n"
        "            d['rows'] = int(len(data))\n"
        "            d['head'] = data.head(20).to_dict(orient='records')\n"
        "        except Exception:\n"
        "            d['raw'] = str(data)[:1500]\n"
        "        print(json.dumps(d, ensure_ascii=False, default=str))\n"
        "    finally:\n"
        "        try:\n"
        "            c.close()\n"
        "        except Exception:\n"
        "            pass\n"
        "except Exception as e:\n"
        "    print(json.dumps({'error': '%%s: %%s' %% (type(e).__name__, str(e)[:200])}))\n"
    ) % (host, port)

    try:
        proc = subprocess.Popen([sys.executable, "-c", _code],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace",
                                cwd=ROOT)
        try:
            so, se = proc.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            proc.kill()                       # ← 真正杀掉，线程一起没 ✓
            proc.communicate()
            out["ok"] = False
            out["error"] = ("**futu SDK 90 秒无响应** ✗ —— OpenD 疑似进入"
                            "无限重连循环（已 kill 子进程，不会残留重连线程 ✓）"
                            "⇒ 需重启/升级 OpenD，不是本脚本的问题 ✓")
            return out
        # 🔴 2026-11-10 实测：futu SDK 的日志**打到 stdout** ✗ ——
        #    `2026-11-10 14:55:17,234 | 76790 | ... | New connect ready: ...`
        #    ⇒ 原来取 `splitlines()[-1]` 拿到的是**日志行** ✗ 解析必失败 ✗
        #    ⇒ 改成**从后往前找第一行能解析成 JSON 的** ✓
        _res = None
        for _ln in reversed((so or "").strip().splitlines()):
            _ln = _ln.strip()
            if not _ln.startswith("{"):
                continue
            try:
                _res = json.loads(_ln)
                break
            except ValueError:
                continue
        if _res is None:
            out["ok"] = False
            out["error"] = ("子进程输出里找不到 JSON ✗（futu 日志混在 stdout）"
                            "：%s" % (so or "")[-400:])
            return out
        if _res.get("error"):
            out["ok"] = False
            out["error"] = "子进程报错：%s" % _res["error"]
            return out
        ret = _res.get("ret")
        out["ret"] = str(ret)[:80]
        # 🔴 2026-11-05 **关键修复**：`futu.RET_OK` **就是整数 0** ✗
        #    我原来写 `"RET_OK" in str(ret)` ✗
        #    ⇒ `str(0)` == `"0"` ✗ **永远不含 "RET_OK"** ✗
        #    ⇒ 接口明明成功了 ✗ 却被判成失败 ✗ 还提前 return 丢掉了 data ✗
        #    实测：`ret=0` `has_method=True` ⇒ **接口是通的** ✓
        #    ⇒ 判据改成 `ret == 0` ✓（同时兼容字符串形式 ✗）
        # 🔴 2026-11-10 第三次修正：**`ret` 现在是字符串** ✗
        #    改成子进程后，子进程里做了 `str(ret)[:80]` ⇒ 回到父进程是 `"0"` ✗
        #    而 `"0" == 0` 是 **False** ✗ ⇒ 接口明明成功（`ret=0`）却报
        #    「接口返回非 OK：0」✗（15:01 那份回执就是这样）
        #    ⇒ 统一转成字符串再比 ✓
        _ret_s = str(ret).strip()
        ok = _ret_s in ("0", "RET_OK") or ("RET_OK" in _ret_s)
        out["ok"] = ok
        if not ok:
            out["error"] = "接口返回非 OK：%s ✗" % str(ret)[:200]
            out["raw"] = str(_res.get("raw") or "")[:600]
            return out
        if _res.get("columns"):
            out["columns"] = _res["columns"]
            out["rows"] = _res.get("rows")
            out["head"] = _res.get("head")
        else:
            out["raw"] = str(_res.get("raw") or "")[:1500]
            return out

        # 可选写盘 ✓（统一成 `fedwatch.csv` 的列名 ✗ 让 `fed.py` 直接消费 ✓）
        if write and out.get("head"):
            import pandas as _pd
            d = _pd.DataFrame(out["head"])
            p = os.path.join(ROOT, "Data", "raw", "futu_fedwatch_raw.csv")
            d.to_csv(p, index=False, encoding="utf-8")
            out["written"] = os.path.relpath(p, ROOT)
    except Exception as exc:                # noqa: BLE001
        out["ok"] = False
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        out["hint"] = ("⚠️ 若是连接失败 ⇒ **OpenD 没开** ✗ "
                       "（`~/futu_OpenD/OpenD` 或 GUI 版 ✗）")
    # ⚠️ 子进程已 `communicate()` / `kill()` 收尸 ✓ ⇒ 无残留线程 ✓
    return out
def _act_futu_probe(params):
    """验证**富途 OpenD 是否可用** ✓（2026-11-16 用户要求）

    🔴 背景：简报报「富途 OpenD 不可用 —— 超过 180 秒未完成（疑似 SDK
       重连循环）」⇒ 连带两个 daily 脚本超时（`fetch_fedwatch_futu` 300s、
       `invest_research` 900s）⇒ 持仓 3 天未更新 ✗

    查**四层**（从粗到细，任一层失败就能定位问题在哪）：
      ① **进程**：`ps aux` 里有没有 `futu` / `OpenD` ✓
         （没有 ⇒ OpenD 根本没启动 ✗）
      ② **端口**：`127.0.0.1:11111` 能否 TCP 连上 ✓
         （连不上 ⇒ 进程在但没监听 / 防火墙 ✗）
      ③ **SDK**：`futu.OpenQuoteContext()` 能否构造成功 ✓
         （失败 ⇒ 端口通但协议层不对 / 版本不匹配 ✗）
      ④ **快照**：`get_market_snapshot(["US.SPY"])` 能否取到数据 ✓
         （失败 ⇒ 连接通但行情权限/登录态有问题 ✗）

    ⚠️ **只有 ④ 成功才算「可用」** ✗ —— 前三层都可能假通
       （实测过「端口通但 get_market_snapshot 一直超时」的情形）

    参数：`host`（默认 127.0.0.1）/ `port`（默认 11111）
    """
    import socket
    host = str(params.get("host") or "127.0.0.1")
    port = int(params.get("port") or 11111)
    out = {"host": host, "port": port, "steps": {}}

    # ① 进程
    try:
        r = _run(["ps", "aux"], 20)
        # 🔴 2026-11-16 用户要求：**精确匹配** ✓
        #    原来用 `"opend" in ln.lower()` ⇒ 误匹配 macOS 系统进程
        #    `/usr/libexec/opendirectoryd` ✗（实测回执里混进来了）
        #    ⇒ 只认 `futu`（覆盖 `~/.futu/opend/FutuOpenD.app` 全路径）✓
        hits = [ln.strip() for ln in (r.stdout or "").splitlines()
                if "futu" in ln.lower() and "grep" not in ln]
        out["steps"]["processes"] = [h[:150] for h in hits[:5]] or ["(无)"]
    except Exception as exc:              # noqa: BLE001
        out["steps"]["processes"] = "ERR %s" % str(exc)[:100]

    # ② 端口
    _port_ok = False
    try:
        _s = socket.create_connection((host, port), timeout=5)
        _s.close()
        _port_ok = True
        out["steps"]["port"] = "可连 ✓"
    except Exception as exc:              # noqa: BLE001
        out["steps"]["port"] = "不可连 ✗ %s" % str(exc)[:100]

    # ③④ SDK + 快照
    # 🔴 2026-11-16 实测事故：**必须走 `_call_with_timeout`** ✗
    #    第一版直接调 `_futu.OpenQuoteContext(...)` ⇒ OpenD 挂时 SDK
    #    **永不返回** ✗ ⇒ 队列单线程串行 ⇒ 整个队列卡死
    #    （用户告警「fg-task-queue 日志 653 秒没动静」就是这个 ✗）
    #    ⇒ 和 `test_futu_fed` 一样用守护线程 + join(timeout) ✓
    _snap_ok = False
    if not _port_ok:
        out["steps"]["sdk"] = "跳过（端口不通）✗"
        out["steps"]["snapshot"] = "跳过（端口不通）✗"
    else:
        def _probe():
            import futu as _futu
            ctx = _futu.OpenQuoteContext(host=host, port=port)
            try:
                return ctx.get_market_snapshot(["US.SPY"])
            finally:
                try:
                    ctx.close()
                except Exception:         # noqa: BLE001
                    pass

        try:
            _done, _res = _call_with_timeout(_probe, 60)
            if not _done:
                out["steps"]["sdk"] = "超时 60s ✗ ⇒ SDK 卡在连接（OpenD 挂）"
                out["steps"]["snapshot"] = "跳过（超时）✗"
            else:
                out["steps"]["sdk"] = "OpenQuoteContext 成功 ✓"
                _ret, _data = _res
                _n = len(_data) if hasattr(_data, "__len__") else "?"
                out["steps"]["snapshot"] = "ret=%s rows=%s" % (_ret, _n)
                _snap_ok = str(_ret).upper().endswith("OK") or _ret == 0
        except Exception as exc:          # noqa: BLE001
            out["steps"]["sdk"] = ("失败 ✗ %s: %s"
                                   % (type(exc).__name__, str(exc)[:150]))
            out["steps"]["snapshot"] = "跳过（SDK 失败）✗"

    out["ok"] = _snap_ok
    out["verdict"] = ("✅ **可用**（四层全过）" if _snap_ok
                      else "❌ **不可用** —— 看 steps 哪一层失败")
    return out
def _act_futu_preflight(params):
    """探一次富途 OpenD 端口 ✓ —— 只读、2 秒超时、零副作用 ✓。

    动机（2026-10-29）：新加的「预检 + 硬超时」要等到明天 05:30 才被跑到 ✗，
    这里让 Mac **立刻验一次** ✓，顺带把状态落盘（简报里就能看到）✓。
    """
    if os.path.join(ROOT, "scripts") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import futu_health
    ok, why = futu_health.preflight()
    futu_health.write_status(ok, why, "queue:futu_preflight")
    return {"ok": bool(ok), "reason": why}
def _act_sync_positions(params):
    """跑一次持仓/账户同步 ✓（`scripts/sync_positions.py`）。

    2026-11-02：用于验证 OKX 的 `securities_mv` / `cash` 拆分 ✓
    （`_okx_split_equity` 从 `/account/balance` 的 `details[]` 拆出来 ✓）
    ⚠️ 会**覆盖** `accounts.csv` / `positions.csv` 的当日行 ✗ —— 幂等 ✓
    """
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "sync_positions.py")]
    # 🔴 2026-11-02 实测：`sync_positions.py` 默认 **static** ✗ ——
    # static 下**不调任何外部 API**、**不碰 accounts/positions** ✗
    # ⇒ 队列任务跑完报 done，但什么都没验证到 ✗（第一次就是这么被骗的 ✗）
    # 而每日链 plist 里是 `FG_SYNC_MODE=live ... sync_positions.py` ✓
    # ⇒ 队列必须显式传 live ✓（否则「验证 OKX 拆分」这个目的达不到 ✗）
    env = dict(os.environ, FG_SYNC_MODE="live")
    try:
        r = _run(cmd, 300, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 300 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    # 🔴 2026-11-05：**回报 `day_pnl` 非空统计** ✓（用户要求 ✗）
    #    为什么需要 ✗：`fill_day_pnl` 刚加上 ✓ 但 stdout 里看不到效果 ✗
    #    而 `day_pnl` 之前 **54 行里只有 1 行有值** ✗（那列从来没被赋值 ✗）
    #    ⇒ 必须**直接统计列的非空数** ✗ 才能确认回填成功 ✓
    stats = {}
    try:
        import pandas as _pd
        p = os.path.join(ROOT, "Data", "accounts.csv")
        if os.path.exists(p):
            d = _pd.read_csv(p)
            stats["accounts_rows"] = int(len(d))
            if "day_pnl" in d.columns:
                nn = int(d["day_pnl"].notna().sum())
                stats["day_pnl_nonnull"] = nn
                stats["day_pnl_ratio"] = round(
                    nn / float(len(d)), 3) if len(d) else 0.0
            if "date" in d.columns:
                stats["date_unique"] = int(d["date"].nunique())
                dd = sorted(d["date"].astype(str).unique())
                stats["date_range"] = "%s → %s" % (dd[0], dd[-1]) if dd else ""
            # 每账户最近一天的 day_pnl ✓（看是否真的算出来了 ✗）
            if {"date", "account", "day_pnl"}.issubset(d.columns) and len(d):
                last = d[d["date"].astype(str) == str(d["date"].max())]
                stats["last_day"] = {
                    str(row["account"]): (None if _pd.isna(row["day_pnl"])
                                          else round(float(row["day_pnl"]), 2))
                    for _, row in last.iterrows()}
    except Exception as exc:                # noqa: BLE001
        stats["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:150])

    # 恒等式不成立时脚本 return 1 ✗ —— 那是**保护**不是崩溃 ✓
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "day_pnl_stats": stats,
            "note": "rc=1 多半是恒等式校验拦住了（sec_mv+cash != net）✗",
            "stdout": (r.stdout or "")[-1500:],
            "stderr": (r.stderr or "")[-600:]}


ACTIONS = {
    "futu_preflight": _act_futu_preflight,
    "futu_probe": _act_futu_probe,
    "futu_opend_info": _act_futu_opend_info,
    "futu_opend_update": _act_futu_opend_update,
    "futu_upgrade_restart": _act_futu_upgrade_restart,
    "test_futu_fed": _act_test_futu_fed,
    "sync_positions": _act_sync_positions,
    "realtime_diag": _act_realtime_diag,
}
