#!/usr/bin/env python3
"""多智能体投研流水线原型 (E1)
Hermes(GLM 云端) 情绪/新闻分析 → Harness 后端模型(deepseek-v4.1-flash via NVIDIA NIM) 深度归因
→ OpenClaw(本地 qwen2.5-coder:3b) 裁判汇总 → 简报推送飞书(海外投资助手机器人)

用法:
  .venv/bin/python scripts/invest_research.py          # 全流程 + 推送飞书
  .venv/bin/python scripts/invest_research.py --dry-run  # 只产出简报不推送
说明:
  - 密钥全部从本机配置文件读取，源码树不出现任何密钥
  - NVIDIA NIM 走本地代理 7890（海外 API）
  - 任一阶段失败自动降级：缺 Hermes → 跳过情绪节；缺 NIM → 跳过归因节；缺 OpenClaw → 用本地快照替代
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DATA = REPO / "Data"

HERMES_URL = "http://127.0.0.1:8642/v1/chat/completions"
NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_MODEL = "deepseek-ai/deepseek-v4.1-flash"
PROXY = "http://127.0.0.1:7890"
FEISHU_OPEN_ID = "ou_c4f5cd25e5001a853309524e899dd6d2"


# ---------------------------------------------------------------- 凭据读取
def _read_hermes_key():
    import yaml
    cfg = yaml.safe_load(open(Path.home() / ".hermes" / "config.yaml"))
    return cfg.get("platforms", {}).get("api_server", {}).get("key")


def _read_nim_key():
    import yaml
    cred = yaml.safe_load(open(Path.home() / ".dsh" / ".credentials.yaml"))
    # 找 nvapi- 开头的 key（跨结构遍历）
    def walk(d):
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, str) and v.startswith("nvapi-"):
                    return v
                r = walk(v)
                if r:
                    return r
        elif isinstance(d, list):
            for v in d:
                r = walk(v)
                if r:
                    return r
        return None
    return walk(cred)


def _read_feishu_creds():
    cfg = json.load(open(Path.home() / ".openclaw" / "openclaw.json"))
    f = cfg.get("channels", {}).get("feishu", {})
    return f.get("appId"), f.get("appSecret")


# ---------------------------------------------------------------- 数据快照
def build_snapshot():
    import pandas as pd
    snap = {}

    # 持仓（最新日期）
    pos = pd.read_csv(DATA / "positions.csv", parse_dates=["date"])
    latest = pos["date"].max()
    pos_latest = pos[pos["date"] == latest]
    rows = []
    for _, r in pos_latest.iterrows():
        rows.append({
            "symbol": r["symbol"], "name": r["name"], "account": r["account"],
            "qty": float(r["qty"]), "cost": float(r["cost"]), "price": float(r["price"]),
            "mv": float(r["market_value"]),
        })
    snap["date"] = str(latest.date())
    snap["positions"] = rows

    # 最新收盘价（prices.csv）
    px = pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])
    last_px = px.sort_values("date").groupby("symbol").tail(1)
    price_map = dict(zip(last_px["symbol"], last_px["close"]))
    for r in rows:
        sym = r["symbol"].replace("-USDT", "")
        r["last_close"] = float(price_map[sym]) if sym in price_map else None
        r["pnl"] = round((r["last_close"] - r["cost"]) * r["qty"], 2) if r["last_close"] else None
        r["pnl_pct"] = round((r["last_close"] / r["cost"] - 1) * 100, 2) if r["last_close"] else None

    # 账户净值（最新）
    acc = pd.read_csv(DATA / "accounts.csv", parse_dates=["date"])
    acc_latest = acc[acc["date"] == acc["date"].max()]
    snap["accounts"] = {r["account"]: float(r["net_value"]) for _, r in acc_latest.iterrows()}

    # 系统贪恐指数（features.csv 最新有效行）
    feat = pd.read_csv(DATA / "features.csv", parse_dates=["date"])
    valid = feat.dropna(subset=["fg_index"])
    if len(valid):
        row = valid.iloc[-1]
        snap["fg"] = {
            "date": str(row["date"].date()), "fg_index": round(float(row["fg_index"]), 1),
            "zone": row["zone"], "target_position": row["target_position"],
            "drawdown": row["drawdown"], "circuit_breaker": bool(row["circuit_breaker"]),
        }
    else:
        snap["fg"] = None

    # 守猪待兔最新（各标的）
    st = pd.read_csv(DATA / "raw" / "shoutu_fng.csv", parse_dates=["date"])
    st_latest = st[st["date"] == st["date"].max()]
    snap["shoutu"] = {r["symbol"]: float(r["value"]) for _, r in st_latest.iterrows()}
    snap["shoutu_date"] = str(st_latest["date"].max().date()) if len(st_latest) else None
    return snap


def snapshot_text(snap):
    lines = [f"数据日期: {snap['date']}"]
    if snap.get("fg"):
        f = snap["fg"]
        lines.append(f"系统贪恐指数: {f['fg_index']} [{f['zone']}] 目标仓位: {f['target_position']} 回撤: {f['drawdown']} 熔断: {f['circuit_breaker']}")
    if snap.get("shoutu"):
        st = " ".join(f"{k}={v}" for k, v in snap["shoutu"].items())
        lines.append(f"守猪待兔({snap['shoutu_date']}): {st}")
    lines.append("持仓明细:")
    for r in snap["positions"]:
        pnl = f"浮盈亏{r['pnl']} ({r['pnl_pct']}%)" if r["pnl"] is not None else "无行情"
        lines.append(f"  {r['symbol']} {r['name']} qty={r['qty']} 成本={r['cost']} 现价={r['last_close']} {pnl} 市值={r['mv']}")
    lines.append(f"账户净值: {snap.get('accounts')}")
    return "\n".join(lines)


# ---------------------------------------------------------------- LLM 调用
def _chat(url, key, model, system, user, max_tokens=1200, proxy=None, timeout=120, retries=2):
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    if proxy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        opener = urllib.request.build_opener()
    last = None
    for i in range(retries):
        try:
            resp = json.loads(opener.open(req, timeout=timeout).read())
            msg = resp["choices"][0]["message"]
            # 推理模型：content 为空时回退 reasoning_content
            out = msg.get("content") or msg.get("reasoning_content") or ""
            if out.strip():
                return out
            last = "空响应"
        except Exception as e:
            last = e
            if i < retries - 1:
                import time
                time.sleep(8)
    raise RuntimeError(f"调用失败({retries}次): {last}")


def stage_sentiment(hermes_key, snap):
    """Hermes(GLM) 情绪/新闻面分析"""
    system = "你是资深美股情绪分析师。基于给定的市场数据快照，用中文输出≤500字的情绪面分析：市场整体情绪定性、仓位拥挤度、需要关注的新闻催化方向。只做分析，不给交易指令。"
    user = f"以下是今日市场快照：\n{snapshot_text(snap)}\n\n请输出情绪面分析。"
    return _chat(HERMES_URL, hermes_key, "hermes-agent", system, user, max_tokens=800)


def stage_attribution(nim_key, snap):
    """Harness 后端模型(deepseek-v4.1-flash via NVIDIA NIM) 深度归因"""
    system = "你是量化交易系统的深度归因分析师。基于持仓与盈亏数据，用中文输出结构化归因（≤800字）：逐标的归因（为什么涨/跌、驱动因素）、组合风险点、仓位合理性。只做归因分析，不给交易指令。直接输出最终分析正文，不要输出思考过程。"
    user = f"以下是今日持仓快照：\n{snapshot_text(snap)}\n\n请输出深度归因分析。"
    return _chat(NIM_URL, nim_key, NIM_MODEL, system, user, max_tokens=4096, proxy=PROXY, timeout=300, retries=2)


def stage_judge(snap, sentiment, attribution):
    """OpenClaw(本地 qwen2.5-coder:3b) 裁判汇总——prompt 压缩，输出纯文本短裁决"""
    # 压缩快照：只保留关键行，避免本地小模型上下文过长
    lines = [f"系统贪恐指数 {snap['fg']['fg_index']} [{snap['fg']['zone']}] 目标仓位 {snap['fg']['target_position']} 回撤 {snap['fg']['drawdown']}"]
    if snap.get("shoutu"):
        lines.append("守猪待兔: " + " ".join(f"{k}={v}" for k, v in snap["shoutu"].items()))
    for r in snap["positions"]:
        lines.append(f"{r['symbol']} 盈亏{r['pnl_pct']}%")
    compact = "\n".join(lines)
    # 报告截断到各 600 字
    sent_short = (sentiment or "（无）")[:600]
    attr_short = (attribution or "（无）")[:600]
    prompt = (
        "你是投研裁判。数据:\n" + compact + "\n\n"
        "情绪分析:\n" + sent_short + "\n\n"
        "归因分析:\n" + attr_short + "\n\n"
        "输出三行纯文本(不要json/代码块):\n"
        "评级: (强烈减仓|减仓|持有|加仓|强烈加仓)\n"
        "理由: (1-2句)\n"
        "风险: (1条)"
    )
    try:
        r = subprocess.run(
            ["openclaw", "agent", "exec", "--model", "ollama/qwen2.5-coder:3b", prompt],
            capture_output=True, text=True, timeout=420,
        )
        out = (r.stdout or "") + (r.stderr or "")
        # 去掉 ANSI 转义与横幅/日志行，提取实际回答
        import re
        clean = re.sub(r"\x1b\[[0-9;]*m", "", out)
        body_lines = []
        for line in clean.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith(("│", "◇", "🦞", "OpenClaw", "Config", "A Gateway", "gate", "[plugins", "[skills", "[state", "[session", "[agents", "[agent", "[tool", "Retrying", "Experimental", "(node", "(Use", "node:")):
                continue
            if re.match(r"^\d{2}:\d{2}:\d{2}", s):
                continue
            body_lines.append(s)
        if not body_lines:
            return "裁判输出为空（本地小模型对长输入不稳定），建议以归因结论为准。"
        return "\n".join(body_lines)[-800:]
    except subprocess.TimeoutExpired:
        return "裁判超时(本地3b模型较慢)，本次由归因结论直接驱动评级。"


# ---------------------------------------------------------------- 新闻抓取（Google News RSS，免 key）
def _rss_titles(url, limit, timeout=20):
    """拉取 RSS 返回标题列表；失败返回 []。"""
    import xml.etree.ElementTree as ET
    import html
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    opener.addheaders = [("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")]
    try:
        data = opener.open(url, timeout=timeout).read().decode("utf-8", "ignore")
        root = ET.fromstring(data)
        titles = []
        for item in root.iter("item"):
            t = item.findtext("title")
            if t:
                t = html.unescape(t).strip()
                if t and t not in titles:
                    titles.append(t)
            if len(titles) >= limit:
                break
        return titles
    except Exception:
        return []


def fetch_news(snap):
    """大盘 + 持仓标的相关新闻。
    主源: 富途 OpenAPI GetSearchNews(本地 OpenD, 中文资讯, 无需代理)
    兜底: Google News RSS(免 key, 走 7890 代理)。全部失败时为空 dict。"""
    out = {}
    # --- 富途主源 ---
    try:
        from futu import OpenQuoteContext
        q = OpenQuoteContext(host="127.0.0.1", port=11111)
        mkt_ret, mkt = q.get_search_news("US stock market", max_count=3)
        if mkt_ret == 0 and len(mkt):
            out["_market"] = [str(t).strip() for t in mkt["title"].tolist()[:3]]
        for r in snap["positions"]:
            sym = r["symbol"].replace("-USDT", "")
            kw = {"BTC": "比特币", "ETH": "以太坊"}.get(sym, sym)
            ret, data = q.get_search_news(kw, max_count=2)
            if ret == 0 and len(data):
                out[sym] = [str(t).strip() for t in data["title"].tolist()[:2]]
        q.close()
    except Exception as e:
        print("富途新闻源不可用:", e)

    # --- Google News 兜底（补富途缺失的区） ---
    gnews = {}
    if not out.get("_market"):
        t = _rss_titles("https://news.google.com/rss/search?q=US+stock+market+today&hl=en-US&gl=US&ceid=US:en", 3)
        if t:
            gnews["_market"] = t
    for r in snap["positions"]:
        sym = r["symbol"].replace("-USDT", "")
        if sym in out:
            continue
        q = {"BTC": "bitcoin price", "ETH": "ethereum price"}.get(sym, f"{sym} stock")
        t = _rss_titles(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en", 2)
        if t:
            gnews[sym] = t
    # 富途完全失败时整体用 gnews；否则仅补缺失
    if not out:
        out = gnews
    else:
        for k, v in gnews.items():
            out.setdefault(k, v)
    return out


def news_text(news):
    """简报用新闻文本：市场区 + 标的分区。"""
    if not news:
        return "（新闻源不可用或为空）"
    lines = []
    if news.get("_market"):
        lines.append("大盘快讯:")
        for t in news["_market"][:3]:
            lines.append(f"· {t[:90]}")
    for sym, titles in news.items():
        if sym == "_market":
            continue
        lines.append(f"{sym}:")
        for t in titles[:2]:
            lines.append(f"· {t[:80]}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 简报与推送
def build_snapshot_lines(snap):
    """简报用紧凑快照行（区别于喂给 LLM 的完整 snapshot_text）。"""
    out = []
    if snap.get("fg"):
        f = snap["fg"]
        out.append(f"系统贪恐指数 {f['fg_index']} [{f['zone']}] · 目标仓位 {f['target_position']} · 回撤 {f['drawdown']:.2%} · 熔断{'已触发' if f['circuit_breaker'] else '未触发'}")
    if snap.get("shoutu"):
        pairs = " / ".join(f"{k} {v}" for k, v in list(snap["shoutu"].items())[:6])
        out.append(f"守猪待兔({snap['shoutu_date']}): {pairs}")
    out.append("持仓:")
    for r in snap["positions"]:
        pnl = f"{r['pnl']} ({r['pnl_pct']}%)" if r["pnl"] is not None else "无行情"
        flag = "🔺" if (r["pnl"] or 0) > 0 else ("🔻" if (r["pnl"] or 0) < 0 else "▪️")
        out.append(f"{flag} {r['symbol']} {r['name']} · 成本 {r['cost']} · 现价 {r['last_close'] or '—'} · 浮盈亏 {pnl}")
    out.append(f"账户净值: " + " / ".join(f"{k} {v}" for k, v in (snap.get('accounts') or {}).items()))
    return "\n".join(out)


def build_brief_sections(snap, sentiment, attribution, judge, news=None):
    """结构化简报（飞书富文本 post 用）：[ ("标题", "正文"), "hr", ... ]"""
    secs = []
    secs.append(("市场快照", build_snapshot_lines(snap)))
    secs.append("hr")
    secs.append(("📰 市场快讯", news_text(news) if news else "（新闻源不可用）"))
    secs.append("hr")
    secs.append(("📰 情绪面 · Hermes(GLM)", (sentiment or "（不可用）").strip()[:300]))
    secs.append("hr")
    secs.append(("🔍 深度归因 · DeepSeek(NVIDIA NIM)", (attribution or "（不可用）").strip()[:300]))
    secs.append("hr")
    secs.append(("⚖️ 裁判裁决 · OpenClaw(本地)", (judge or "（不可用）").strip()[:300]))
    return secs


def build_brief(snap, sentiment, attribution, judge, news=None):
    lines = [
        f"# 多智能体投研简报 {snap['date']}",
        "",
        "## 市场快照",
        "```",
        build_snapshot_lines(snap),
        "```",
        "",
        "## 市场快讯",
        news_text(news) if news else "（新闻源不可用）",
        "",
        "## 情绪面分析（Hermes / GLM）",
        (sentiment or "（跳过：Hermes 不可用）").strip()[:300],
        "",
        "## 深度归因（Harness 后端 deepseek-v4.1-flash / NVIDIA NIM）",
        (attribution or "（跳过：NIM 不可用）").strip()[:300],
        "",
        "## 裁判裁决（OpenClaw / 本地 qwen2.5-coder:3b）",
        (judge or "（跳过：OpenClaw 不可用）").strip()[:300],
        "",
        "> 由 scripts/invest_research.py 自动生成 · 仅供个人研究，不构成投资建议",
    ]
    return "\n".join(lines)


def push_feishu(text):
    return _send_feishu("text", {"text": text})


def push_feishu_rich(title, sections):
    """飞书富文本 post：标题 + 分区（加粗标题行 / 分隔行 / 正文行）。
    post 消息仅支持 text/a/at/img 元素（不支持 hr），用分隔文本行代替。"""
    content = []
    for sec in sections:
        if sec == "hr":
            content.append([{"tag": "text", "text": "——————" * 4}])
            continue
        head, body = sec
        content.append([{"tag": "text", "text": head, "style": ["bold"]}])
        for line in (body or "").splitlines():
            if line.strip():
                content.append([{"tag": "text", "text": line.strip()}])
    payload = {"post": {"zh_cn": {"title": title, "content": content}}}
    return _send_feishu("post", payload)


def _send_feishu(msg_type, content_obj):
    app_id, app_secret = _read_feishu_creds()
    token_req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    token = json.loads(urllib.request.urlopen(token_req, timeout=15).read())["tenant_access_token"]
    msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {"receive_id": FEISHU_OPEN_ID, "msg_type": msg_type,
            "content": json.dumps(content_obj, ensure_ascii=False)}
    msg_req = urllib.request.Request(
        msg_url, data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(msg_req, timeout=15).read())
    return resp.get("code") == 0, resp.get("msg", resp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只产出简报不推送飞书")
    args = ap.parse_args()

    snap = build_snapshot()
    brief_path = REPO / "Data" / f"invest_brief_{snap['date']}.md"

    sentiment = attribution = judge = None
    news = None
    try:
        news = fetch_news(snap)
    except Exception as e:
        print("新闻抓取失败:", e)
    try:
        sentiment = stage_sentiment(_read_hermes_key(), snap)
    except Exception as e:
        print("Hermes 阶段失败:", e)
    try:
        attribution = stage_attribution(_read_nim_key(), snap)
    except Exception as e:
        print("NIM 阶段失败:", e)
    try:
        judge = stage_judge(snap, sentiment or "（无）", attribution or "（无）")
    except Exception as e:
        print("OpenClaw 阶段失败:", e)

    brief = build_brief(snap, sentiment, attribution, judge, news)
    brief_path.write_text(brief, encoding="utf-8")
    print(f"简报已写入: {brief_path}")

    if args.dry_run:
        print(brief[:500])
        return
    if not (sentiment and attribution and judge):
        print("存在缺失阶段，跳过飞书推送（dry-run 模式已可查看简报）")
        return
    ok, msg = push_feishu_rich(f"📊 多智能体投研简报 {snap['date']}",
                               build_brief_sections(snap, sentiment, attribution, judge, news))
    print(f"飞书富文本推送: {'成功' if ok else f'失败 {msg}'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
