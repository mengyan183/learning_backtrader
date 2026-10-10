#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-7 新闻情绪信号接入（NewsAPI 免费档，100 请求/天）。

- 数据源：https://newsapi.org/v2/everything（官方 REST，API key 存 Data/newsapi_key）
- 覆盖：大盘（stock market / wall street）、加密（bitcoin / ethereum / crypto）、
  持仓标的（positions.csv 最新快照 symbols → 关键词映射）
- 情感打分：确定性英文正负词表（标题+描述计数），无 LLM、可审计
- 输出：Data/raw/news_sentiment.csv —— date, mkt_total, mkt_pos, mkt_neg, mkt_score,
  crypto_total, crypto_pos, crypto_neg, crypto_score, syms_hit（今日有新闻的标的，| 分隔）
- 增量：同一天已存在则整行更新；不重复追加
- 网络：国内直连失败时自动走本地代理 127.0.0.1:7890（与既有脚本一致）

用法：.venv/bin/python scripts/fetch_news.py
信号分级：🟡 研究参考（新闻情绪为 E1 情绪子信号候选，未经回测裁判，不直接进合成权重）
"""

import csv
import json
import os
import re
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "Data", "raw")
OUT = os.path.join(RAW, "news_sentiment.csv")
KEY_FILE = os.path.join(REPO, "Data", "newsapi_key")
PROXY = "http://127.0.0.1:7890"

API = "https://newsapi.org/v2/everything"
POS_WORDS = [
    "rally", "surge", "gain", "record", "beat", "jump", "bull", "outperform",
    "rebound", "strong", "profit", "soar", "advance", "rise", "growth",
    "upbeat", "breakthrough", "upgrade", "win", "best", "high", "hopes", "boost",
]
NEG_WORDS = [
    "plunge", "drop", "fall", "slump", "loss", "crash", "bear", "miss", "down",
    "decline", "weak", "fear", "selloff", "tumble", "worry", "retreat", "cut",
    "warning", "risk", "worst", "low", "downgrade", "doubt", "concern", "hit",
]

# 持仓 symbol → 新闻关键词（其余 symbol 直接查其代码本身）
SYM_KEYWORDS = {
    "BTC-USDT": "bitcoin",
    "ETH-USDT": "ethereum",
    "BTC": "bitcoin",
    "ETH": "ethereum",
}


def read_key():
    """key 优先取环境变量 `NEWSAPI_KEY`，其次 `Data/newsapi_key`。

    R-6（WT-12 审查）：key 进 URL query string 是 NewsAPI 官方约束（改不了
    header），但**来源**不该只有文件一个 —— env 注入便于临时/CI 运行，且与
    `fg_system/data/shoutu.py::load_token` 的既有约定一致（env 优先、文件兜底）。
    """
    env = os.environ.get("NEWSAPI_KEY", "").strip()
    if env:
        return env
    if not os.path.exists(KEY_FILE):
        sys.exit("NEWSAPI_KEY 未设且 Data/newsapi_key 不存在："
                 "请申请 NewsAPI key 后写入环境变量或该文件")
    with open(KEY_FILE, encoding="utf-8") as f:
        return f.read().strip()


def _urlopen(url):
    try:
        return urllib.request.urlopen(url, timeout=20)
    except Exception:
        proxy = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
        opener = urllib.request.build_opener(proxy)
        return opener.open(url, timeout=25)


def fetch(q, page_size=8, key=""):
    url = f"{API}?q={urllib.parse.quote(q)}&language=en&sortBy=publishedAt&pageSize={page_size}&apiKey={key}"
    last = None
    for attempt in (1, 2):
        try:
            with _urlopen(url) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("status") != "ok":
                print(f"  NewsAPI {q!r} 失败: {d.get('message')}")
                return []
            return d.get("articles", [])
        except Exception as e:
            last = e
            continue
    print(f"  NewsAPI {q!r} 重试后仍失败: {last}")
    return []


def score(articles):
    total, pos, neg = 0, 0, 0
    for a in articles:
        text = f"{a.get('title') or ''} {a.get('description') or ''}".lower()
        if not text.strip():
            continue
        total += 1
        pos += sum(1 for w in POS_WORDS if re.search(r"\b" + w + r"\b", text))
        neg += sum(1 for w in NEG_WORDS if re.search(r"\b" + w + r"\b", text))
    net = pos - neg
    score_val = net / max(total, 1)
    return total, pos, neg, round(score_val, 3)


def main():
    import urllib.parse
    key = read_key()
    print(f"=== B-7 新闻情绪抓取（{__import__('datetime').date.today()}）===")

    mkt = fetch('"stock market" OR "wall street" OR "s&p 500"', 8, key)
    mt, mp, mn, ms = score(mkt)
    print(f"  大盘: {mt} 条, 正 {mp} / 负 {mn}, score={ms}")

    crypto = fetch("bitcoin OR ethereum OR crypto", 8, key)
    ct, cp, cn, cs = score(crypto)
    print(f"  加密: {ct} 条, 正 {cp} / 负 {cn}, score={cs}")

    # 持仓标的
    syms_hit = []
    pos_file = os.path.join(REPO, "Data", "positions.csv")
    syms = []
    if os.path.exists(pos_file):
        with open(pos_file, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                s = r.get("symbol")
                if s and s not in syms:
                    syms.append(s)
    for s in syms:
        kw = SYM_KEYWORDS.get(s, s)
        arts = fetch(kw, 3, key)
        if arts:
            syms_hit.append(f"{s}({len(arts)})")
    print(f"  标的新闻: {len(syms_hit)} 只  → {', '.join(syms_hit) if syms_hit else '无'}")

    today = __import__("datetime").date.today().isoformat()
    row = {
        "date": today, "mkt_total": mt, "mkt_pos": mp, "mkt_neg": mn, "mkt_score": ms,
        "crypto_total": ct, "crypto_pos": cp, "crypto_neg": cn, "crypto_score": cs,
        "syms_hit": "|".join(syms_hit),
    }
    cols = ["date", "mkt_total", "mkt_pos", "mkt_neg", "mkt_score",
            "crypto_total", "crypto_pos", "crypto_neg", "crypto_score", "syms_hit"]

    rows = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("date") != today:
                    rows.append(r)
    rows.append(row)
    rows.sort(key=lambda r: r["date"])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"  → {OUT}（{len(rows)} 行，最新 {today} mkt_score={ms} crypto_score={cs}）")


if __name__ == "__main__":
    main()
