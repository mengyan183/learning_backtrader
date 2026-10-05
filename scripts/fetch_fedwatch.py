#!/usr/bin/env python3
"""CME FedWatch 市场预期抓取（FOMC 加息/降息概率）。

数据源：CME FedWatch 工具（QuikStrike 内嵌页，服务端渲染 .aspx，无需 JS）。
- 页面本体（CME）对 curl 403，但 QuikStrikeView.aspx 带有效 qsid 可直连
- qsid 是 QuikStrike 会话 ID：从浏览器打开 CME FedWatch 页面获取
  （cmegroup-tools.quikstrike.net/User/QuikStrikeTools.aspx?...&qsid=xxx）
- qsid 过期（返回 302/403）时脚本只告警、不覆盖旧数据，提示刷新 config

用法:
  .venv/bin/python scripts/fetch_fedwatch.py          # 抓取并更新 Data/raw/fedwatch.csv
  .venv/bin/python scripts/fetch_fedwatch.py --debug   # 打印解析明细

输出: Data/raw/fedwatch.csv（追加行）
  date | meeting | ease_pct | hold_pct | hike_pct
  | now_hold_pct | now_hike_pct | wk_hold_pct | wk_hike_pct
  | m_hold_pct | m_hike_pct | src
（hold/hike = 市场对"维持/加息 25bp"的隐含概率，来自 30 天联邦基金期货）
"""
import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DATA = REPO / "Data"
RAW = DATA / "raw"
OUT = RAW / "fedwatch.csv"

import urllib.request

from fg_system import config

PROXY = "http://127.0.0.1:7890"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _fetch(url):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with opener.open(req, timeout=40) as r:
        return r.read().decode("utf-8", errors="ignore")


def parse(html):
    """解析 QuikStrike FedWatch 页面 → dict。"""
    # 会议列表：<td class="center">28 Oct 2026</td><td class="center">ZQV6</td>
    # （首个 td 是会议日期，第二个是 30 天联邦基金期货合约代码，据此排除 Expires 列）
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
    # 每场会议 Ease/NoChange/Hike 概率（<td class="number">x.x %</td> 三元组）
    prob_rows = re.findall(
        r'<td class="number">([\d.]+)\s*%</td>\s*'
        r'<td class="number">([\d.]+)\s*%</td>\s*'
        r'<td class="number">([\d.]+)\s*%</td>', html)
    # 目标区间分布（含 (Current) 标记）：375-400 (Current) 82.3% 77.9% 35.8% 54.4%
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
    args = ap.parse_args()

    qsid = config.FEDWATCH_QSID
    url = config.FEDWATCH_VIEW_URL % qsid
    try:
        html = _fetch(url)
    except Exception as e:
        print("[fedwatch] 抓取失败: %s" % e)
        print("[fedwatch] 提示：qsid 可能过期，用浏览器打开 CME FedWatch 页面"
              "复制新 qsid 更新 config.FEDWATCH_QSID")
        sys.exit(2)

    p = parse(html)
    if args.debug:
        print("会议:", p["meetings"][:5])
        print("E/H/H 组数:", len(p["prob_rows"]), p["prob_rows"][:3])
        print("目标区间行:", p["zones"])

    if not p["prob_rows"]:
        print("[fedwatch] 页面无概率数据（可能被反爬或结构变化）")
        sys.exit(3)

    # 最近会议 = 第一个非零概率组对应最近日期；用第一个有数据的组
    cur = None
    for e, h_, k in p["prob_rows"]:
        if float(h_) > 0 or float(k) > 0:
            cur = (float(e), float(h_), float(k))
            break
    if cur is None:
        print("[fedwatch] 无有效概率（全部 0）")
        sys.exit(4)
    ease, hold, hike = cur

    # 目标区间分布：找 (Current) 行 + 下一区间行
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
        df_old = _read_csv()
        # 同一天不重复追加（幂等）
        if df_old and str(df_old[-1]["date"]) == row["date"]:
            print("[fedwatch] 今日已有数据，跳过（%s）" % row["date"])
            return
    import csv
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if not OUT.exists() or OUT.stat().st_size == 0:
            w.writeheader()
        w.writerow(row)
    print("[fedwatch] OK 会议 %s 维持 %.1f%% 加息 %.1f%% 降息 %.1f%%"
          % (meeting, hold, hike, ease))
    if z_wk_hike is not None:
        d = hike - z_wk_hike
        print("[fedwatch] 加息概率 vs 一周前: %+.1fpp" % d)


_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _read_csv():
    import csv
    with open(OUT, newline="") as f:
        return list(csv.DictReader(f))


if __name__ == "__main__":
    main()
