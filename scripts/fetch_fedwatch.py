#!/usr/bin/env python3
"""CME FedWatch 市场预期抓取（FOMC 加息/降息概率）——全自动会话刷新版。

数据源：QuikStrike FedWatch 数据页（服务端渲染 .aspx，可直连）。
会话机制（实测 2026-10-05）：
- insid(工具实例) + qsid(会话) 由 CME 宿主页面每次打开时动态生成
- curl 无法自行创建会话（服务端仅接受宿主页面上下文创建的 QSID）
- 自动刷新 = headless Chrome 打开 CME 页面 → 网络日志提取 View.aspx
  请求里的最新 insid+qsid（本机 Chrome，~15s，无人工）

流程：
1. 会话 = 上次成功会话（Data/raw/fedwatch_session.json）或 config 默认值
2. curl 抓 QuikStrikeView.aspx（代理 7890 + cmegroup Referer）→ 解析
3. 失败（302/403/ErrorPage/无数据）→ headless 刷新会话 → 重试
4. 成功 → 更新会话文件；失败仅告警、不覆盖旧数据

用法:
  .venv/bin/python scripts/fetch_fedwatch.py           # 抓取+自动刷新
  .venv/bin/python scripts/fetch_fedwatch.py --debug    # 打印解析明细
  .venv/bin/python scripts/fetch_fedwatch.py --force-refresh  # 强制先刷新会话

输出: Data/raw/fedwatch.csv（追加行，同一天幂等）
  date | meeting | ease_pct | hold_pct | hike_pct
  | now_hold_pct | now_hike_pct | wk_hold_pct | wk_hike_pct
  | m_hold_pct | m_hike_pct | src
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DATA = REPO / "Data"
RAW = DATA / "raw"
OUT = RAW / "fedwatch.csv"

from fg_system import config

PROXY = "http://127.0.0.1:7890"


def _find_chrome():
    """**自动探测 Chrome/Chromium 路径** ✓（2026-11-03 修）。

    🔴 原来 `CHROME` 写死 `/Applications/Google Chrome.app/...` ✗
       ⇒ 没装 Chrome（只有 Chromium / 或装在其他位置）时
         `subprocess.run` 抛 `OSError` ✗ 被 `except` 吞掉 ✗
         只打印「刷新异常」✗ 看起来像网络问题 ✗ **实际是找不到浏览器** ✗
    """
    cands = [
        os.environ.get("FG_CHROME") or "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/opt/homebrew/bin/chromium",
        "/usr/local/bin/chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _load_session():
    """上次成功会话 → (insid, qsid)；无则用 config 默认。"""
    p = config.FEDWATCH_SESSION_FILE
    try:
        with open(p) as f:
            s = json.load(f)
        if s.get("insid") and s.get("qsid"):
            return str(s["insid"]), str(s["qsid"])
    except (OSError, ValueError):
        pass
    return config.FEDWATCH_INSID, config.FEDWATCH_QSID


def _save_session(insid, qsid):
    RAW.mkdir(parents=True, exist_ok=True)
    with open(config.FEDWATCH_SESSION_FILE, "w") as f:
        json.dump({"insid": insid, "qsid": qsid,
                   "updated": dt.datetime.now().isoformat()}, f)


def _kill_stray_chrome():
    """清理残留的 headless Chrome（避免单实例冲突卡住）。"""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "Google Chrome.*headless=new"],
            capture_output=True, text=True, timeout=10)
        for pid in out.stdout.split():
            subprocess.run(["kill", pid], capture_output=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass


def dump_netlog_urls(netlog_path, patterns=None):
    """**从 netlog 里提取所有 URL** ✓（2026-11-04 用户要求「CME 要适配」）。

    🔴 为什么需要：
       实测 `netlog 8.7MB` ✗ 但**零个 `QuikStrike` 请求** ✗
       ⇒ 说明 CME 换了接口 ✗ 或加了反爬 ✗
       ⇒ **必须知道它现在请求什么** 才能适配 ✓

    :param patterns: 只保留包含这些子串的 URL（默认 `cme` / `quikstrike`
                     / `api` / `fedwatch` ✗ 不区分大小写 ✓）
    """
    import json as _json

    pats = [p.lower() for p in (patterns or
                                ("cme", "quikstrike", "fedwatch", "api"))]
    urls = {}
    try:
        with open(netlog_path, "r", encoding="utf-8", errors="ignore") as f:
            # netlog 是**大 JSON** ✗ 逐行扫 `"url"` 字段（比整体解析快 ✓）
            for line in f:
                if '"url"' not in line:
                    continue
                for m in re.finditer(r'"url"\s*:\s*"((?:[^"\\]|\\.)+)"', line):
                    u = m.group(1)
                    # 反转义 ✓（netlog 里 `\/` 很常见 ✗）
                    u = u.replace("\\/", "/").replace("\\u0026", "&")
                    lo = u.lower()
                    if not any(p in lo for p in pats):
                        continue
                    # 去掉 query 里的随机参数 ✗ 便于归并 ✓
                    base = u.split("?")[0]
                    urls[base] = urls.get(base, 0) + 1
    except OSError as exc:
        return {"error": str(exc)[:120]}
    top = sorted(urls.items(), key=lambda kv: -kv[1])[:40]
    # 🔴 2026-11-04 补充：**保留 query 参数** ✓
    #    实测发现新接口 `CmeWS/mvc/quotes/v2/contracts-by-number` ✗
    #    但 `dump_netlog_urls` **去掉了 query** ✗ ⇒ 看不到**参数格式** ✗
    #    ⇒ 适配时必须知道它带什么参数 ✓
    samples = {}
    try:
        with open(netlog_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"url"' not in line:
                    continue
                for m in re.finditer(r'"url"\s*:\s*"((?:[^"\\]|\\.)+)"', line):
                    u = m.group(1).replace("\\/", "/").replace("\\u0026", "&")
                    lo = u.lower()
                    # 只挑「可能有数据」的接口 ✓（排除字体/脚本/样式 ✗）
                    if not any(k in lo for k in ("cmews", "quotes", "contracts",
                                                 "quikstrike", "api/")):
                        continue
                    base = u.split("?")[0]
                    bucket = samples.setdefault(base, [])
                    if len(bucket) < 3 and u not in bucket:
                        bucket.append(u[:400])
    except OSError:
        pass

    return {"unique": len(urls),
            "top": [{"url": u[:220], "hits": n} for u, n in top],
            "api_samples": samples}


def _refresh_session(debug=False, retries=2, keep_netlog=False,
                     dump_urls=False):
    """headless Chrome 打开 CME FedWatch 页面 → netlog 提取最新 insid+qsid。
    返回 (insid, qsid)；失败返回 (None, None)。"""
    chrome = _find_chrome()
    if not chrome:
        # 🔴 2026-11-03：**必须明确说「找不到浏览器」** ✗
        #    原来静默 `(None, None)` ⇒ 上层 `sys.exit(2)` ⇒
        #    日志只写「无法获取会话」✗ 完全误导 ✗
        print("[fedwatch] ✗ **找不到 Chrome/Chromium** ✗ —— "
              "设环境变量 `FG_CHROME=/path/to/chrome` 或装 Chrome ✓",
              file=sys.stderr)
        return None, None
    if debug:
        print("[fedwatch] 使用浏览器：%s" % chrome)

    for attempt in range(retries + 1):
        _kill_stray_chrome()
        fd, netlog = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                   "--proxy-server=" + PROXY, "--user-agent=" + UA,
                   # 🔴 20000 → 40000：CME 页面在代理下加载慢 ✗
                   #    实测 20s 常常 dump 到空 DOM ✗
                   "--virtual-time-budget=40000",
                   "--log-net-log=" + netlog,
                   "--net-log-capture-mode=IncludeSensitive",
                   "--dump-dom", config.FEDWATCH_PAGE_URL]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=180)
            if debug and r.returncode != 0:
                print("[fedwatch] chrome rc=%s stderr=%s"
                      % (r.returncode, (r.stderr or "")[-200:]))
            with open(netlog, encoding="utf-8", errors="ignore") as f:
                data = f.read()
            m = re.search(r'QuikStrikeView\.aspx[^"\\]{0,300}?insid=(\d+)[^"\\]{0,200}?qsid=([a-f0-9\-]{36})',
                          data)
            if not m:
                m = re.search(r'QuikStrikeView\.aspx[^"\\]{0,300}?qsid=([a-f0-9\-]{36})', data)
                if m:
                    qsid = m.group(1)
                    m2 = re.search(r'insid=(\d+)[^"\\]{0,300}?qsid=' + qsid, data)
                    if m2:
                        m = m2
            if m and m.lastindex == 2:
                insid, qsid = m.group(1), m.group(2)
                if debug:
                    print("[fedwatch] 会话刷新(%d): insid=%s qsid=%s"
                          % (attempt + 1, insid, qsid))
                return insid, qsid
            # 🔴 2026-11-03：**失败原因必须总是可见** ✗
            #    原来 `if debug:` 才打印 ✗ ⇒ 链里跑时完全静默 ✗
            #    ⇒ 21 天没人知道是「Chrome 缺失」还是「页面结构变了」✗
            nlog = len(data)
            has_qs = "QuikStrike" in data
            print("[fedwatch] ✗ 第 %d 次失败：netlog %d 字节，含 QuikStrike=%s"
                  % (attempt + 1, nlog, has_qs), file=sys.stderr)

            # 🔴 2026-11-04：**把真实请求打出来** ✓（适配新接口的唯一途径 ✗）
            if dump_urls:
                info = dump_netlog_urls(netlog)
                print("[fedwatch] netlog 里的相关 URL（%s 个唯一）✗"
                      % info.get("unique", "?"), file=sys.stderr)
                for it in (info.get("top") or [])[:25]:
                    print("   [%4d] %s" % (it["hits"], it["url"]),
                          file=sys.stderr)
                # 🔴 接口的**完整 URL（含参数）** ✓ —— 适配的唯一依据 ✗
                for base, us in (info.get("api_samples") or {}).items():
                    print("[fedwatch] 接口样本 %s" % base, file=sys.stderr)
                    for u in us:
                        print("   → %s" % u, file=sys.stderr)
            if keep_netlog:
                keep = os.path.join(
                    tempfile.gettempdir(),
                    "fedwatch_netlog_%d.json" % (attempt + 1))
                try:
                    os.replace(netlog, keep)
                    print("[fedwatch] netlog 已保留：%s（%.1f MB ✗）"
                          % (keep, nlog / 1048576.0), file=sys.stderr)
                    # 已移走 ⇒ 下面 `finally` 的 remove 会失败但不影响 ✓
                except OSError as exc:
                    print("[fedwatch] 保留 netlog 失败：%s" % exc,
                          file=sys.stderr)
            if nlog < 5000:
                print("[fedwatch]   ⇒ netlog 太小 ⇒ **Chrome 没真正打开页面** ✗"
                      "（代理不通 / 浏览器崩溃 ✗）", file=sys.stderr)
            elif not has_qs:
                print("[fedwatch]   ⇒ 有 netlog 但**无 QuikStrike 请求** ✗"
                      "（CME 页面结构变了 / 被反爬拦 ✗）", file=sys.stderr)
            else:
                print("[fedwatch]   ⇒ 有 QuikStrike 但**正则不匹配** ✗"
                      "（insid/qsid 格式变了 ✗）", file=sys.stderr)
        except (subprocess.TimeoutExpired, OSError) as e:
            print("[fedwatch] ✗ 第 %d 次异常：%s: %s"
                  % (attempt + 1, type(e).__name__, e), file=sys.stderr)
        finally:
            try:
                os.remove(netlog)
            except OSError:
                pass
    return None, None


def _fetch(url):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    req = urllib.request.Request(
        url, headers={
            "User-Agent": UA,
            "Referer": config.FEDWATCH_PAGE_URL,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        })
    with opener.open(req, timeout=40) as r:
        return r.read().decode("utf-8", errors="ignore")


def _looks_valid(html):
    """页面是否为数据页（含概率数字表格）。"""
    return '<td class="number">' in html and "FedWatch Tool" in html


def parse(html):
    """解析 QuikStrike FedWatch 页面 → dict。"""
    meeting_rows = re.findall(
        r'<td class="center">(\d{1,2}) ([A-Za-z]{3}) (\d{4})</td>\s*'
        r'<td class="center">(ZQ\w+)</td>', html)
    meetings = []
    seen = set()
    for d, mon, y, _con in meeting_rows:
        key = "%04d-%02d-%02d" % (int(y), _MONTHS.get(mon[:3].lower(), 0), int(d))
        if key not in seen:
            seen.add(key)
            meetings.append(key)
    prob_rows = re.findall(
        r'<td class="number">([\d.]+)\s*%</td>\s*'
        r'<td class="number">([\d.]+)\s*%</td>\s*'
        r'<td class="number">([\d.]+)\s*%</td>', html)
    zone_rows = re.findall(
        r'<td class="center">(\d{3}-\d{3})\s*(\(Current\))?\s*</td>\s*'
        r'<td class="number highlight">([\d.]+)%</td>\s*'
        r'<td class="number">([\d.]+)%</td>\s*'
        r'<td class="number">([\d.]+)%</td>\s*'
        r'<td class="number">([\d.]+)%</td>', html)
    return {"meetings": meetings, "prob_rows": prob_rows, "zones": zone_rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--force-refresh", action="store_true")
    # 🔴 2026-11-04：**适配 CME 新接口的诊断开关** ✓
    ap.add_argument("--dump-urls", action="store_true",
                    help="从 netlog 里列出所有相关 URL（找 CME 新接口 ✗）")
    ap.add_argument("--keep-netlog", action="store_true",
                    help="保留 netlog 文件到 /tmp（8MB+ ✗ 用于离线分析 ✓）")
    args = ap.parse_args()

    # qsid 有效期短（分钟~小时级），默认每次先 headless 刷新；
    # 刷新失败回退上次成功会话（config 默认值兜底）
    insid, qsid = _refresh_session(debug=args.debug, keep_netlog=args.keep_netlog, dump_urls=args.dump_urls)
    if not insid:
        insid, qsid = _load_session()
        if args.debug:
            print("[fedwatch] 刷新失败，回退上次会话: %s/%s" % (insid, qsid))

    # 尝试抓取（最多刷新一次会话后重试）
    html = None
    attempts = 0
    while attempts < 2:
        if not insid or not qsid:
            insid, qsid = _refresh_session(debug=args.debug, keep_netlog=args.keep_netlog, dump_urls=args.dump_urls)
            if not insid:
                print("[fedwatch] 无法获取会话，退出（保留旧数据）")
                sys.exit(2)
        url = config.FEDWATCH_VIEW_URL % (insid, qsid)
        try:
            html = _fetch(url)
        except Exception as e:
            print("[fedwatch] 抓取异常: %s" % e)
            html = None
        if html and _looks_valid(html):
            _save_session(insid, qsid)
            break
        # 无效 → 强制刷新会话再试一次
        if attempts == 0:
            if args.debug:
                print("[fedwatch] 会话失效（%s），headless 刷新重试" % url)
            insid, qsid = None, None
        attempts += 1

    if not html or not _looks_valid(html):
        print("[fedwatch] 两次尝试均失败，退出（保留旧数据）")
        sys.exit(3)

    p = parse(html)
    if args.debug:
        print("会议:", p["meetings"][:5])
        print("E/H/H 组数:", len(p["prob_rows"]), p["prob_rows"][:3])
        print("目标区间行:", p["zones"])

    if not p["prob_rows"]:
        print("[fedwatch] 页面无概率数据（结构变化）")
        sys.exit(4)

    cur = None
    for e, h_, k in p["prob_rows"]:
        if float(h_) > 0 or float(k) > 0:
            cur = (float(e), float(h_), float(k))
            break
    if cur is None:
        print("[fedwatch] 无有效概率（全部 0）")
        sys.exit(5)
    ease, hold, hike = cur

    z_hold = z_hike = None
    z_wk_hold = z_wk_hike = z_m_hold = z_m_hike = None
    for lo_hi, is_cur, now_p, d1, wk, mo in p["zones"]:
        if is_cur:
            z_hold = float(now_p)
            z_wk_hold = float(wk)
            z_m_hold = float(mo)
        else:
            if z_hold is not None and z_hike is None and z_wk_hold is not None:
                z_hike = float(now_p)
                z_wk_hike = float(wk)
                z_m_hike = float(mo)

    meeting = p["meetings"][0] if p["meetings"] else "?"
    row = {
        "date": dt.date.today().isoformat(),
        "meeting": meeting,
        "ease_pct": round(ease, 1),
        "hold_pct": round(hold, 1),
        "hike_pct": round(hike, 1),
        "now_hold_pct": z_hold if z_hold is not None else round(hold, 1),
        "now_hike_pct": z_hike if z_hike is not None else round(hike, 1),
        "wk_hold_pct": z_wk_hold, "wk_hike_pct": z_wk_hike,
        "m_hold_pct": z_m_hold, "m_hike_pct": z_m_hike,
        "src": "cmefedwatch-quikstrike",
    }
    RAW.mkdir(parents=True, exist_ok=True)
    cols = list(row.keys())
    if OUT.exists():
        import csv
        with open(OUT, newline="") as f:
            old_rows = list(csv.DictReader(f))
        if old_rows and str(old_rows[-1]["date"]) == row["date"]:
            print("[fedwatch] 今日已有数据，跳过（%s）" % row["date"])
            return
    import csv
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if OUT.stat().st_size == 0:
            w.writeheader()
        w.writerow(row)
    print("[fedwatch] OK 会议 %s 维持 %.1f%% 加息 %.1f%% 降息 %.1f%%"
          % (meeting, hold, hike, ease))
    if z_wk_hike is not None:
        d = hike - z_wk_hike
        print("[fedwatch] 加息概率 vs 一周前: %+.1fpp" % d)


if __name__ == "__main__":
    main()
