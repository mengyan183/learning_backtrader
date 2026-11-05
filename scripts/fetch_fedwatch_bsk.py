# -*- coding: utf-8 -*-
"""用 **bsk（真实 Chromium）** 抓 CME FedWatch ✓（2026-11-04 用户裁定「CME 用 bsk」）。

【为什么改用 bsk】
  ① 旧方案 headless Chrome ✗ 拿不到数据 ✗
     实测 `--dump-dom` 得 287KB ✗ 有 `FedWatch` 字样、有 `ZQ` 合约代码 ✗
     但**零个百分比数字** ✗ ⇒ 数据是 JS 异步渲染的 ✗
  ② 直接调 API ✗ `CmeWS/mvc/quotes/v2/contracts-by-number` **403** ✗
  ③ bsk 用的是**用户真实浏览器** ✓ 已有登录态/cookie ✓ 能过 JS 挑战 ✓

【流程】（严格按 bsk 的 lifecycle ✗ 不遵守会报
        `shared page control or observation changed` ✗）
  `bsk session start`            → 拿 4 字母 session id ✓
  `bsk navigate <url> --session` → 打开页面 ✓
  `bsk wait-ms 8000 --session`   → **等 JS 渲染** ✓（关键 ✗ 不等就是空表）
  `bsk get-html --session`       → 拿**渲染后**的 HTML ✓
  `bsk session stop <id>`        → **必须停** ✓（成功/异常都要 ✗）

【⚠️ 已知限制】
  - 需要 Mac 上 **Chrome 常驻 + bsk daemon 在跑** ✗
  - 需要页面**已登录/无验证码** ✗（首次可能要人处理 ✗）
  - 与 **OpenClaw agent** 抢浏览器会失败 ✗（见 `--retries`）

用法：
    python scripts/fetch_fedwatch_bsk.py --dump-html /tmp/cme.html
    python scripts/fetch_fedwatch_bsk.py --write      # 解析并写 fedwatch.csv
"""
import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fg_system import config  # noqa: E402

def _find_bsk():
    """**自动探测 `bsk` 可执行文件** ✓（2026-11-04 修）。

    🔴 为什么不能直接 `["bsk", ...]` ✗：
       实测（Mac / launchd 环境）：
         `session_start rc=-1  **找不到 bsk** ✗`
       而 bsk **确实装着** ✓（`fetch_shoutu_history.py` 用过 ✓）
       ⇒ 因为 **launchd 的 PATH 不含 `~/.local/bin` / `/opt/homebrew/bin`** ✗
         （plist 里只加过 `/opt/homebrew/bin` ✗ 而 bsk 可能装在
          `~/.local/bin` 或 `~/Library/Python/*/bin` ✗）

    ⇒ 依次尝试：`FG_BSK` 环境变量 → `shutil.which` → 常见路径 ✓
    """
    env = os.environ.get("FG_BSK")
    if env and os.path.exists(env):
        return env
    import shutil
    w = shutil.which("bsk")
    if w:
        return w
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, ".local", "bin", "bsk"),
        "/opt/homebrew/bin/bsk",
        "/usr/local/bin/bsk",
        "/usr/bin/bsk",
        os.path.join(home, ".npm-global", "bin", "bsk"),
    ]
    # `~/Library/Python/3.x/bin/bsk`（pip --user 常见位置 ✗）
    import glob as _g
    cands += sorted(_g.glob(os.path.join(
        home, "Library", "Python", "*", "bin", "bsk")), reverse=True)
    for c in cands:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None


BSK = _find_bsk() or "bsk"      # 探测失败仍用 "bsk" ✓（至少报错更明确 ✗）
PAGE = config.FEDWATCH_PAGE_URL
#: 等 JS 渲染的毫秒数 ✗ —— 实测页面要 5~10 秒才出表格 ✓
WAIT_MS = int(os.environ.get("FG_CME_WAIT_MS") or 8000)


def _run(args, timeout=120):
    """跑一条 bsk 命令 ✓ 返回 `(rc, stdout, stderr)`。"""
    try:
        r = subprocess.run([BSK] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except FileNotFoundError:
        # 探测结果给出来 ✓ 便于定位是「没装」还是「PATH 不含」✗
        import shutil as _sh
        where = _sh.which("bsk") or "(which 也找不到 ✗)"
        return -1, "", ("**找不到 bsk** ✗\n"
                        "   探测结果：BSK=%r  which=%s\n"
                        "   常见路径：~/.local/bin/bsk / /opt/homebrew/bin/bsk\n"
                        "   ⇒ 设 `FG_BSK=/完整/路径/bsk` 或 `pip install browser-skill` ✗"
                        % (BSK, where))
    except subprocess.TimeoutExpired:
        return -2, "", "bsk 命令超时（%ds ✗）" % timeout


def fetch_html(wait_ms=WAIT_MS, retries=2, debug=False):
    """用 bsk 打开 CME FedWatch 并返回**渲染后**的 HTML ✓。

    :returns: `(html, info)` —— `html` 为 `None` 表示失败 ✓ `info` 带诊断 ✗
    """
    info = {"page": PAGE, "wait_ms": wait_ms, "attempts": []}
    for attempt in range(retries + 1):
        rc, out, err = _run(["session", "start"], timeout=60)
        sid = (out or "").strip().splitlines()[-1].strip() if out else ""
        if rc != 0 or not re.fullmatch(r"[a-z0-9]{3,12}", sid or ""):
            info["attempts"].append({"step": "session_start", "rc": rc,
                                     "out": out[-200:], "err": err[-300:]})
            time.sleep(3)
            continue
        info["session"] = sid
        try:
            rc, out, err = _run(["navigate", PAGE, "--session", sid],
                                timeout=180)
            info["attempts"].append({"step": "navigate", "rc": rc,
                                     "out": out[-200:], "err": err[-300:]})
            if rc != 0:
                continue
            # 🔴 **必须等 JS 渲染** ✗ 不等就是空表 ✗
            #    2026-11-04 踩坑：`bsk wait-ms` **没有 `--session` 参数** ✗
            #      实测 `bsk wait-ms --help`：
            #        Usage: bsk wait-ms [OPTIONS] <DURATION>
            #        （只接受时长 ✗ 且是 **daemon 侧 sleep** ✗ 与 session 无关 ✗）
            #      ⇒ 原来传 `--session sid` ⇒ **命令报错** ✗ 而返回值没检查 ✗
            #      ⇒ **等待从未生效** ✗ 5.1 秒就 get-html ✗ 页面没渲染完 ✗
            #      ⇒ 症状：HTML 217KB ✗ 但 `pct_total=0` ✗
            wrc, wout, werr = _run(["wait-ms", str(wait_ms)], timeout=90)
            info["attempts"].append({"step": "wait_ms", "rc": wrc,
                                     "ms": wait_ms, "err": werr[-200:]})
            rc, html, err = _run(["get-html", "--session", sid], timeout=120)
            info["attempts"].append({"step": "get_html", "rc": rc,
                                     "len": len(html or ""),
                                     "err": err[-300:]})
            if rc == 0 and html and len(html) > 10000:
                info["ok"] = True
                info["html_len"] = len(html)
                return html, info
        finally:
            # 🔴 **成功/异常都要停** ✓
            _run(["session", "stop", sid], timeout=60)
        time.sleep(2)
    info["ok"] = False
    return None, info


#: CME 的月份缩写 ✓
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"))}


def parse(html):
    """从**渲染后**的 HTML 解析 FedWatch 数据 ✓。

    🔴 2026-11-04：**旧正则全部作废** ✗
       旧代码找 `<td class="number">78.4%</td>` ✗
       而实测新页面 `has_number_td: False` ✗ ⇒ 结构完全不同 ✗
       ⇒ 本函数**多套正则并试** ✓ 哪个出结果用哪个 ✓
       ⇒ 并在 `raw_hits` 里回传命中的样本 ✓ 便于下次调 ✗
    """
    out = {"meetings": [], "prob_rows": [], "zones": [],
           "raw_hits": {}, "source_len": len(html or "")}
    if not html:
        return out

    # ① 会议日期 + 合约代码（ZQ 系列 ✗ 这个在实测里存在 ✓）
    for d, mon, y, con in re.findall(
            r'(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})[^A-Za-z]{0,80}(ZQ\w+)',
            html):
        m = _MONTHS.get(mon[:3].lower())
        if not m:
            continue
        key = "%04d-%02d-%02d" % (int(y), m, int(d))
        if key not in out["meetings"]:
            out["meetings"].append(key)
    out["raw_hits"]["meeting_con"] = len(out["meetings"])

    # ② 概率三元组（宽松版 ✗ 不依赖 td class ✗）
    #    匹配「78.4%」这种，且同一段里连着出现 3 个 ✓
    pcts = re.findall(r'(\d{1,3}\.\d)\s*%', html)
    out["raw_hits"]["pct_total"] = len(pcts)
    if len(pcts) >= 3:
        # 按 3 个一组切 ✓（FedWatch 每行是 ease/hold/hike ✗）
        for i in range(0, len(pcts) - 2, 3):
            out["prob_rows"].append(tuple(pcts[i:i + 3]))
    out["raw_hits"]["prob_rows"] = len(out["prob_rows"])

    # ③ 目标区间（`375-400` / `400-425` 这类 ✗）
    zones = re.findall(r'(\d{3})\s*[-–]\s*(\d{3})', html)
    out["zones"] = sorted(set("%s-%s" % (a, b) for a, b in zones))[:12]
    out["raw_hits"]["zones"] = len(out["zones"])

    return out


def diagnose(wait_ms=20000, debug=True):
    """**把 bsk 的工具全跑一遍** ✓（2026-11-04 用户要求「完整使用 bsk 功能」）。

    🔴 为什么需要：
       实测 `get-html` 拿到 478 KB ✗ 但 `<table>` 标签 **0 个** ✗
       零个百分比 ✗ ⇒ **不知道数据在哪** ✗
       可能：① 在 `<iframe>` 里 ✗ ② 在 JS 变量里 ✗ ③ 需要交互才加载 ✗
       ⇒ 必须用**别的 bsk 工具**去探 ✓

    【跑 5 件事】
      ① `observe`      —— 语义视图（能直接看到表格数据吗 ✗）
      ② `tab list`     —— 有没有子 frame / 新 tab ✓
      ③ `network`      —— 它请求了哪些 API ✓ ← **最有价值**
      ④ `evaluate`     —— `window` 上有没有 QuikStrike / 数据对象 ✓
      ⑤ `snapshot`     —— 无障碍树（比 observe 更严格 ✗）
    """
    out = {"page": PAGE, "wait_ms": wait_ms, "steps": {}}
    rc, o, e = _run(["session", "start"], timeout=60)
    sid = (o or "").strip().splitlines()[-1].strip() if o else ""
    if rc != 0 or not sid:
        return {"ok": False, "error": "session start 失败",
                "stdout": o[-300:], "stderr": e[-300:]}
    out["session"] = sid
    try:
        rc, o, e = _run(["navigate", PAGE, "--session", sid,
                         "--timeout", "90s"], timeout=180)
        out["steps"]["navigate"] = {"rc": rc, "out": o[-200:], "err": e[-200:]}
        if rc != 0:
            return out
        wrc, _, werr = _run(["wait-ms", str(wait_ms)], timeout=90)
        out["steps"]["wait_ms"] = {"rc": wrc, "ms": wait_ms, "err": werr[-150:]}

        # ① observe ✓
        rc, o, e = _run(["observe", "--session", sid], timeout=120)
        hits = sum(o.count(k) for k in ("%", "ZQ", "Target", "Prob"))
        out["steps"]["observe"] = {
            "rc": rc, "lines": len((o or "").splitlines()),
            "len": len(o or ""), "data_hits": hits,
            "head": (o or "")[:500],
        }

        # ② tab list（看 iframe / 子 tab ✗）
        rc, o, e = _run(["tab", "list", "--session", sid], timeout=60)
        out["steps"]["tab_list"] = {"rc": rc, "out": (o or "")[:1200]}

        # ③ network（**最有价值** ✗ 看它请求什么 API + **响应体** ✓）
        #    🔴 2026-11-04 实测：`network --help` 有 `--max-text-chars` ✗
        #       ⇒ **能拿到响应体** ✓ 这是关键 ✓
        #       因为 `CmeWS/mvc/quotes/v2/contracts-by-number` 在浏览器里
        #       是 **200 成功** ✓（带 cookie ✗）而纯 HTTP 直调是 **403** ✗
        #       ⇒ 从浏览器的 network 缓冲里取响应 ✗ 就能绕过 403 ✓
        rc, o, e = _run(["network", "--session", sid, "--json",
                         "--limit", "200", "--max-text-chars", "30000"],
                        timeout=120)
        urls = re.findall(r"https?://[^\s\"'<>\\]+", o or "")
        api = [u for u in urls
               if any(k in u.lower() for k in
                      ("cmews", "quotes", "contracts", "quikstrike"))]
        # 从 JSON 里找 `contracts-by-number` 那条的响应体 ✓
        cbn_body, cbn_status = "", None
        try:
            import json as _j2
            arr = _j2.loads(o) if (o or "").strip().startswith(("[", "{")) else []
            if isinstance(arr, dict):
                arr = arr.get("entries") or arr.get("items") or []
            for it in (arr or []):
                u = str(it.get("url") or "")
                if "contracts-by-number" in u:
                    cbn_status = it.get("status")
                    cbn_body = str(it.get("text") or it.get("body") or "")
                    if not cbn_body:
                        cbn_body = str(it.get("response") or "")[:30000]
        except Exception as exc:            # noqa: BLE001
            out["steps"].setdefault("network_parse_error", str(exc)[:150])
        out["steps"]["network"] = {
            "rc": rc, "total_urls": len(urls),
            "api_urls": sorted(set(api))[:10],
            "cbn_status": cbn_status,
            "cbn_body_len": len(cbn_body),
            "cbn_body_head": cbn_body[:2500],
            "raw_head": (o or "")[:300],
        }

        # ④ evaluate（找 window 上的数据 ✓）
        #    🔴 2026-11-04 踩坑（两次）：
        #      v1：`f=>f.src` 箭头函数 + 多层引号嵌套 ⇒ rc=1 ✗
        #      v2：改成极简 JS ⇒ **仍 rc=1** ✗ 错误变成：
        #          `shared page control or observation changed`
        #          `requires the context returned by the latest cooperate sync` ✗
        #    ⇒ 根因**不是 JS 语法** ✗ 而是 **`evaluate` 要求「刚刚 observe 过」** ✗
        #      中间夹了 `tab list` / `network` ⇒ 上下文失效 ✗
        #    ⇒ **在 evaluate 前重新 observe 一次** ✓（刷新控制上下文 ✗）
        _run(["observe", "--session", sid], timeout=90)
        js = (
            "JSON.stringify({"
            "hasQuik: (typeof window.QuikStrike !== 'undefined'),"
            "tables: document.querySelectorAll('table').length,"
            "iframes: document.querySelectorAll('iframe').length,"
            "bodyLen: (document.body ? document.body.innerText.length : 0),"
            "pcts: (document.body ? "
            "(document.body.innerText.match(/[0-9]+[.][0-9][ ]*%/g) || [])"
            ".slice(0,20) : [])"
            "})"
        )
        rc, o, e = _run(["evaluate", js, "--session", sid], timeout=90)
        out["steps"]["evaluate"] = {"rc": rc, "out": (o or "")[:600],
                                    "err": e[-300:]}

        # ④b 🔴 **点开那个「Select your ...」按钮** ✓
        #     实测 `observe` 里唯一可交互的是它 ✗ 而页面**没有任何表格数据** ✗
        #     ⇒ 强烈怀疑**必须先选一个选项**（日期 / 会议 ✗）才加载数据 ✗
        #
        #     🔴 2026-11-05 **关键踩坑**：不能用 `@eN` ref ✗
        #        错误：`shared page control or observation changed` ✗
        #        根因：CME 页面**持续动态变化**（倒计时每秒刷新 ✗ 数据异步 ✗）
        #              ⇒ `observe` 拿到的 `@eN` 快照**立刻失效** ✗
        #        ⇒ 本机实测（example.com 静态页）`click a` **成功** ✓
        #          ⇒ 证明 bsk 没问题 ✓ 是**页面变化太快** ✗
        #        ⇒ 改用 **CSS 选择器** ✓ 它不依赖快照 ✓
        css_cands = [
            "button[aria-haspopup]",
            "main button",
            "select",
            "[class*=dropdown] button",
        ]
        for css in css_cands:
            crc, cout, cerr = _run(
                ["click", "--selector", css, "--session", sid,
                 "--timeout", "20s"], timeout=60)
            out["steps"]["click_%s" % css] = {
                "rc": crc, "css": css,
                "out": cout[-250:], "err": cerr[-250:]}
            if crc == 0:
                _run(["wait-ms", "4000"], timeout=30)
                rc2, o2, e2 = _run(["observe", "--session", sid], timeout=90)
                out["steps"]["observe_after_click"] = {
                    "rc": rc2, "lines": len((o2 or "").splitlines()),
                    "data_hits": sum(o2.count(k) for k in ("%", "ZQ", "Target")),
                    "head": (o2 or "")[:600],
                }
                break

        # ④c 🔴 **查 iframe** ✓（2026-11-05 关键假设 ✗）
        #     现象：`get-html` 478 KB ✗ 但 `<table>` **0 个** ✗ 零个百分比 ✗
        #           `observe` 有 FedWatch 框架 ✗ 但没数据 ✗
        #           `click` / `evaluate` 报 `shared page control` ✗
        #     ⇒ **统一解释：数据在跨域 `<iframe>` 里** ✗
        #       - `get-html` 只拿主文档 ⇒ 拿不到 iframe 内容 ✓
        #       - `observe` 只看主文档的无障碍树 ✓
        #       - iframe 抢了「页面控制权」⇒ 写操作被拒 ✓
        #     ⇒ 必须确认有没有 iframe ✗ 有几个 ✗ src 是什么 ✓
        rc, html, e = _run(["get-html", "--session", sid], timeout=120)
        iframes = re.findall(
            r"<iframe[^>]*?(?:src|data-src)\s*=\s*[\"']([^\"']+)[\"']",
            html or "", re.I)
        out["steps"]["iframes"] = {
            "rc": rc, "html_len": len(html or ""),
            "count": len(iframes),
            "srcs": [u[:200] for u in iframes[:10]],
            "has_table_tag": "<table" in (html or "").lower(),
            "pct_in_html": len(re.findall(r"\d{1,3}\.\d\s*%", html or "")),
        }

        # ⑤ snapshot（无障碍树 ✗ 比 observe 更严格）
        rc, o, e = _run(["snapshot", "--session", sid], timeout=120)
        out["steps"]["snapshot"] = {
            "rc": rc, "lines": len((o or "").splitlines()),
            "data_hits": sum(o.count(k) for k in ("%", "ZQ", "Target")),
            "head": (o or "")[:400],
        }
    finally:
        _run(["session", "stop", sid], timeout=60)
    out["ok"] = True
    return out


def main():
    ap = argparse.ArgumentParser(
        description="用 bsk 抓 CME FedWatch（真实浏览器 ✗ 能过 JS 渲染 ✓）")
    ap.add_argument("--dump-html", metavar="PATH",
                    help="把渲染后的 HTML 存到 PATH（用于**先看结构** ✗）")
    ap.add_argument("--write", action="store_true",
                    help="解析并写 `Data/raw/fedwatch.csv` ✓")
    ap.add_argument("--wait-ms", type=int, default=WAIT_MS,
                    help="等 JS 渲染的毫秒数（默认 %d ✗）" % WAIT_MS)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--debug", action="store_true")
    # 🔴 2026-11-04：**把 bsk 的工具全跑一遍** ✓（observe/tab/network/evaluate/snapshot）
    ap.add_argument("--diagnose", action="store_true",
                    help="跑 observe+tab+network+evaluate+snapshot，定位数据在哪 ✗")
    args = ap.parse_args()

    if args.diagnose:
        import json as _json
        r = diagnose(wait_ms=args.wait_ms)
        print(_json.dumps(r, ensure_ascii=False, indent=2)[:12000])
        return 0 if r.get("ok") else 2

    html, info = fetch_html(wait_ms=args.wait_ms, retries=args.retries,
                            debug=args.debug)
    if args.dump_html and html:
        # 🔴 相对路径按 ROOT 解析 ✓（`run_fetch_step` 的 cwd 是仓库根 ✗）
        out_path = args.dump_html
        if not os.path.isabs(out_path):
            out_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                out_path)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print("HTML 已存：%s（%.1f KB ✗）"
              % (out_path, len(html) / 1024.0))

    # 🔴 2026-11-04：**把 HTML 里的关键片段打出来** ✓
    #    因为 217KB 的文件没法直接看 ✗ 而 `pct_total=0` 需要知道
    #    「页面里到底有什么」✗ 才能判断是「没渲染」还是「结构变了」✗
    if html:
        import re as _re2
        print("\n--- HTML 特征 ---")
        for key in ("FedWatch", "ZQ", "probability", "Probability",
                    "target rate", "Target Rate", "table", "quikstrike",
                    "QuikStrike", "CmeWS"):
            print("  %-14s %s" % (key, html.count(key)))
        # 任何数字+% 的样本 ✓（不限于 `>78.4%<` ✗）
        pcts = _re2.findall(r"(\d{1,3}\.\d)\s*%", html)[:15]
        print("  百分比样本:", pcts if pcts else "(零个 ✗)")
        # 找最大的 `<table>` 片段 ✓
        tbls = _re2.findall(r"<table.{0,4000}?</table>", html, _re2.S)
        print("  table 数量:", len(tbls))
        if tbls:
            print("  最大 table 前 600 字：")
            print("  " + max(tbls, key=len)[:600].replace("\n", " "))

    if not html:
        print("✗ bsk 抓取失败 ✗", file=sys.stderr)
        for a in info.get("attempts", []):
            print("   %s rc=%s %s %s" % (a.get("step"), a.get("rc"),
                                         str(a.get("out") or "")[:120],
                                         str(a.get("err") or "")[:200]),
                  file=sys.stderr)
        return 2

    data = parse(html)
    print("meetings=%d prob_rows=%d zones=%d pct_total=%d"
          % (len(data["meetings"]), len(data["prob_rows"]),
             len(data["zones"]), data["raw_hits"].get("pct_total", 0)))
    if args.debug:
        print("meetings:", data["meetings"][:6])
        print("prob_rows:", data["prob_rows"][:6])
        print("zones:", data["zones"][:6])

    if not args.write:
        return 0

    # ---- 写盘 ✓ ----
    # ⚠️ **字段映射待确认** ✗ —— 必须先看 `--dump-html` 的真实结构 ✗
    #    现在按「meeting + 第一个 prob_row」尽力而为 ✓
    if not data["meetings"] or not data["prob_rows"]:
        print("✗ 解析不到 meetings / prob_rows ⇒ **不能写盘** ✗"
              "（先跑 --dump-html 看结构 ✗）", file=sys.stderr)
        return 3

    rows = []
    for i, mt in enumerate(data["meetings"]):
        if i >= len(data["prob_rows"]):
            break
        e, h, k = data["prob_rows"][i]
        rows.append({"date": datetime.now().strftime("%Y-%m-%d"),
                     "meeting": mt, "ease_pct": e, "hold_pct": h,
                     "hike_pct": k, "src": "cme-bsk"})
    if not rows:
        print("✗ 无有效行 ✗", file=sys.stderr)
        return 3

    import csv
    path = os.path.join(config.RAW_DIR, "fedwatch.csv")
    os.makedirs(config.RAW_DIR, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("✓ 已写 %s（%d 行 ✗）" % (path, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
