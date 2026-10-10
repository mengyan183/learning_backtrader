#!/usr/bin/env python3
"""多智能体投研流水线原型 (E1)
Hermes(GLM 云端) 情绪/新闻分析 → NVIDIA NIM(deepseek-v4.1-flash) 深度归因
→ 裁判裁决(NVIDIA NIM 云端；弃用本地小模型——3b 倾向输出 tool_call JSON) → 简报推送飞书
BTC 持仓现价回退源：OKX REST(走 7890 代理)；FG_STATIC_ONLY=1 时跳过外部行情。

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
sys.path.insert(0, str(REPO / "scripts"))
DATA = REPO / "Data"

HERMES_URL = "http://127.0.0.1:8642/v1/chat/completions"
NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_MODEL = "deepseek-ai/deepseek-v4.1-flash"
PROXY = "http://127.0.0.1:7890"
FEISHU_OPEN_ID = "ou_c4f5cd25e5001a853309524e899dd6d2"
OKX_TICKER_URL = "https://www.okx.com/api/v5/market/ticker?instId={sym}"
# 公司电脑只跑静态数据时置 1，禁止任何外部行情 API（富途/OKX）
STATIC_ONLY = os.environ.get("FG_STATIC_ONLY", "0") == "1"


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


def _okx_ticker(sym):
    """OKX 实时价回退源（BTC 无美股收盘价时用）。走 7890 代理；
    静态模式或调用失败返回 None（不阻塞简报）。"""
    if STATIC_ONLY:
        return None
    try:
        inst_id = sym if sym.endswith("-USDT") else f"{sym}-USDT"
        url = OKX_TICKER_URL.format(sym=inst_id)
        req = urllib.request.Request(url, headers={"User-Agent": "fg-brief/1.0"})
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
        d = json.loads(opener.open(req, timeout=15).read())
        data = (d.get("data") or [{}])[0]
        last = data.get("last")
        open24 = data.get("open24h")
        out = {"price": float(last)} if last else None
        if out and open24 and float(open24):
            out["day_chg_pct"] = round((float(last) / float(open24) - 1) * 100, 2)
        return out
    except Exception as e:
        # G-4（WT-12 审查）：降级设计保留（返回 None），但**不得静默** ——
        # "调用失败"与"合法空结果"压成同一个 None 会让排障无从下手。
        print("[okx_ticker] 取价失败（按无数据处理）: %s" % e, file=sys.stderr)
        return None


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

    # 统一价格源（修复"持仓段/归因段双价格"问题，2026-10-07）：
    #   优先级：① realtime_state.json 实时价（仅 BTC 使用，OKX 常驻更新）
    #           ② positions.csv 快照价（美股标的：05:30 实时快照，与 qty/cost 同源同刻）
    #           ③ prices.csv 最新收盘价（fallback）
    # 选定后 **mv / pnl / pnl_pct 全部按该价重算**，保证同一简报内自洽。
    rt_prices = {}
    try:
        with open(DATA / "realtime_state.json", encoding="utf-8") as _f:
            rt_prices = json.load(_f).get("prices") or {}
    except Exception:
        rt_prices = {}

    px = pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])
    last_px = px.sort_values("date").groupby("symbol").tail(1)
    price_map = dict(zip(last_px["symbol"], last_px["close"]))
    for r in rows:
        sym = r["symbol"].replace("-USDT", "")
        if sym == "BTC":
            # 加密仓优先 OKX 实时价（realtime_state 由常驻服务更新，source=OKX）
            _rt = rt_prices.get("BTC") or {}
            if _rt.get("price"):
                r["last_close"] = float(_rt["price"])
                r["px_source"] = "OKX实时"
            else:
                r["last_close"] = float(r["price"])
                r["px_source"] = "positions快照"
        elif r["price"]:
            # 美股标的：positions 快照价（与 qty/cost 同源同刻，简报自洽优先）
            r["last_close"] = float(r["price"])
            r["px_source"] = "positions快照"
        elif sym in price_map:
            r["last_close"] = float(price_map[sym])
            r["px_source"] = "prices.csv"
        else:
            r["last_close"] = None
            r["px_source"] = None
        # 统一口径：市值与浮盈按同一价格重算（positions 原 market_value 不再混用）
        if r["last_close"]:
            r["mv"] = round(r["last_close"] * r["qty"], 2)
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

    # P1 风控仓位（1% 风险规则：建议市值上限 = 净值×1% / 2×ATR20。
    # 规则来源：知识库 RaynerTeo《The Math Behind Profitable Trading》）
    stock_net = snap["accounts"].get("stock")
    sys.path.insert(0, str(REPO))
    from fg_system import risk as risk_mod
    for r in rows:
        sym0 = r["symbol"].replace("-USDT", "")
        px_now = r.get("last_close")
        mv0 = r["mv"]
        if stock_net and px_now and mv0:
            atrp = risk_mod.atr_pct(px, sym0, px_now)
            lim, _ratio = risk_mod.position_limit(stock_net, mv0, atrp)
            r["risk_limit"] = round(lim, 2) if lim else None
            r["risk_over"] = bool(lim and mv0 > lim)
        else:
            r["risk_limit"] = None
            r["risk_over"] = False

    # 系统个股系数（路径B：mom60/mom20/vol20 三因子；数据不足回退市场级）。
    # 供「减仓操作双引擎」使用：引擎A=价格风控、引擎B=贪恐系数方向信号。
    try:
        from fg_system.factors import symbol as sym_mod
        market_fg = (snap["fg"] or {}).get("fg_index")
        for r in rows:
            s = r["symbol"].replace("-USDT", "")
            s_fg = sym_mod.symbol_fg_index(s, prices=px)
            if s_fg is None or s_fg.dropna().empty:
                r["sys_fg"] = round(float(market_fg), 1) if market_fg else None
                r["sys_fg_note"] = "回退市场级"
            else:
                r["sys_fg"] = round(float(s_fg.dropna().iloc[-1]), 1)
                r["sys_fg_note"] = "个股级"
    except Exception:
        for r in rows:
            r["sys_fg"] = None
            r["sys_fg_note"] = "不可用"

    # 连亏 kill switch：当日亏损 ≥2% 净值 → 提示收工（知识库：Peter Brandt 风控）
    snap["kill_switch"] = None
    _dp = acc_latest["day_pnl"].dropna()
    if len(_dp) and stock_net:
        _day_pnl = float(_dp.iloc[-1])
        if _day_pnl <= -0.02 * stock_net:
            snap["kill_switch"] = {
                "day_pnl": round(_day_pnl, 2),
                "pct": round(_day_pnl / stock_net * 100.0, 2),
            }
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


# ---------------------------------------------------------------- LLM 输出校验与降级（2026-10-07 修复）
# 背景：NIM 云端 deepseek 在长 prompt 下偶发「prompt 回显 / 思考过程当作正文」，
# 导致简报出现 "We need answer in Chinese..."、"Hmm if crypto NAV includes BTC?" 等脏内容。
# 修复策略：**校验失败即降级**，宁可显示"生成失败"也不污染简报。

_PREAMBLE_HITS = ["we need answer", "我们需要回答用户", "你的全部输出只能是",
                  "请直接输出", "以下是今日", "直接输出最终分析正文",
                  "你是量化交易系统", "你是投研裁判"]
_THINKING_HITS = ["need calculate", "hmm if", "let's sum", "need infer",
                  "need interpret", "maybe scores", "need attribute",
                  "need calculate exposures", "need not give instructions"]


def _clean_attribution(text):
    """归因输出清洗：命中 prompt 回显/思考特征 → 返回 None（降级）。"""
    if not text or len(text.strip()) < 80:
        return None
    t = text.strip()
    low = t.lower()
    if any(m in low for m in _PREAMBLE_HITS) or any(m in low for m in _THINKING_HITS):
        return None
    return t


def _validate_judge(text):
    """裁判输出校验：必须为三行格式（评级: …/理由: …/风险: …）。不匹配 → None。"""
    import re
    if not text:
        return None
    t = text.strip().replace("\n\n", "\n")
    if not re.search(r"评级\s*[:：]\s*(强烈减仓|减仓|持有|加仓|强烈加仓)", t):
        return None
    if "理由" not in t or "风险" not in t:
        return None
    return t[:800]


def stage_attribution(nim_key, snap):
    """Harness 后端模型(deepseek-v4.1-flash via NVIDIA NIM) 深度归因"""
    system = "你是量化交易系统的深度归因分析师。基于持仓与盈亏数据，用中文输出结构化归因（≤800字）：逐标的归因（为什么涨/跌、驱动因素）、组合风险点、仓位合理性。只做归因分析，不给交易指令。直接输出最终分析正文，不要输出思考过程。"
    user = f"以下是今日持仓快照：\n{snapshot_text(snap)}\n\n请输出深度归因分析。"
    try:
        out = _chat(NIM_URL, nim_key, NIM_MODEL, system, user,
                    max_tokens=4096, proxy=PROXY, timeout=300, retries=2)
        clean = _clean_attribution(out)
        if clean is None:
            # 疑似 prompt 回显/思考 → 重试一次（NIM 偶发）
            out = _chat(NIM_URL, nim_key, NIM_MODEL, system, user,
                        max_tokens=4096, proxy=PROXY, timeout=300, retries=1)
            clean = _clean_attribution(out)
        return clean
    except Exception as e:
        # G-4：LLM 失败与"输出被清洗判定为空"原本不可区分 ⇒ 记一行原因。
        print("[stage_attribution] 归因失败（按无数据处理）: %s" % e,
              file=sys.stderr)
        return None


def stage_judge(nim_key, snap, sentiment, attribution):
    """裁判汇总——NVIDIA NIM(deepseek-v4.1-flash) 云端裁决。
    历史教训：本地 qwen2.5-coder:3b 在裁判任务上倾向输出
    tool_call/sessions_yield 等 JSON 工具格式而非纯文本裁决，
    已弃用本地模型，统一走 NIM 云端（与深度归因同通道）。
    2026-10-07 加固：**校验三行格式，不匹配重试一次，仍失败则降级提示**。"""
    # 压缩快照：只保留关键行，控制输入长度
    lines = [f"系统贪恐指数 {snap['fg']['fg_index']} [{snap['fg']['zone']}] 目标仓位 {snap['fg']['target_position']} 回撤 {snap['fg']['drawdown']}"]
    if snap.get("shoutu"):
        lines.append("守猪待兔: " + " ".join(f"{k}={v}" for k, v in snap["shoutu"].items()))
    for r in snap["positions"]:
        lines.append(f"{r['symbol']} 盈亏{r['pnl_pct']}%")
    compact = "\n".join(lines)
    # 报告截断到各 600 字
    sent_short = (sentiment or "（无）")[:600]
    attr_short = (attribution or "（无）")[:600]
    system = ("你是投研裁判。你的全部输出只能是如下三行纯文本，"
              "禁止输出JSON、代码块、Markdown标记或任何工具调用格式：\n"
              "评级: (强烈减仓|减仓|持有|加仓|强烈加仓)\n"
              "理由: (1-2句)\n"
              "风险: (1条)")
    user = (f"数据:\n{compact}\n\n情绪分析:\n{sent_short}\n\n归因分析:\n{attr_short}\n\n"
            "请直接输出三行裁决文本。")
    try:
        out = _chat(NIM_URL, nim_key, NIM_MODEL, system, user,
                    max_tokens=400, proxy=PROXY, timeout=180, retries=1)
        v = _validate_judge(out)
        if v is None:
            out = _chat(NIM_URL, nim_key, NIM_MODEL, system, user,
                        max_tokens=400, proxy=PROXY, timeout=180, retries=1)
            v = _validate_judge(out)
        if v is None:
            return "（裁判未按三行格式输出，本次以归因/风控结论为准。）"
        return v
    except Exception as e:
        return f"裁判调用失败（NIM）：{e}，本次以归因结论为准。"


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
    except Exception as e:
        # G-4：RSS 取不到标题是**可接受的降级**，但静默会让"源挂了"看起来
        # 像"今天没新闻"。
        print("[_rss_titles] 取标题失败（按空列表处理）: %s" % e, file=sys.stderr)
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
            lines.append(f"· {t[:150]}")
    for sym, titles in news.items():
        if sym == "_market":
            continue
        lines.append(f"{sym}:")
        for t in titles[:2]:
            lines.append(f"· {t[:120]}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 简报与推送
def build_snapshot_lines(snap):
    """简报用紧凑快照行（区别于喂给 LLM 的完整 snapshot_text）。"""
    out = []
    if snap.get("fg"):
        f = snap["fg"]
        out.append(f"系统贪恐指数 {f['fg_index']} [{f['zone']}] · 目标仓位 {f['target_position']} · 回撤 {f['drawdown']:.2%} · 熔断{'已触发' if f['circuit_breaker'] else '未触发'}")
    if snap.get("shoutu"):
        # 全量展示（修复 2026-10-07 审查发现的 [:6] 静默截断：UPRO/YINN 被隐藏）
        items = list(snap["shoutu"].items())
        pairs = " / ".join(f"{k} {v}" for k, v in items[:8])
        if len(items) > 8:
            pairs += " …"  # 超过 8 个标的时显式标注省略
        out.append(f"守猪待兔({snap['shoutu_date']}): {pairs}")
    out.append("持仓:")
    for r in snap["positions"]:
        pnl = f"{r['pnl']} ({r['pnl_pct']}%)" if r["pnl"] is not None else "无行情"
        flag = "🔺" if (r["pnl"] or 0) > 0 else ("🔻" if (r["pnl"] or 0) < 0 else "▪️")
        out.append(f"{flag} {r['symbol']} {r['name']} · 成本 {r['cost']} · 现价 {r['last_close'] or '—'} · 浮盈亏 {pnl}")
    out.append(f"账户净值: " + " / ".join(f"{k} {v}" for k, v in (snap.get('accounts') or {}).items()))
    return "\n".join(out)


def risk_brief_text(snap):
    """P1 风控仓位节（简报）：逐标的风险上限 + 连亏 kill switch。

    1% 风险规则：建议市值上限 = 账户净值×1% / (2×ATR20)。
    知识库来源：RaynerTeo《Math Behind》/ Peter Brandt 风控。
    """
    lines = []
    for r in snap.get("positions", []):
        sym = r["symbol"]
        if r.get("risk_limit"):
            if r["risk_over"]:
                lines.append("⚠ %s 市值 %.0f > 1%%风险上限 %.0f：建议减仓"
                             % (sym, r["mv"], r["risk_limit"]))
            else:
                lines.append("✓ %s 未超 1%%风险上限（%.0f）"
                             % (sym, r["risk_limit"]))
    ks = snap.get("kill_switch")
    if ks:
        lines.append("🔴 连亏保护触发：当日亏损 %s (%.1f%%) ≥ 2%%净值，"
                     "建议停止开新仓/当日收工（Peter Brandt 风控）"
                     % (ks["day_pnl"], ks["pct"]))
    return "\n".join(lines) if lines else None


def action_brief_text(snap):
    """📉 减仓操作双引擎（2026-10-07 落地，回答"按系数还是按价格减仓"）。

    - 引擎A · 价格风控（P1 1% 风险规则）：**硬敞口**。市值 > 1%风险上限
      ⇒ 必须减仓到上限（无论系数如何），保护单笔风险 ≤ 净值 1%。
    - 引擎B · 贪恐系数（系统个股系数 + 守猪待兔系数档位）：**方向信号**。
      决定买卖时机，不单独触发强制减仓。
    - 动作矩阵：
        A触发 & B贪婪(≥卖出线)   → 减仓（双触发，优先级最高）
        A触发 & B非贪婪           → 减仓至上限（仅降敞口，不追方向）
        A未触发 & B恐慌(≤买入线)  → 持有/可加（恐慌买入区且敞口合规）
        其余                      → 持有观望
    """
    from fg_system.config import shoutu_lines
    _ZONE_TXT = {0: "极恐", 1: "恐惧", 2: "中性", 3: "贪婪", 4: "极贪"}
    out = []
    for r in snap.get("positions", []):
        sym = r["symbol"]
        sym0 = sym.replace("-USDT", "")
        mv = r.get("mv"); lim = r.get("risk_limit")
        over = bool(r.get("risk_over"))
        # 守猪待兔系数与档位（引擎B 之一）
        st_val = (snap.get("shoutu") or {}).get(sym0)
        buy_line, sell_line = shoutu_lines(sym0)
        if st_val is None:
            st_desc = "守猪待兔:无系数"
        elif st_val <= buy_line:
            st_desc = "守猪待兔:%.0f 恐慌(买入区≤%.0f)" % (st_val, buy_line)
        elif st_val >= sell_line:
            st_desc = "守猪待兔:%.0f 贪婪(卖出线≥%.0f)" % (st_val, sell_line)
        else:
            st_desc = "守猪待兔:%.0f 中性" % st_val
        # 系统个股系数档位（引擎B 之二）
        sys_fg = r.get("sys_fg")
        if sys_fg is None:
            sys_desc = "系统:无系数"
        else:
            zi = _zone_int(sys_fg)
            sys_desc = "系统:%.1f %s(%s)" % (sys_fg, _ZONE_TXT.get(zi, "?"),
                                             r.get("sys_fg_note", ""))
        # 动作判定
        greedy = ((sys_fg is not None and sys_fg >= 60)
                  or (st_val is not None and st_val >= sell_line))
        fearful = (st_val is not None and st_val <= buy_line)
        if over and greedy:
            act = "减仓（价格风控+贪婪双触发，优先级最高）"
        elif over:
            act = "减仓至上限%.0f（仅价格风控，系数%s；只降敞口不追方向）" % (
                lim, "贪婪" if greedy else "非贪婪")
        elif fearful:
            act = "持有/可加（恐慌买入区且敞口合规）"
        else:
            act = "持有观望"
        if lim is not None:
            out.append("· %s 市值%.0f/上限%.0f | %s | %s → %s"
                       % (sym, mv, lim, sys_desc, st_desc, act))
        else:
            out.append("· %s 市值%.0f（无上限） | %s | %s → %s"
                       % (sym, mv, sys_desc, st_desc, act))
    if not out:
        return None
    head = ("引擎A=价格风控(P1 1%规则)：市值超上限必须减到上限（硬敞口）；"
            "引擎B=贪恐系数：只定方向不动手；A+B 同时贪婪=最高减仓优先级。"
            "🟡 研究参考，实盘需人工确认。")
    return head + "\n" + "\n".join(out)


def _zone_int(fg):
    """fg_index → 档位整数 0极度恐惧~4极度贪婪（不依赖 features 的 zone 文本列）。"""
    if fg is None:
        return None
    edges = [20, 40, 60, 80]
    zi = 0
    for e in edges:
        if fg >= e:
            zi += 1
    return min(zi, 4)


def behavior_checklist(snap):
    """P2 极端档位行为检查清单（简报节）。

    知识库来源：Duomo 行为一致性 / ChatWithTraders Market Wizards
    （交易心理 57 条为最大主题簇，档位极端时最容易犯行为错误）。
    """
    fg = (snap.get("fg") or {}).get("fg_index")
    zi = _zone_int(fg)
    if zi == 0:
        return ("极度恐惧档位 · 行为检查清单【研究参考】\n"
                "☐ 恐慌割肉检查：卖出理由是否来自基本面恶化，而非仅因系数低？\n"
                "☐ 弹药纪律：熔断/极端日释放的弹药按计划分批，不一次打光\n"
                "☐ 分批节奏：恐惧区加仓按 1/3 步进，留子弹应对更低\n"
                "☐ 集中优势兵力：弹药集中于最高确信标的，不平均撒网（过度分散=同时押注所有方向）")
    if zi == 4:
        return ("极度贪婪档位 · 行为检查清单【研究参考】\n"
                "☐ 追高检查：是否在贪婪区追入未持有的标的？等待信号回中性\n"
                "☐ 止盈纪律：盈利仓位分批落袋，不赌最后一段\n"
                "☐ 杠杆上限：杠杆标的（YINN/TQQQ 等）不加仓，警惕衰减与清算\n"
                "☐ 集中度检查：持仓是否过度分散（数不过来/说不清每只为什么在）？单标的风险占比是否超出预算？")
    return None


def _human30_brief():
    """🌱 Human 3.0 状态节（组合骨架）。无记录返回 None（不输出空板块）。"""
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from fg_system import human30 as _h30
    line = _h30.brief_line()
    if not line:
        return None
    rec = _h30.latest()
    adv = _h30.advice(rec, _h30.history(2)[-2] if len(_h30.history(2)) >= 2 else None)
    out = [line] + ["· " + a for a in adv[:3]]
    # 连续未打卡提醒（确定性：断档会让极端档位归因缺样本）
    gap = _h30.days_since_last()
    if gap is not None and gap >= 1:
        out.append(f"⏰ 已连续 {gap} 天未打卡（上次 {rec['date']}）——记录断档，极端档位归因将缺样本")
    # 近 7 日统计（有记录才输出）
    w = _h30.window_stats(7)
    if not w["no_data"]:
        lv = w["level_counts"]
        lv_txt = " / ".join(f"L{k}×{lv[k]}" for k in (1, 2, 3) if lv.get(k))
        out.append(f"近 7 日：打卡 {w['records']} 次 · 意识层级 {lv_txt}")
    out.append("（自评打卡：页面表单 或 scripts/human30_cli.py --set --mind .. --body .. --spirit .. --vocation ..）")
    return "\n".join(out)


def _freshness_block():
    """读 Data/freshness_warning.txt（scripts/check_freshness.py 每日链写入）。
    有风险则返回告警文本，正常返回 None。"""
    p = REPO / "Data" / "freshness_warning.txt"
    if p.exists():
        txt = p.read_text(encoding="utf-8").strip()
        if txt and not txt.startswith("数据新鲜"):
            return txt
    return None


def _major_contradiction():
    """毛选·矛盾分析法（确定性）：取 features.csv 尾行五因子，
    计算「权重 × 偏离中性50」的合成贡献，绝对值最大=主要矛盾，次大=对冲力量。

    返回结构行（无数据/计算失败返回 None，不编造）。
    """
    try:
        import os
        import pandas as pd
        from fg_system import config
        path = os.path.join(config.ROOT, "Data", "features.csv")
        row = pd.read_csv(path).tail(1).iloc[-1]
        names = {"vix": "VIX", "term": "TERM", "price": "PRICE",
                 "breadth": "BREADTH", "fed": "FED"}
        contrib = []
        for col, label in names.items():
            if pd.isna(row.get(col)):
                continue
            val = float(row[col])
            contrib.append((abs(config.WEIGHTS[col] * (val - 50.0)),
                            label, val, "贪婪向" if val > 50 else "恐惧向"))
        if len(contrib) < 2:
            return None
        contrib.sort(reverse=True, key=lambda t: t[0])
        m1 = contrib[0]
        m2 = contrib[1]
        date = row.get("date")
        return (f"主要矛盾：{m1[1]} 因子 {m1[2]:.1f}（{m1[3]}，贡献最大）"
                f"；对冲力量：{m2[1]} 因子 {m2[2]:.1f}（{m2[3]}，其次）"
                f"〔features.csv 数据日 {date}，权重×偏离中性50〕")
    except Exception:
        return None


def build_brief_sections(snap, sentiment, attribution, judge, news=None):
    """结构化简报（飞书富文本 post 用）：[ ("标题", "正文"), "hr", ... ]"""
    from fg_system import fed as _fed
    _fctx = _fed.fed_context()
    secs = []
    _warn = _freshness_block()
    if _warn:
        secs.append(("⚠️ 数据新鲜度", _warn))
        secs.append("hr")
    secs.append(("市场快照", build_snapshot_lines(snap)))
    secs.append("hr")
    _risk_sec = risk_brief_text(snap)
    if _risk_sec:
        secs.append(("🛡️ 风控仓位（1%风险规则）", _risk_sec))
        secs.append("hr")
    _act_sec = action_brief_text(snap)
    if _act_sec:
        secs.append(("📉 减仓操作（双引擎：价格风控 × 贪恐系数）", _act_sec))
        secs.append("hr")
    _bc = behavior_checklist(snap)
    if _bc:
        secs.append(("🧠 行为检查清单", _bc))
        secs.append("hr")
    _h30 = _human30_brief()
    if _h30:
        secs.append(("🌱 Human 3.0 状态【自评记录】", _h30))
        secs.append("hr")
    secs.append(("🏛️ 美联储动态", _fed.fed_brief_text(_fctx)))
    secs.append("hr")
    secs.append(("📰 市场快讯", news_text(news) if news else "（新闻源不可用）"))
    secs.append("hr")
    secs.append(("📰 情绪面 · Hermes(GLM)", (sentiment or "（不可用）").strip()[:1200]))
    secs.append("hr")
    _mc = _major_contradiction()
    _attr_txt = (_mc + "\n\n" if _mc else "") + (attribution or "（归因生成失败，已降级跳过）").strip()[:2600]
    secs.append(("🔍 深度归因 · DeepSeek(NVIDIA NIM)", _attr_txt))
    secs.append("hr")
    secs.append(("⚖️ 裁判裁决 · OpenClaw云端(NVIDIA NIM)【研究参考】",
                 (judge or "（裁判未生成，已降级；以风控/归因结论为准）").strip()[:1200]))
    secs.append("hr")
    secs.append(("🧠 知识库观点佐证 · YouTube 9频道【研究参考】", _kb_brief_text(kb_evidence(snap))))
    secs.append("hr")
    secs.append(("📎 数据来源", _source_footnote(snap)))
    return secs


def _source_footnote(snap):
    """简报脚注：关键数字一律可指回来源文件与日期。"""
    fg_date = (snap.get("fg") or {}).get("date", "—")
    parts = [
        f"指数/因子: features.csv(数据日 {fg_date})",
        "熔断/弹药: state.json",
        f"持仓: positions.csv(快照 {snap.get('date', '—')})",
        "守猪待兔: shoutu_fng.csv",
        "美联储: federalreserve.gov + fedwatch.csv",
        "情绪: vix_history/funding_rate.csv",
    ]
    return " · ".join(parts)


# ---------------------------------------------------------------- 知识库观点佐证
_KB_THEMES = {
    "vix": "vix volatility fear option",
    "term": "yield curve term structure bond rates",
    "price": "price momentum trend following",
    "breadth": "market breadth internals sentiment indicators",
    "fed": "federal reserve monetary policy rate cuts inflation",
}


def kb_evidence(snap, n=2):
    """简报佐证：按当日档位/因子主题检索 YouTube 知识库，取 n 条最相关观点。
    返回 list[dict(channel,title,date,score,snippet)]，失败返回 None（不阻塞简报）。"""
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from kb_search import search_results
    except Exception as e:
        print(f"[kb] 导入失败: {e}")
        return None
    fg = snap.get("fg") or {}
    queries = []
    # 档位：zone 数字 → 英文档位词（0极度恐惧~4极度贪婪）
    z = fg.get("zone")
    if isinstance(z, (int, float)):
        zname = {0: "extremely fearful", 1: "fearful", 2: "neutral",
                 3: "greedy", 4: "extremely greedy"}.get(int(z), "")
        if zname:
            queries.append(f"{zname} market sentiment psychology")
    # 因子：features.csv 最新有效行（vix/term/price/breadth/fed）
    try:
        import pandas as pd
        feat = pd.read_csv(DATA / "features.csv")
        valid = feat.dropna(subset=["fg_index"])
        row = valid.iloc[-1]
        for key, q in _KB_THEMES.items():
            if key in row.index and pd.notna(row[key]):
                queries.append(q)
    except Exception:
        pass
    # 持仓主题（首个有名字的标的，如 YINN/TQQQ 杠杆ETF）
    for r in snap.get("positions", []):
        name = (r.get("name") or "").lower()
        sym = (r.get("symbol") or "").upper()
        if "leveraged" in name or sym in ("YINN", "TQQQ", "CONL", "GDXU"):
            queries.append("leveraged etf risk decay")
            break
    seen, hits = set(), []
    skip_titles = ("react to", "tiktok", "challenge", "try not to")
    for q in queries[:3]:
        for r in search_results(q, n=4):
            key = r["title"]
            if key in seen or r["score"] < 0.45:
                continue
            if any(s in key.lower() for s in skip_titles):
                continue
            seen.add(key)
            hits.append(r)
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:n] or None


def kb_note(query, n=1, max_len=100):
    """通用知识库观点提取：单主题查询取最高分观点，压缩 ≤max_len。
    返回单条文本（含来源与相关度），失败/无命中返回 ''。供异动告警等场景复用。"""
    import re as _re
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from kb_search import search_results
    except Exception:
        return ""
    skip = ("react to", "tiktok", "challenge", "try not to")
    for r in search_results(query, n=4):
        if r["score"] < 0.45:
            continue
        if any(s in (r["title"] or "").lower() for s in skip):
            continue
        snip = (r["snippet"] or "").replace("\n", " ").strip()
        snip = _re.sub(r"^[A-Za-z]{1,3}\s+", "", snip)
        if len(snip) > max_len:
            snip = snip[:max_len] + "…"
        return f"【{r['channel']}】《{r['title']}》相关度{r['score']}：{snip}"
    return ""


def _kb_brief_text(hits):
    """佐证节正文（飞书富文本/Markdown 共用，压缩单条 ≤110 字）。
    片段跳过开头寒暄，从首个完整句子后取信息量部分。"""
    if not hits:
        return "（知识库不可用或未命中）"
    import re
    lines = []
    for h in hits:
        snip = h["snippet"].replace("\n", " ").strip()
        # 去掉开头孤立截断词（VTT 切片常以 1-3 字母开头）
        snip = re.sub(r"^[A-Za-z]{1,3}\s+", "", snip)
        # 跳过寒暄，定位首个完整句子边界
        m = re.search(r"[.!?]\s+[A-Z\"'“]", snip[40:])
        if m:
            snip = snip[40 + m.start():]
        if len(snip) > 110:
            snip = snip[:110] + "…"
        date = h["date"] if h["date"] and h["date"] != "NA" else "日期NA"
        lines.append(f"【{h['channel']}】《{h['title']}》（{date}, 相关度{h['score']}）\n“{snip}”")
    return "\n\n".join(lines)


def build_brief(snap, sentiment, attribution, judge, news=None):
    from fg_system import fed as _fed
    _fctx = _fed.fed_context()
    _warn = _freshness_block()
    lines = [
        f"# 多智能体投研简报 {snap['date']}",
        "",
    ]
    if _warn:
        lines += ["## ⚠️ 数据新鲜度", _warn, "", "---", ""]
    lines += [
        "## 市场快照",
        "```",
        build_snapshot_lines(snap),
        "```",
        "",
    ]
    _risk_sec = risk_brief_text(snap)
    if _risk_sec:
        lines += ["## 🛡️ 风控仓位（1%风险规则）", _risk_sec, ""]
    _act_sec = action_brief_text(snap)
    if _act_sec:
        lines += ["## 📉 减仓操作（双引擎：价格风控 × 贪恐系数）【研究参考】", _act_sec, ""]
    _bc = behavior_checklist(snap)
    if _bc:
        lines += ["## 🧠 行为检查清单【研究参考】", _bc, ""]
    lines += [
        "## 🏛️ 美联储动态",
        _fed.fed_brief_text(_fctx),
        "",
        "## 市场快讯",
        news_text(news) if news else "（新闻源不可用）",
        "",
        "## 情绪面分析（Hermes / GLM）",
        (sentiment or "（跳过：Hermes 不可用）").strip()[:1500],
        "",
        "## 深度归因（Harness 后端 deepseek-v4.1-flash / NVIDIA NIM）",
        ((_major_contradiction() or "") + "\n\n" if _major_contradiction() else "")
        + (attribution or "（跳过：NIM 不可用）").strip()[:3000],
        "",
        "## 裁判裁决（OpenClaw 云端裁判 / NVIDIA NIM）【研究参考，非实盘指令】",
        (judge or "（跳过：裁判不可用）").strip()[:1200],
        "",
        "## 🧠 知识库观点佐证（YouTube 9频道）【研究参考，非实盘指令】",
        _kb_brief_text(kb_evidence(snap)),
        "",
        "## 📎 数据来源",
        _source_footnote(snap),
        "",
        "> 分级：🟢实盘动作=已采纳规则执行 · 🟡研究参考=模型分析不直接执行 · ⚪待验证=假说观察中",
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
        judge = stage_judge(_read_nim_key(), snap, sentiment or "（无）", attribution or "（无）")
    except Exception as e:
        print("OpenClaw 阶段失败:", e)

    brief = build_brief(snap, sentiment, attribution, judge, news)
    brief_path.write_text(brief, encoding="utf-8")
    print(f"简报已写入: {brief_path}")

    # ---- Harness 模式落地 #1/#2/#6：外验证门（Policy-as-Code）----
    # 阻断级失败（结构缺失/数字不可追溯/无日期）→ 跳过推送，人工核查
    try:
        from verify_brief import verify_and_report
        blocked = verify_and_report(brief, snap)
    except Exception as e:
        print(f"[verify] 验证门异常（放行但记录）: {e}")
        blocked = False

    if args.dry_run:
        print(brief[:500])
        return

    # ---- #7 Agent-Maintained Memory：沉淀决策日志（人工门控）----
    try:
        from decision_log import append as _dl_append
        _dl_append(snap, judge)
    except Exception as e:
        print(f"[decision-log] 沉淀失败: {e}")

    # ---- #5 Lineage Compaction：简报轮转归档（保留 7 天）----
    try:
        from archive_briefs import archive as _archive
        _archive(keep_days=7)
    except Exception as e:
        print(f"[archive] 归档失败: {e}")

    if blocked:
        print("[verify] 简报存在阻断级问题，跳过飞书推送（请先核查 last_brief_check.json）")
        return 2
    if not (sentiment and attribution and judge):
        print("存在缺失阶段，跳过飞书推送（dry-run 模式已可查看简报）")
        return
    ok, msg = push_feishu_rich(f"📊 多智能体投研简报 {snap['date']}",
                               build_brief_sections(snap, sentiment, attribution, judge, news))
    print(f"飞书富文本推送: {'成功' if ok else f'失败 {msg}'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
