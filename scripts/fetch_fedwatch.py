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


def _refresh_session(debug=False, retries=2):
    """headless Chrome 打开 CME FedWatch 页面 → netlog 提取最新 insid+qsid。
    返回 (insid, qsid)；失败返回 (None, None)。"""
    for attempt in range(retries + 1):
        _kill_stray_chrome()
        fd, netlog = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                   "--proxy-server=" + PROXY, "--user-agent=" + UA,
                   "--virtual-time-budget=20000",
                   "--log-net-log=" + netlog,
                   "--net-log-capture-mode=IncludeSensitive",
                   "--dump-dom", config.FEDWATCH_PAGE_URL]
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=150)
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
            if debug:
                print("[fedwatch] 刷新第 %d 次: netlog 无 View 请求" % (attempt + 1))
        except (subprocess.TimeoutExpired, OSError) as e:
            print("[fedwatch] 刷新异常(第 %d 次): %s" % (attempt + 1, e))
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
    args = ap.parse_args()

    # qsid 有效期短（分钟~小时级），默认每次先 headless 刷新；
    # 刷新失败回退上次成功会话（config 默认值兜底）
    insid, qsid = _refresh_session(debug=args.debug)
    if not insid:
        insid, qsid = _load_session()
        if args.debug:
            print("[fedwatch] 刷新失败，回退上次会话: %s/%s" % (insid, qsid))

    # 尝试抓取（最多刷新一次会话后重试）
    html = None
    attempts = 0
    while attempts < 2:
        if not insid or not qsid:
            insid, qsid = _refresh_session(debug=args.debug)
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
