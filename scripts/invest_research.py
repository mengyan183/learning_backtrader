#!/usr/bin/env python3
"""多智能体投研流水线原型 (E1)

三段 AI：**情绪面 → 深度归因 → 裁判裁决**，最后推送飞书。

🔴 2026-10-31：**通道全部改读环境变量** ✓ —— 不再硬编码供应商 ✗
   `FG_HERMES_URL` / `FG_HERMES_MODEL`（情绪面）
   `FG_LLM_URL`    / `FG_LLM_MODEL`   （归因 + 裁判，同通道）
   `FG_LLM_KEY`（不设则从 `~/.dsh/.credentials.yaml` 读，优先 `sk-` ✓）
   `FG_LLM_PROXY`（空串 = 直连 ✓）
   ⇒ 简报里的**小节标题也从运行时配置推导**（`_llm_tag`）✓ ——
     硬编码「Hermes(GLM)」「NVIDIA NIM」会过期 ✗（曾长期误导 ✗）。

BTC 持仓现价回退源：OKX REST(走 7890 代理)；FG_STATIC_ONLY=1 时跳过外部行情。

用法:
  .venv/bin/python scripts/invest_research.py          # 全流程 + 推送飞书
  .venv/bin/python scripts/invest_research.py --dry-run  # 只产出简报不推送
说明:
  - 密钥全部从本机配置文件/环境变量读取，源码树不出现任何密钥
  - 任一阶段失败自动降级：情绪面失败 → 跳过该节；归因失败 → 跳过该节；
    裁判失败 → 以归因/风控结论为准 ✓
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
DATA = REPO / "Data"

# ── LLM 通道（2026-10-30 改成**读配置** ✓，全部可用环境变量覆盖）──────────
# 背景：Mac 上 openclaw / hermes / deepseek-harness 三个 agent 已统一走
# DeepSeek 的 API ✗，而这里还硬编码 NVIDIA NIM 的地址与模型 ✗ ⇒ 换一次改一次代码 ✗。
#
# 切换方式（Mac 上设环境变量，不用改代码）：
#   export FG_LLM_URL="https://api.deepseek.com/v1/chat/completions"
#   export FG_LLM_MODEL="deepseek/deepseek-flash"
#   export FG_LLM_KEY="sk-..."          # 不设则回落到 ~/.dsh/.credentials.yaml
#   export FG_LLM_PROXY=""              # 官方 API 国内直连，不用代理
# 默认值**保持原样** ✓ —— 不设环境变量时行为完全不变（避免静默改变生产链路 ✗）。
HERMES_URL = os.environ.get(
    "FG_HERMES_URL", "http://127.0.0.1:8642/v1/chat/completions")
HERMES_MODEL = os.environ.get("FG_HERMES_MODEL", "hermes-agent")
NIM_URL = os.environ.get(
    "FG_LLM_URL", "https://integrate.api.nvidia.com/v1/chat/completions")
NIM_MODEL = os.environ.get(
    "FG_LLM_MODEL", "deepseek-ai/deepseek-v4.1-flash")
#: LLM 调用走的本地代理（Mac 上是 Clash 默认端口）✓
#: 🔴 2026-10-29：原来**硬编码** ✗ —— Clash 换端口就得改代码 ✗；
#: 现在可用 `FG_LLM_PROXY` 覆盖（空串 = 不用代理）✓
PROXY = os.environ.get("FG_LLM_PROXY", "http://127.0.0.1:7890")

#: 标的 → 知识库检索词 ✓（2026-10-30：**按标的匹配**，不再用泛化主题 ✗）
#: 只用标的所属**行业/主题**，不写"outlook"这类空词（会被泛泛而谈命中 ✗）
KB_SYMBOL_TERMS = {
    "YINN": "china large cap stocks policy stimulus",
    "GDXU": "gold miners real rates",
    "CRCG": "circle stablecoin regulation",
    "CONL": "coinbase crypto exchange earnings",
    "AXTX": "semiconductor equipment orders",
    "TQQQ": "nasdaq 100 technology earnings",
    "SOXL": "semiconductor cycle",
    "UPRO": "s&p 500 breadth",
    "BTC": "bitcoin etf institutional flows",
}

#: 知识库佐证的最低相关度 ✓ —— 低于它的命中与当天持仓基本无关，宁缺毋滥 ✗
#: 2026-10-29 用户裁定 **0.7 → 0.6** ✓：0.7 把命中全过滤掉了，整节变成空占位 ✗
#: 知识库佐证最低相关度 ✓ —— 保持 **0.6** ✗（2026-10-29 用户裁定 0.7 太严：
#: 命中全被过滤 ⇒ 整节变空占位 ✗）。
#: 2026-10-31 起改用**实体词过滤**治噪音 ✓（见 `KB_QUERY_ENTITIES`）——
#: 光提阈值会把「相关但分数不高」的也砍掉 ✗，砍不到「分数高但跑题」的 ✗。
KB_MIN_SCORE = 0.6

#: 检索词 → **片段里必须出现的实体词** ✓（2026-10-31）
#: 动机：0.602 的 RaynerTeo《Trading Results》讲比特币减半，
#: 分数过了 0.6 但与当天持仓无关 ✗ —— 问题是**语义相似 ≠ 讲的是同一个东西** ✗
#: ⇒ 片段必须提到该主题的核心实体，否则丢弃 ✓
KB_QUERY_ENTITIES = {
    "china large cap stocks policy stimulus": ("china", "chinese", "yuan", "beijing"),
    "gold miners real rates": ("gold", "miner", "bullion"),
    "circle stablecoin regulation": ("circle", "stablecoin", "usdc"),
    "coinbase crypto exchange earnings": ("coinbase", "crypto", "exchange"),
    "semiconductor equipment orders": ("semiconductor", "chip", "wafer", "axti"),
    "nasdaq 100 technology earnings": ("nasdaq", "tech", "earnings"),
    "semiconductor cycle": ("semiconductor", "chip", "cycle"),
    "s&p 500 breadth": ("s&p", "breadth", "500"),
    # 🔴 BTC 的检索词原来是 "bitcoin liquidity halving" ✗ ——
    # 「halving」是个**话题词**不是持仓逻辑，会命中一堆讲减半原理的科普 ✗
    # ⇒ 改成与「借 USDT 买入 BTC」这个仓位直接相关的：ETF 资金流 + 机构需求 ✓
    "bitcoin etf institutional flows": ("bitcoin", "etf", "institutional", "btc"),
}

#: 阶段日志的写锁 ✓ —— 三个线程并发 append 在 Windows 上会偶发丢行 ✗
_LOG_LOCK = threading.Lock()


def _port_ok(host, port, timeout=1.5):
    """本地端口能不能连 ✓ —— 服务没起就**秒跳过**，别白等 240 秒阶段超时 ✗。

    2026-10-29 实测：代理恢复后 net_probe 全绿（200/641ms），但简报的两个阶段
    仍 240s 超时 ✗ ⇒ 说明「网络通」≠「服务在」✗。
    """
    import socket
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _url_addr(url):
    """`http://host:port/...` ⇒ `(host, port)` ✓；解析不了返回 None。"""
    if not url:
        return None
    import urllib.parse
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if not u.hostname:
        return None
    return (u.hostname, u.port or (443 if u.scheme == "https" else 80))


#: 三个 LLM 阶段各自的「本机入口」✓ —— 预检用
#:   Hermes        → 本地 127.0.0.1:8642（不走代理）✗
#:   deepseek 归因 → NVIDIA NIM，经本地代理（预检代理端口）✓
#:   OpenClaw 裁判 → 同 NIM 通道（同一代理）✓
HERMES_ADDR = _url_addr(HERMES_URL)
PROXY_ADDR = _url_addr(PROXY)
FEISHU_OPEN_ID = "ou_c4f5cd25e5001a853309524e899dd6d2"
OKX_TICKER_URL = "https://www.okx.com/api/v5/market/ticker?instId={sym}"
# 公司电脑只跑静态数据时置 1，禁止任何外部行情 API（富途/OKX）
STATIC_ONLY = os.environ.get("FG_STATIC_ONLY", "0") == "1"


# ---------------------------------------------------------------- 凭据读取
def _read_hermes_key():
    # 2026-10-30：优先环境变量 ✓（统一走 DeepSeek 后，两处可以用同一个 key ✓）
    if os.environ.get("FG_LLM_KEY"):
        return os.environ["FG_LLM_KEY"]
    import yaml
    cfg = yaml.safe_load(open(Path.home() / ".hermes" / "config.yaml"))
    return cfg.get("platforms", {}).get("api_server", {}).get("key")


def _read_nim_key():
    # 2026-10-30：`FG_LLM_KEY` 优先 ✓ —— 换供应商时只改环境变量，不动代码 ✓
    if os.environ.get("FG_LLM_KEY"):
        return os.environ["FG_LLM_KEY"]
    import yaml
    cred = yaml.safe_load(open(Path.home() / ".dsh" / ".credentials.yaml"))
    # 2026-10-30：**优先 `sk-`（DeepSeek 官方）** ✓，其次 `nvapi-`（NVIDIA）✓
    # —— 原来只认 nvapi- ✗，切到 DeepSeek 后读不到 key ⇒ 401 Unauthorized ✗
    found = {"sk-": None, "nvapi-": None}

    def walk(d):
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, str):
                    for pre in found:
                        if v.startswith(pre) and not found[pre]:
                            found[pre] = v
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)

    walk(cred)
    return found["sk-"] or found["nvapi-"]


def _read_llm_key():
    """归因 / 裁判用的 key ✓ —— **按 URL 决定从哪读** ✗（2026-10-31）。

    🔴 实测教训：plist 里把 `FG_LLM_URL` 指到 `api.deepseek.com` 后，
    情绪面（本地 Hermes 8642）**从成功变成失败** ✗，归因/裁判仍是 401 ✗
    ⇒ **直连 DeepSeek 这条路在 Mac 上不通** ✗（key 不在 `~/.dsh`，或网络受限 ✗）。
    而本地 Hermes 服务**内部已经配好 DeepSeek** ✓（10:37 那次情绪面成功即为证 ✓）
    ⇒ 正确做法：**统一走本地 Hermes**，key 也用它自己的 ✓。
    """
    if os.environ.get("FG_LLM_KEY"):
        return os.environ["FG_LLM_KEY"]
    if "127.0.0.1" in str(NIM_URL) or "localhost" in str(NIM_URL):
        try:
            return _read_hermes_key()
        except Exception:                  # noqa: BLE001 —— 读不到就回落 ✓
            pass
    return _read_nim_key()


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
    # 🔴 2026-10-31：**现金明细** ✗ —— 简报里「加密净值 2,742 vs BTC 市值 2,318，
    # 差 425」一直没人能解释（是闲置 USDT？还是借币利息？✗）
    # `accounts.csv` 本来就有 `securities_mv` / `cash` 两列 ✓ ⇒ 直接给出来 ✓
    detail = {}
    for _, r in acc_latest.iterrows():
        detail[str(r["account"])] = {
            "net_value": float(r["net_value"]),
            "securities_mv": float(r["securities_mv"]) if pd.notna(r.get("securities_mv")) else None,
            "cash": float(r["cash"]) if pd.notna(r.get("cash")) else None,
            "date": str(r["date"].date()),
        }
    snap["accounts_detail"] = detail

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
    # 2026-10-29：指数数据日单独留一份 ✓ —— `snap["date"]` 是**持仓快照日**，
    # 两者不同源、经常差一天 ✗（持仓同步失败那天，指数已经算到新日期 ✗）
    snap["index_date"] = (snap["fg"] or {}).get("date")

    # 🔴 2026-10-31 用户裁定：**有效名义敞口进快照** ✓ ——
    # 名义仓位会被杠杆倍数掩盖 ✗：5 只 2~3 倍 ETF 的「市值 10,465」
    # 实际对应 **29,473** 的市场敞口（净值的 2.39 倍）✗
    # 而 AI 只能看到名义仓位 ⇒ 一直报「超配 1.8 倍」，低估了 2.8 倍 ✗
    # ⚠️ 必须在 `snap["fg"]` 之后算 ✗ —— 目标仓位来自那里 ✓
    try:
        from fg_system import position_plan as _pp
        _total_net = sum(float(v or 0) for v in snap["accounts"].values())
        _eff = sum(float(r.get("mv") or 0) * _pp.leverage_of(r.get("symbol"))
                   for r in rows)
        _tgt = (snap.get("fg") or {}).get("target_position")
        if _total_net > 0 and _eff > 0:
            snap["eff_exposure"] = (
                "%.0f（净值 %.0f 的 **%.2f 倍**）%s"
                % (_eff, _total_net, _eff / _total_net,
                   ("· 目标仓位 %.1f%% ⇒ 超配 **%.1f 倍**"
                    % (float(_tgt) * 100, _eff / (_total_net * float(_tgt))))
                   if _tgt else ""))
    except Exception as _e:                # noqa: BLE001 —— 算不出就不给 ✓
        print("[warn] 有效敞口计算失败：%s" % _e)

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
            # 2026-10-30：1% 规则改用**底层 ATR × 杠杆**（纪律 4C.4 ✓）——
            # 原来用杠杆 ETF 自身 ATR，含 vol decay/费用噪声 ✗
            atrp = risk_mod.atr_pct_effective(px, sym0, px_now)
            lim, _ratio = risk_mod.position_limit(stock_net, mv0, atrp)
            r["risk_limit"] = round(lim, 2) if lim else None
            r["atr_pct"] = atrp
            # 建仓间距要的是**正股** ATR（`position_plan` 自己再乘杠杆 ✓），
            # 不能传上面的有效值 —— 否则杠杆被乘两次 ✗
            r["atr_pct_und"] = risk_mod.atr_pct_underlying(px, sym0)
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
    # 2026-10-29：喂给 LLM 的日期也写双日 ✓ —— 只给持仓日会让模型把指数当成旧数据 ✗
    lines = [f"数据日期: {_date_label(snap)}"]
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
    # 🔴 2026-10-31：把**仓位口径**显式给出 ✗ —— 原来只给净值 dict ⇒
    # AI 自己挑分母 ✗ ⇒ 两份简报一个算 103.7%（股票净值做分母）、
    # 一个算 84.9%（总净值）✗ 同一持仓两个数 ✗
    acc = snap.get("accounts") or {}
    stock_net = float(acc.get("stock") or 0)
    total_net = sum(float(v or 0) for v in acc.values())
    stock_mv = sum(float(r.get("mv") or 0) for r in snap.get("positions", [])
                   if str(r.get("account")) == "stock")
    if total_net > 0:
        lines.append(
            "仓位口径（**直接引用，不要自己重算**）: "
            "名义仓位 %.1f%%（分母=总净值 %.0f）· "
            "股票端仓位 %.1f%%（分母=股票净值 %.0f）"
            % (stock_mv / total_net * 100, total_net,
               (stock_mv / stock_net * 100) if stock_net else 0.0, stock_net))
    # 现金明细（回答「净值比币值多出来的钱是什么」✗）
    ad = snap.get("accounts_detail") or {}
    if ad:
        lines.append("账户明细: " + " · ".join(
            "%s 净值%.0f（证券%.0f / 现金%.0f，%s）"
            % (k, v["net_value"], v["securities_mv"] or 0, v["cash"] or 0,
               v["date"]) for k, v in ad.items()))
    # 🔴 2026-10-31：**有效名义敞口**必须显式给出 ✗ ——
    # 名义仓位（84.9%）会被杠杆倍数掩盖 ✗，真实敞口是净值的 2.39 倍 ✓
    # 不给这个数，模型只会说「超配 1.8 倍」，低估 2.8 倍 ✗
    eff = snap.get("eff_exposure")
    if eff:
        lines.append("有效名义敞口（含杠杆倍数，**直接引用**）: %s" % eff)
    # 无交易记录 ⇒ 禁止推断「是否减过仓」✗（2026-10-31 实测的错误归因）
    lines.append("持仓变动: 快照**只有当前持仓**，无买卖流水 ⇒ "
                 "**禁止推断某标的「是否减过仓/是残余仓位」** ✗")
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
    return _chat(HERMES_URL, hermes_key, HERMES_MODEL, system, user,
                 max_tokens=800)


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


def _kb_context(query, n=3):
    """可选引用知识库观点（L3.5 闭环增强）：kb_search 结构化检索 → 观点参考文本。

    非 LLM 判决：仅作归因参考上下文，逐条标注来源（YouTube 知识库）；
    检索失败/库空返回空串，不阻塞主流程。
    """
    try:
        from scripts import kb_search
        rows = kb_search.search_results(query, n=n)
    except Exception as e:
        print("[kb_context] 知识库检索失败（按无引用处理）: %s" % e, file=sys.stderr)
        return ""
    if not rows:
        return ""
    lines = ["【知识库观点参考（YouTube 交易频道字幕，仅参考不构成信号）】"]
    for r in rows[:n]:
        lines.append("- 来源 %s《%s》（%s，相关度 %.3f）：%s"
                     % (r["channel"], r["title"], r["date"], r["score"],
                        r["snippet"][:200].replace("\n", " ")))
    return "\n".join(lines) + "\n\n"


def stage_attribution(nim_key, snap, kb=None):
    """Harness 后端模型(deepseek-v4.1-flash via NVIDIA NIM) 深度归因

    kb: 可选检索问题（L3.5）——注入知识库观点作参考上下文，不改判决链。
    """
    system = (
        "你是量化交易系统的深度归因分析师。基于持仓与盈亏数据，"
        "用中文输出结构化归因（≤800字）：逐标的归因（为什么涨/跌、驱动因素）、"
        "组合风险点、仓位合理性。只做归因分析，不给交易指令。"
        "直接输出最终分析正文，不要输出思考过程。\n\n"
        # 🔴 2026-10-31 用户裁定：**禁止线性折算** ✗
        # 杠杆 ETF 的累计收益是**逐日复利**的：
        #   ETF累计 = ∏(1 + L×r_i)  ≠  1 + L×Σr_i
        # 震荡市里 ETF 跌幅 **大于** 标的跌幅×L（volatility decay）
        # ⇒ 用「ETF跌幅 ÷ 杠杆倍数」反推标的跌幅会**系统性低估** ✗
        # （实测：AXTX -82.75% 被折算成「标的仅跌41.4%」✗ 实际更深）
        # 🔴 2026-10-31 用户裁定：把「无流水不得推断减仓」写死 ✗
        # 实测错误：模型说「YINN 占股票端 33.7% 却只贡献 7.3% 亏损，
        # 说明它是**减仓后的残余仓位**」✗ —— 因果倒置 ✗
        # 真相：YINN 权重从成本口径 21.3% 涨到市值口径 33.7%，
        # 是因为它**跌得最少**（-16% vs AXTX -83%），不是被减过 ✗
        "【硬性约束】快照**只有当前持仓，没有买卖流水** ✗ ⇒ "
        "**禁止推断**某标的「是否减过仓 / 是减仓后的残余仓位 / 曾经加过仓」✗。"
        "权重占比的变化只能归因于**涨跌幅差异**（跌得少的标的占比自然上升）✓。\n"
        "【硬性约束】谈仓位超配时必须用「**有效名义敞口**」（已含杠杆倍数），"
        "不要只用名义仓位 —— 名义仓位会被 2~3 倍杠杆掩盖 ✗。\n"
        "【硬性约束】禁止用「ETF 跌幅 ÷ 杠杆倍数」反推标的跌幅 ✗。"
        "杠杆 ETF 是逐日复利，震荡市有 volatility decay ⇒ 该折算会"
        "**系统性低估**标的真实跌幅。需要描述标的时，只说"
        "「标的期间下跌，杠杆放大且叠加复利损耗」，**不要给出具体折算数字**。"
        "同理禁止把「ETF 累计涨幅 ÷ 杠杆」当作标的涨幅。"
    )
    kb_txt = _kb_context(kb) if kb else ""
    user = f"{kb_txt}以下是今日持仓快照：\n{snapshot_text(snap)}\n\n请输出深度归因分析。"
    try:
        out = _chat(NIM_URL, nim_key, NIM_MODEL, system, user,
                    max_tokens=4096, proxy=PROXY, timeout=120, retries=2)
        clean = _clean_attribution(out)
        if clean is None:
            # 疑似 prompt 回显/思考 → 重试一次（NIM 偶发）
            out = _chat(NIM_URL, nim_key, NIM_MODEL, system, user,
                        max_tokens=4096, proxy=PROXY, timeout=120, retries=1)
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
                    max_tokens=400, proxy=PROXY, timeout=120, retries=1)
        v = _validate_judge(out)
        if v is None:
            out = _chat(NIM_URL, nim_key, NIM_MODEL, system, user,
                        max_tokens=400, proxy=PROXY, timeout=120, retries=1)
            v = _validate_judge(out)
        if v is None:
            return "（裁判未按三行格式输出，本次以归因/风控结论为准。）"
        return v
    except Exception as e:
        # 2026-10-31：不再硬编码「NIM」✗ —— 通道可能已换成 DeepSeek / 本地 ✓
        return (f"裁判调用失败（{_llm_tag(NIM_URL, NIM_MODEL)}）：{e}，"
                "本次以归因结论为准。")


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
            else:
                # 🔴 2026-10-31：富途返回空也要**留痕** ✗ ——
                # 原来静默跳过，简报里少几组新闻没人知道为什么 ✗
                print("[news] 富途无结果：%s（kw=%s, ret=%s, n=%s）"
                      % (sym, kw, ret, 0 if data is None else len(data)))
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
    # 🔴 2026-10-31 实测：某天简报的「市场快讯」从 6 组缩到 3 组 ✗
    # （CRCG/CONL/AXTX/BTC 全没了），但**没有任何提示** ✗
    # ⇒ 打一行覆盖情况 ✓ —— 让「缩水」在日志里可见，不用靠数行数发现 ✗
    want = [str(r.get("symbol") or "").replace("-USDT", "")
            for r in (snap.get("positions") or [])]
    miss = [s for s in want if s and s not in out]
    print("[news] 覆盖 %d/%d 标的%s；大盘%s"
          % (len(want) - len(miss), len(want),
             ("，缺 " + "、".join(miss)) if miss else "",
             "有" if out.get("_market") else "**无** ✗"))
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
        # 2026-10-29：目标仓位打**百分比** ✗ —— 原来直接打 float，
        # 简报里出现 `0.4708333333333333` ✗
        out.append(f"系统贪恐指数 {f['fg_index']} [{f['zone']}] · 目标仓位 {float(f['target_position']):.1%} · 回撤 {f['drawdown']:.2%} · 熔断{'已触发' if f['circuit_breaker'] else '未触发'}")
    if snap.get("shoutu"):
        # 全量展示（修复 2026-10-07 审查发现的 [:6] 静默截断：UPRO/YINN 被隐藏）
        items = list(snap["shoutu"].items())
        pairs = " / ".join(f"{k} {v}" for k, v in items[:8])
        if len(items) > 8:
            pairs += " …"  # 超过 8 个标的时显式标注省略
        out.append(f"守猪待兔({snap['shoutu_date']}): {pairs}")
    out.append("持仓:")
    for r in snap["positions"]:
        # 2026-10-29：统一 2 位小数 ✗ —— 原来直接打 pandas float，
        # 同一列里 `-869.78` 和 `-1276.8` 混着出现 ✗
        pnl = ("%.2f (%.2f%%)" % (r["pnl"], r["pnl_pct"])
               if r["pnl"] is not None else "无行情")
        flag = "🔺" if (r["pnl"] or 0) > 0 else ("🔻" if (r["pnl"] or 0) < 0 else "▪️")
        out.append(f"{flag} {r['symbol']} {r['name']} · 成本 {r['cost']} · 现价 {r['last_close'] or '—'} · 浮盈亏 {pnl}")
    out.append(f"账户净值: " + " / ".join(f"{k} {v}" for k, v in (snap.get('accounts') or {}).items()))
    # 🔴 2026-10-31 用户裁定：**账户明细进简报正文** ✓ ——
    # 原来只在 `snapshot_text`（喂 LLM 的）里给，正文看不到 ✗
    # ⇒ 「加密净值 2,742 vs BTC 市值 2,318，差 425」一直没解释 ✗
    # 现在正文直接给「证券 / 现金」拆分，差额一眼可见 ✓
    ad = snap.get("accounts_detail") or {}
    if ad:
        parts = []
        for k, v in ad.items():
            seg = "%s 净值%.0f" % (k, v["net_value"])
            if v.get("securities_mv") is not None:
                seg += "（证券%.0f / 现金%.0f）" % (v["securities_mv"],
                                                   v.get("cash") or 0)
            parts.append(seg)
        out.append("账户明细: " + " · ".join(parts))
    # 有效名义敞口（含杠杆）✓ —— 名义仓位会被杠杆倍数掩盖 ✗
    eff = snap.get("eff_exposure")
    if eff:
        out.append("有效敞口: %s" % eff)
    return "\n".join(out)


def risk_brief_text(snap):
    """P1 风控仓位节（简报）：逐标的风险上限 + 连亏 kill switch。

    1% 风险规则：建议市值上限 = 账户净值×1% / (2×ATR20)。
    知识库来源：RaynerTeo《Math Behind》/ Peter Brandt 风控。
    """
    lines = []
    # 2026-10-29：**只给汇总** ✓ —— 逐标的的「市值/上限」在下面「减仓操作」里
    # 已经逐条列过一次 ✗，两节重复同一批数字纯属噪音 ✗。
    pos = snap.get("positions", [])
    over = [r for r in pos if r.get("risk_limit") and r["risk_over"]]
    if over:
        lines.append("⚠ %d/%d 个标的超出 1%% 风险上限（合计需减 %.0f）—— 逐标的见「减仓操作」"
                     % (len(over), len(pos),
                        sum(r["mv"] - r["risk_limit"] for r in over)))
    elif pos:
        lines.append("✓ 全部标的未超 1%% 风险上限")
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
            # 2026-10-29：后缀从**每条**挪到段首 ✗ —— 原来 6 条各带一遍
            # 「（仅价格风控，系数非贪婪；只降敞口不追方向）」✗
            act = "减仓至上限%.0f" % lim
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
    # 2026-10-29：把「仅价格风控/只降敞口不追方向」的说明**提到段首说一次** ✗
    # —— 原来 6 条各带一遍同样的后缀 ✗
    if any("减仓至上限" in ln for ln in out):
        head += ("\n标注「减仓至上限」= 仅价格风控触发（系数非贪婪）⇒ 只降敞口、不追方向。")
    # 🔴 2026-10-31 用户裁定：**减仓顺序要写进简报** ✗
    # 排序 = 浮亏深度 × 杠杆倍数（越大越先减）✓ 依据：
    #   ① 浮亏深 ⇒ 回本数学**指数级**恶化（-83% 要 +488%，几乎不可能）
    #   ② 杠杆高 ⇒ 日重置损耗更快（震荡市纯亏）
    #   ③ 盈利仓（BTC）⇒ 不减，不列入 ✓
    # ⚠️ 不排序的话，照「逐标的减到上限」平均减会先砍 YINN（方向最对、
    #    亏得最少）而留着 AXTX（已废）⇒ **减反了** ✗
    from fg_system import position_plan as _pp
    ranked = []
    for r in snap.get("positions", []):
        pnl = r.get("pnl_pct")
        if pnl is None or float(pnl) >= 0:
            continue
        lev = _pp.leverage_of(r.get("symbol"))
        ranked.append((abs(float(pnl)) * lev, str(r.get("symbol")),
                       float(pnl), lev))
    ranked.sort(reverse=True)
    if len(ranked) >= 2:
        head += ("\n**减仓顺序**（浮亏深度×杠杆倍数，越大越先减；"
                 "盈利仓不减）：%s"
                 % " > ".join("%s（%.0f%%×%dx）" % (s, p, l)
                              for _sc, s, p, l in ranked))
    return head + "\n" + "\n".join(out)


def position_plan_brief(snap):
    """📐 建仓/加仓计划 ✓ —— 按 `fg_system.position_plan` 的口径逐标的给结论。

    2026-10-30 用户裁定：杠杆 ETF「越跌越买」是负期望（3x 从 -50% 回本要 +100%）
    ⇒ 必须把首建/加仓/上限写成可执行规则 ✗，且**超限时冻结加仓** ✓
    （否则与「减仓至上限」互相打架 ✗）。
    """
    from fg_system import position_plan as pp
    net = (snap.get("accounts") or {}).get("stock")
    if not net:
        return None
    pos = snap.get("positions") or []
    lev_total = sum(float(r.get("mv") or 0) for r in pos
                    if pp.leverage_of(r.get("symbol")) > 1)
    lines = []
    for r in pos:
        sym0 = str(r.get("symbol") or "").replace("-USDT", "")
        plan = pp.build_plan(
            net, sym0, r.get("atr_pct_und"),   # 正股 ATR ✓（gap_pct 内部再乘杠杆）
            (snap.get("shoutu") or {}).get(sym0),
            held_value=float(r.get("mv") or 0),
            pnl_pct=r.get("pnl_pct"),
            leveraged_value=lev_total,
            risk_limit=r.get("risk_limit"))
        ln = pp.brief_line(plan)
        if ln:
            lines.append(ln)
    if not lines:
        return None
    # 2026-10-30 用户裁定措辞：不写「待回测确认」✗ ——
    # 现有回测**不支持**该规则（样本外全负、前后半段方向不一致 ✗），
    # 但样本太少也不足以证伪 ⇒ 如实写「样本太少、待丰富」✓
    head = ("规则（2026-10-30 定版 C · **回测样本太少，待丰富回测样本**；"
            "现有样本**不支持**该规则，仅供参考）：单标的 ≤%.0f%% 净值、"
            "杠杆总敞口 ≤%.0f%%、首建 %.0f%%、加仓 %.0f%%×%d、"
            "间距 = %.1f×ATR20(正股)×杠杆、相邻 ≥%d 交易日；"
            "浮亏 >%.0f%% 只禁加仓、不清仓。🟡 研究参考，实盘需人工确认。"
            % (pp.PLAN["single_cap"] * 100, pp.PLAN["total_cap"] * 100,
               pp.PLAN["first"] * 100, pp.PLAN["adds"][0] * 100,
               len(pp.PLAN["adds"]), pp.PLAN["atr_k"],
               pp.PLAN["min_gap_days"], abs(pp.PLAN["hard_stop"]) * 100))
    return head + "\n" + "\n".join(lines)


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


def _drawdown_of(snap):
    """从 snap 取标的指数回撤（`snap["fg"]["drawdown"]`，唯一既有数据源）。

    形态兼容：`pipeline.drawdown_series()` 产出 `1 - basket/peak` ⇒ **正数形态**
    （0.0559 = 5.59% 回撤）；亦兼容负数（-0.0559）与百分数字面量（5.59）。
    取不到 ⇒ 返回 None（不猜、不崩）。
    """
    dd = (snap.get("fg") or {}).get("drawdown")
    if dd is None:
        return None
    try:
        dd = float(dd)
    except (TypeError, ValueError):
        return None
    if dd != dd:            # NaN
        return None
    if abs(dd) > 1:         # 百分数字面量 ⇒ 归一到小数
        dd = dd / 100.0
    return dd


# P0（2026-10-15 C-3 批准）：交易前检查单的「视角自问」两项。
# 视角 = 思维顾问 / 研究参考，**永不进信号、不改任何确定性规则**（nuwa 结合方案 §1 红线）。
# 确定性模板文案，**不调 LLM** ✗。
_PERSPECTIVE_PROMPTS = (
    "🟡 思维顾问自问（研究参考，非系统信号）\n"
    "☐ 🔍 芒格审视：这笔交易**反过来看**，最大的错误会是什么？"
    "（逆向思考 / 认知偏误自查）\n"
    "☐ 🛡 塔勒布审视：最坏情景发生，我的损失是否在可承受范围？"
    "（尾部风险 / skin in the game）"
)


def behavior_checklist(snap):
    """P2 极端档位 + 抄底三黑 行为检查清单（简报节）。

    知识库来源：Duomo 行为一致性 / ChatWithTraders Market Wizards
    （交易心理 57 条为最大主题簇，档位极端时最容易犯行为错误）。
    §4.5 抄底三黑：弹药释放按回撤（`DRAWDOWN_BATCHES`）触发 ⇒ 清单随之出现。
    """
    fg = (snap.get("fg") or {}).get("fg_index")
    zi = _zone_int(fg)
    if zi == 0:
        return ("极度恐惧档位 · 行为检查清单【研究参考】\n"
                "☐ 恐慌割肉检查：卖出理由是否来自基本面恶化，而非仅因系数低？\n"
                "☐ 抄底三黑①过早满仓：弹药按计划分批，「不一次打光」"
                "（此刻还有几批未释放？）\n"
                "☐ 抄底三黑②单一重仓：既不平均撒网（同时押注所有方向），"
                "也不把弹药砸在一个标的上\n"
                "☐ 抄底三黑③档差没拉开：三批对应 -20% / -40% / -60%，"
                "不挤在同一个小坑里打完\n"
                "（详见 trading-discipline.md §4.5）")
    dd = _drawdown_of(snap)          # 从 snap 取回撤（小数，负数或正数都兼容）
    if dd is not None and abs(dd) >= 0.20:      # 与 config.DRAWDOWN_BATCHES[0] 同源
        # 阈值故意写死 0.20：简报层不依赖 config 计算（避免耦合）；
        # 同源 = config.DRAWDOWN_BATCHES[0]，改 config 时此处须同步。
        return ("回撤已达首档（弹药开始释放）· 行为检查清单【研究参考】\n"
                "☐ 抄底三黑①过早满仓：弹药按计划分批，「不一次打光」"
                "（此刻还有几批未释放？）\n"
                "☐ 抄底三黑②单一重仓：既不平均撒网（同时押注所有方向），"
                "也不把弹药砸在一个标的上\n"
                "☐ 抄底三黑③档差没拉开：三批对应 -20% / -40% / -60%，"
                "不挤在同一个小坑里打完\n"
                "（详见 trading-discipline.md §4.5）")
    if zi == 4:
        return ("极度贪婪档位 · 行为检查清单【研究参考】\n"
                "☐ 追高检查：是否在贪婪区追入未持有的标的？等待信号回中性\n"
                "☐ 止盈纪律：盈利仓位分批落袋，不赌最后一段\n"
                "☐ 杠杆上限：杠杆标的（YINN/TQQQ 等）不加仓，警惕衰减与清算\n"
                "☐ 集中度检查：持仓是否过度分散（数不过来/说不清每只为什么在）？单标的风险占比是否超出预算？")
    return None


def _human30_brief():
    """🌱 Human 3.0 状态节（**v2 口径**：象限 Archetype/相位 + 核心问题；禁分数数字 ✗）。

    无记录返回 None（不输出空板块）。v1 的 `brief_line()` / `advice()` **不再使用** ✗
    （它们输出 `Level 2.0` / `均分 xx.x` ✗，与 §7.1 冲突；函数本体保留给旧调用点 ✓）。
    """
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from fg_system import human30 as _h30
    from fg_system.human30 import metatype as _mt
    from fg_system.human30 import render as _rd

    rec = _h30.latest()
    if not rec:
        return None
    levels = rec.get("levels") or {}
    phases = rec.get("phases") or {}
    out = ["· " + ln for ln in _rd.quadrant_lines(levels, phases)]
    out.append("· %s 核心问题：%s"
               % (_rd.AI_PREFIX,
                  _mt.deterministic_metatype(levels).get("metatype") or "未判定"))
    gap = _h30.days_since_last()
    if gap is not None and gap >= 1:
        out.append("⏰ 已断档多日未打卡（上次 %s）——记录断档，极端档位归因将缺样本"
                   % rec["date"])
    w = _h30.window_stats(7)
    if not w["no_data"]:
        lv = w["level_counts"]
        lv_txt = " / ".join(_rd.level_word(k) for k in (1, 2, 3) if lv.get(k))
        out.append("近 7 日：意识层级以 %s 为主" % (lv_txt or "未判定"))
    # 🟡 AI 复盘（H-REV-001）：明标研究参考；内部失败已降级，不阻塞简报 ✓
    try:
        from human30_review import review as _h30_review
        out.append(_h30_review(days=7))
    except Exception:
        pass
    out.append("（自评打卡：页面表单 或 scripts/human30_cli.py --set --mind .. "
               "--body .. --spirit .. --vocation ..）")
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


def _futu_health_block():
    """（兼容保留）旧入口 —— 现在走 `_data_health_block` ✓。"""
    return _data_health_block({})


#: 裁判失败时 `stage_judge` 返回的是**带原因的文案**（保留原因给用户看 ✓），
#: 但健康块不能把这种文案当成「裁判可用」✗（2026-10-29 实测：简报里明明写着
#: 「裁判调用失败」，健康块却只报「缺 情绪、归因」✗）
_JUDGE_FAIL_PREFIXES = ("裁判调用失败", "（裁判未按三行格式")


def _judge_ok(judge):
    """裁判是否真的产出了三行裁决 ✓（失败文案不算 ✗）。"""
    return bool(judge) and not str(judge).startswith(_JUDGE_FAIL_PREFIXES)


def _prev_factor_value(df, col, max_lookback=10):
    """该因子列**最近一个非空值** ⇒ `(value, 差几天)` ✓；找不到返回 `(None, 0)`。

    2026-10-31：vix/term 缺失是**数据源时滞**（CBOE 的 T 日数据在 05:30 还没发布 ✗），
    ⇒ 简报回退显示 `T-n` 的值并明确标注 ✓ —— 比「数据缺失」有用且不编造 ✓。
    """
    if col not in df.columns:
        return (None, 0)
    s = df[col].tail(max_lookback + 1)
    if s.isna().all():
        return (None, 0)
    idx = s.last_valid_index()
    if idx is None:
        return (None, 0)
    lag = int(len(s) - list(s.index).index(idx) - 1)
    try:
        return (float(s.loc[idx]), lag)
    except (TypeError, ValueError):
        return (None, 0)


def _missing_factor_count():
    """六因子里有几个算不出来 ✓（读不到就返回 0，别让健康块自己崩 ✗）。"""
    try:
        import pandas as pd

        from fg_system import config
        from fg_system.index import factor_score_summary
        row = pd.read_csv(os.path.join(config.ROOT, "Data", "features.csv")).tail(1).iloc[-1]
        s = factor_score_summary(row) or {}
        return sum(1 for v in s.values() if v.get("score") is None)
    except Exception:                                  # noqa: BLE001
        return 0


def _data_health_block(snap, sentiment=None, attribution=None, judge=None):
    """🔌 数据源健康：富途 + AI 三阶段 + 因子完整性 ✓（2026-10-29 扩展）。

    原来只报富途 ✗ —— 那次 VIX/TERM 缺、NIM 超时，这一行却只写「富途正常」✗
    ⇒ 读者以为一切都好 ✗。**缺什么就在顶部说清楚** ✓。
    """
    lines = []
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        import futu_health  # noqa: PLC0415 —— 同目录脚本，延迟导入 ✓
        st = futu_health.read_status()
    except Exception:                                  # noqa: BLE001
        st = None
    if st:
        at = str(st.get("at") or "")[:16].replace("T", " ")
        if st.get("ok"):
            lines.append("富途 OpenD：正常 ✓（%s 检查）" % at)
        else:
            lines.append("⚠️ 富途 OpenD：**不可用** —— %s（%s 检查；"
                         "持仓/成交可能停留在上一交易日 ✗ 本简报已按现有数据生成 ✓）"
                         % (st.get("reason") or "未知原因", at))
    miss = [n for n, ok in (("情绪", bool(sentiment)),
                            ("归因", bool(attribution)),
                            ("裁判", _judge_ok(judge))) if not ok]
    if miss:
        lines.append("AI 三阶段：**缺 %s** ✗（对应小节为占位）" % "、".join(miss))
    n_miss = _missing_factor_count()
    if n_miss:
        # 2026-10-31：缺失多半是**数据源时滞**（CBOE T 日数据 05:30 还没发布 ✗）
        # ⇒ 分项里会用 T-1 值并标注，这里说清「不是没有，是滞后」✓
        lines.append("六因子：**缺 %d 个**（源数据滞后，分项用 T-n 值 ✓）"
                     % n_miss)
    # 全都正常时压成**一行** ✓ —— 每天铺三行「正常」纯属占版面 ✗
    if not lines or all(ln.startswith("富途 OpenD：正常") for ln in lines):
        return "全部正常 ✓（富途 OpenD / AI 三阶段 / 六因子）"
    return "\n".join(lines)


def build_brief_sections(snap, sentiment, attribution, judge, news=None):
    """结构化简报（飞书富文本 post 用）：[ ("标题", "正文"), "hr", ... ]"""
    from fg_system import fed as _fed
    _fctx = _fed.fed_context()
    secs = []
    _warn = _freshness_block()
    if _warn:
        secs.append(("⚠️ 数据新鲜度", _warn))
        secs.append("hr")
    _ds = _data_health_block(snap, sentiment, attribution, judge)
    if _ds:
        secs.append(("🔌 数据源健康", _ds))
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
    _plan_sec = position_plan_brief(snap)
    if _plan_sec:
        secs.append(("📐 建仓/加仓计划", _plan_sec))
        secs.append("hr")
    _bc = behavior_checklist(snap)
    if _bc:
        _bc = _bc + "\n" + _PERSPECTIVE_PROMPTS
        secs.append(("🧠 行为检查清单", _bc))
        secs.append("hr")
    _h30 = _human30_brief()
    if _h30:
        secs.append(("🌱 Human 3.0 状态【自评记录】", _h30))
        secs.append("hr")
    _fbreak = _factor_breakdown()
    if _fbreak:
        secs.append(("🧩 六因子独立分项【R1.3】", _fbreak))
        secs.append("hr")
    secs.append(("🏛️ 美联储动态", _fed.fed_brief_text(_fctx)))
    secs.append("hr")
    secs.append(("📰 市场快讯", news_text(news) if news else "（新闻源不可用）"))
    secs.append("hr")
    # 2026-10-31：标题从**运行时配置**推导 ✓（硬编码会过期 ✗）
    _sent_tag = _llm_tag(HERMES_URL, HERMES_MODEL)
    _attr_tag = _llm_tag(NIM_URL, NIM_MODEL)
    secs.append(("📰 情绪面 · %s" % _sent_tag,
                 (sentiment or "（不可用）").strip()[:1200]))
    secs.append("hr")
    _mc = _major_contradiction()
    _attr_txt = (_mc + "\n\n" if _mc else "") + (attribution or "（归因生成失败，已降级跳过）").strip()[:2600]
    secs.append(("🔍 深度归因 · %s" % _attr_tag, _attr_txt))
    secs.append("hr")
    secs.append(("⚖️ 裁判裁决 · %s【研究参考】" % _attr_tag,
                 (judge or "（裁判未生成，已降级；以风控/归因结论为准）").strip()[:1200]))
    secs.append("hr")
    secs.append(("🧠 知识库观点佐证 · YouTube 9频道【研究参考】", _kb_brief_text(kb_evidence(snap))))
    secs.append("hr")
    secs.append(("📎 数据来源", _source_footnote(snap)))
    return secs


def _factor_breakdown():
    """R1.3 六因子独立分项（确定性）：features.csv 尾行逐因子 分 + 档位 + 方向。

    每因子独立 0-100 档位判定（复用 config.ZONE_EDGES 边界），不参与合成即可独立
    诊断——让简报展示「哪个因子在拉/压指数」。无数据/计算失败返回 None，不编造。
    """
    try:
        import os
        import pandas as pd
        from fg_system import config
        from fg_system.index import factor_score_summary
        path = os.path.join(config.ROOT, "Data", "features.csv")
        row = pd.read_csv(path).tail(1).iloc[-1]
        summary = factor_score_summary(row)
        if not summary:
            return None
        labels = {"vix": "VIX", "term": "TERM", "price": "PRICE",
                  "breadth": "BREADTH", "fed": "FED", "putcall": "PUT-CALL"}
        date = row.get("date")
        lines = [f"〔数据日 {date}；档位边界 20/40/60/80；权重为合成权重〕"]
        # 🔴 2026-10-31 实测：vix/term 缺失多半是**数据源时滞** ✗ ——
        # CBOE 的 T 日数据在每日链 05:30 跑时还没发布；10:22 补抓就有 10-30 ✓
        # ⇒ 回退用**最近一个非空值**并标注 `T-n` ✓
        # 比「数据缺失」有用，且**不编造**（标了差几天 ✓）
        whole = pd.read_csv(path)
        for k, s in summary.items():
            if s["score"] is None:
                prev, lag = _prev_factor_value(whole, k)
                if prev is None:
                    lines.append(f"{labels[k]:8s}  —  数据缺失")
                else:
                    lines.append(
                        f"{labels[k]:8s}  {prev:6.2f}  ←  "
                        f"**T-{lag}**（源数据未更新，非当日值 ✗）")
                continue
            arrow = "→" if s["direction"] == "贪婪向" else "↓"
            lines.append(f"{labels[k]:8s}  {s['score']:6.2f}  {arrow}  "
                         f"{s['zone_name']}（权重 {s['weight']:.3f}）")
        return "\n".join(lines)
    except Exception:
        return None


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
    # 🔴 2026-10-30 用户裁定：**按标的匹配** ✓ —— 原来用泛化主题
    # （"market sentiment psychology" / "leveraged etf risk decay"）✗
    # ⇒ 命中的全是 RaynerTeo / ChatWithTraders 的泛泛交易心理 ✗，
    #   与当天持仓毫无关系 ✗（实测 0.607/0.644 两条纯噪音 ✗）。
    queries = []
    pos = [r for r in (snap.get("positions") or []) if r.get("mv")]
    for r in sorted(pos, key=lambda x: -(x.get("mv") or 0))[:3]:
        sym0 = str(r.get("symbol") or "").upper().replace("-USDT", "")
        term = KB_SYMBOL_TERMS.get(sym0)
        if term:
            queries.append(term)
    # 全都没命中 ⇒ 回退到「杠杆 ETF 风险」这一条（保底，仍与持仓相关 ✓）
    if not queries and pos:
        queries.append("leveraged etf volatility decay risk")
    seen, hits = set(), []
    skip_titles = ("react to", "tiktok", "challenge", "try not to")
    for q in queries[:3]:
        # 2026-10-31：片段必须提到该主题的**实体词** ✓
        # （0.602 的「比特币减半科普」语义相似但不是讲持仓逻辑 ✗）
        ents = KB_QUERY_ENTITIES.get(q) or ()
        for r in search_results(q, n=4):
            key = r["title"]
            if key in seen or r["score"] < 0.45:
                continue
            if any(s in key.lower() for s in skip_titles):
                continue
            if ents:
                blob = ((r.get("snippet") or "") + " "
                        + (r.get("title") or "")).lower()
                if not any(e in blob for e in ents):
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


def _llm_tag(url, model):
    """把「URL + 模型」压成一句**人能读的通道名** ✓（2026-10-31）。

    🔴 硬编码标签会过期 ✗ —— 简报里曾长期写「Hermes(GLM)」
    「DeepSeek(NVIDIA NIM)」「OpenClaw云端(NVIDIA NIM)」，
    而实际三个通道**全部已切到 DeepSeek** ✗ ⇒ 标题误导读者 ✗。
    ⇒ 改成从**运行时配置**推导 ✓：换供应商只改环境变量，标题自动跟着变 ✓。
    """
    u = str(url or "")
    m = str(model or "")
    short = m.split("/")[-1] if m else "未知模型"
    if "deepseek.com" in u:
        return "DeepSeek（%s）" % short
    if "nvidia" in u.lower() or "nim" in u.lower():
        return "NVIDIA NIM（%s）" % short
    if "127.0.0.1" in u or "localhost" in u:
        return "本地（%s）" % short
    return short


def _kb_brief_text(hits):
    """佐证节正文（飞书富文本/Markdown 共用，压缩单条 ≤110 字）。
    片段跳过开头寒暄，从首个完整句子后取信息量部分。"""
    if not hits:
        return "（知识库不可用或未命中）"
    import re
    # 2026-10-29：**相关度阈值 0.7** ✗ —— 实测 0.607/0.644 命中过两段泛泛的
    # 交易心理（RaynerTeo / ChatWithTraders），与当天持仓毫无关系 ✗ ⇒ 宁缺毋滥 ✓
    hits = [h for h in hits if float(h.get("score") or 0) >= KB_MIN_SCORE]
    if not hits:
        return "（本次无相关度 ≥ %.1f 的知识库观点）" % KB_MIN_SCORE
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


def _date_label(snap):
    """标题日期：**指数日在前、持仓日在后** ✓（2026-10-29 用户裁定方案 ②）。

    原来只写 `snap["date"]`（持仓快照日）✗ —— 持仓同步失败那天，标题显示 10-26
    而正文的贪恐指数是 10-27 的 ✗（`verify_brief` 因此报「数据不同步」✗）。
    两个日期都写出来，谁也不冒充谁 ✓。

    指数日放**前**是有意的：`verify_brief` 取标题后第一个日期做比对 ✓
    ⇒ 现在取到的就是指数数据日，与 features 尾行一致，那条 WARN 自然消失 ✓。
    """
    idx = str(snap.get("index_date") or "")
    pos = str(snap.get("date") or "")
    if idx and pos and idx != pos:
        return "%s（指数）/ %s（持仓）" % (idx, pos[5:])
    return idx or pos


def build_brief(snap, sentiment, attribution, judge, news=None):
    from fg_system import fed as _fed
    _fctx = _fed.fed_context()
    _warn = _freshness_block()
    lines = [
        f"# 多智能体投研简报 {_date_label(snap)}",
        "",
    ]
    if _warn:
        lines += ["## ⚠️ 数据新鲜度", _warn, "", "---", ""]
    # 2026-10-29：md 版也带上健康块 ✗ —— 原来只有飞书富文本有，
    # 归档的 .md 看不到「缺什么」✗
    lines += ["## 🔌 数据源健康",
              _data_health_block(snap, sentiment, attribution, judge), "", "---", ""]
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
    _plan_sec = position_plan_brief(snap)
    if _plan_sec:
        lines += ["## 📐 建仓/加仓计划【研究参考】", _plan_sec, ""]
    _bc = behavior_checklist(snap)
    if _bc:
        _bc = _bc + "\n" + _PERSPECTIVE_PROMPTS
        lines += ["## 🧠 行为检查清单【研究参考】", _bc, ""]
    lines += [
        "## 🏛️ 美联储动态",
        _fed.fed_brief_text(_fctx),
        "",
        "## 市场快讯",
        news_text(news) if news else "（新闻源不可用）",
        "",
        "## 情绪面分析（%s）" % _llm_tag(HERMES_URL, HERMES_MODEL),
        (sentiment or "（跳过：Hermes 不可用）").strip()[:1500],
        "",
        "## 深度归因（%s）" % _llm_tag(NIM_URL, NIM_MODEL),
        ((_major_contradiction() or "") + "\n\n" if _major_contradiction() else "")
        + (attribution or "（跳过：%s 不可用）"
           % _llm_tag(NIM_URL, NIM_MODEL)).strip()[:3000],
        "",
        "## 裁判裁决（%s）【研究参考，非实盘指令】"
        % _llm_tag(NIM_URL, NIM_MODEL),
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


#: 单个 AI 阶段的上限（秒）✓ —— 超了就**降级跳过**，不许拖死整条简报 ✗
#: 2026-10-29 实测：三个阶段并发仍突破 600 秒 ⇒ 说明有阶段会长时间挂住 ✗。
STAGE_TIMEOUT = 240


def _run_stages(snap, kb=None):
    """并发跑三个**互不依赖**的阶段：新闻 / Hermes 情绪 / NIM 归因 ✓。

    🔴 `stage_judge` **不能**并发 ✗ —— 它的入参就是 `sentiment` 与 `attribution`
    的产出（裁判要在两者之上做判断）⇒ 必须等它们回来 ✓。

    2026-10-29 实测：一次简报 **478 秒**，绝大部分耗在这三个串行等待上 ✗
    （每个阶段都是一次 2~3 分钟的 LLM 调用）。三个并行后只剩**最慢那个**的时长 ✓。

    每个阶段还有 **`STAGE_TIMEOUT` 上限** ✓ —— 超了就降级为 None（简报照发，
    写「（跳过：X 超时）」）✗ 而不是把整条链拖死 ✗（2026-10-29 实测并发版仍破 600s ✗）。

    失败语义与串行版完全一致 ✓：任何一个阶段抛错 ⇒ 只把该阶段置 None 并打一行日志，
    其余阶段照常 ✓（下游 `build_brief_sections` 会写「（跳过：X 不可用）」占位 ✓）。
    """
    def _log(line):
        """阶段级日志落盘 ✓ —— 被外层超时杀掉时**还能知道卡在哪一步** ✗。

        2026-10-29 实测：队列动作 600 秒超时，`subprocess` 杀进程 ⇒ stdout 全丢 ✗
        ⇒ 只知道「超时」，不知道卡在新闻还是 LLM ✗。

        🔴 必须**串行写** ✗ —— 三个线程同时 `open(..., "a")` 在 Windows 上会
        偶发 sharing violation（PermissionError）⇒ 被 `except OSError` 吞掉
        ⇒ 日志少一行 ✗（2026-10-29 测试实测：`done 新闻抓取` 时有时无 ✗）。
        """
        try:
            d = os.path.join(REPO, "Data", "health")
            os.makedirs(d, exist_ok=True)
            with _LOG_LOCK:
                with open(os.path.join(d, "invest_stages.log"), "a",
                          encoding="utf-8") as fh:
                    fh.write("%s %s\n" % (time.strftime("%H:%M:%S"), line))
        except OSError:
            pass

    def _guarded(label, fn):
        _log("start %s" % label)
        try:
            r = fn()
            _log("done  %s" % label)
            return r
        except Exception as exc:                       # noqa: BLE001
            _log("fail  %s: %s" % (label, exc))
            print("%s失败: %s" % (label, exc))
            return None

    jobs = {
        "news": ("新闻抓取", lambda: fetch_news(snap)),
        "sentiment": ("Hermes 阶段", lambda: stage_sentiment(_read_hermes_key(), snap)),
        "attribution": ("NIM 阶段",
                        lambda: stage_attribution(_read_llm_key(), snap, kb=kb)),
    }
    # 端口预检 ✓ —— 三个阶段各自的本机入口，服务没起就**秒跳过** ✗
    # （2026-10-29：代理恢复后仍 240s 超时 ⇒ 「网络通」不等于「服务在」✗）
    down = {}
    if HERMES_ADDR and not _port_ok(*HERMES_ADDR):
        down["sentiment"] = "Hermes %s:%d 未监听" % HERMES_ADDR
    if PROXY_ADDR and not _port_ok(*PROXY_ADDR):
        down["attribution"] = "代理 %s 未监听" % PROXY
    for _k, _why in down.items():
        _log("skip  %s: %s" % (_k, _why))
        print("[preflight] %s ⇒ %s，跳过（不耗阶段超时）" % (_k, _why))
    jobs = {k: v for k, v in jobs.items() if k not in down}

    # 🔴 2026-10-29 用户裁定：**单阶段卡住就降级跳过** ✗，不许拖死整条简报 ✗
    # 用 daemon 线程而不是 ThreadPoolExecutor ✗ —— 后者退出时会 join 所有
    # 未完成线程 ⇒ 一个挂死的 HTTP 调用照样把进程拖住 ✗（Python 无法杀线程 ✓，
    # 只能不 join + daemon，让进程能正常退 ✓）。
    # 记下这次用的代理 ✓ —— 下次再超时，一眼能看出是不是代理/端口的问题 ✗
    _log("proxy=%s stage_timeout=%ds" % (PROXY or "(none)", STAGE_TIMEOUT))
    out, timed_out = {}, set()

    def _worker(key, label, fn):
        out[key] = _guarded(label, fn)

    threads = []
    for key, (label, fn) in jobs.items():
        t = threading.Thread(target=_worker, args=(key, label, fn), daemon=True)
        t.start()
        threads.append((key, label, t))

    deadline = time.time() + STAGE_TIMEOUT
    for key, label, t in threads:
        t.join(max(0.0, deadline - time.time()))
        if t.is_alive():
            timed_out.add(key)
            _log("timeout %s (>%ds) ⇒ 降级跳过" % (label, STAGE_TIMEOUT))
            print("%s超时（>%ds）⇒ 降级跳过" % (label, STAGE_TIMEOUT))
    return tuple(None if k in timed_out else out.get(k)
                 for k in ("news", "sentiment", "attribution"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只产出简报不推送飞书")
    ap.add_argument("--kb", default=None, help="L3.5 可选引用知识库观点（如 '杠杆ETF 风险管理'；注入归因参考，不改判决）")
    args = ap.parse_args()

    snap = build_snapshot()
    # 文件名按**指数数据日** ✓（那才是这份简报在讲的那天）；
    # 持仓日落后时不再出现「10-27 的简报存成 10-26」✗
    # ⚠️ 括号不能省 ✗ —— `/` 与 `%` 同优先级且左结合 ⇒ `REPO / "…%s" % x`
    # 会先算 `(Path) % x`（TypeError: Path % str ✗）
    brief_path = REPO / "Data" / ("invest_brief_%s.md" % (
        snap.get("index_date") or snap["date"]))

    judge = None
    # 2026-10-29：三个独立阶段并发 ✓（串行时一次简报 478 秒 ✗）
    news, sentiment, attribution = _run_stages(snap, kb=args.kb)
    # 裁判也走 NIM 通道 ⇒ 代理端口没起就秒跳过 ✓（别白等 180 秒 ✗）
    if PROXY_ADDR and not _port_ok(*PROXY_ADDR):
        print("[preflight] 代理 %s 未监听 ⇒ 跳过裁判阶段" % PROXY)
    else:
        try:
            judge = stage_judge(_read_llm_key(), snap,
                                sentiment or "（无）", attribution or "（无）")
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
    # 🔴 2026-10-29：**任一阶段缺失也照发** ✓ —— `build_brief_sections` 早就给每个
    # 缺失阶段写了「（跳过：X 不可用）」占位 ✓，这里却把**整条简报**都扣下不发 ✗
    # ⇒ 用户连续两天收不到简报、且没有任何提示 ✗（与模块 docstring
    # 「任一阶段失败自动降级」自相矛盾 ✗）。只在**三个全缺**时留一行日志 ✓。
    if not (sentiment or attribution or judge):
        print("[degrade] 三个 AI 阶段全缺 ⇒ 仍按占位版本推送（不再静默不发）")
    ok, msg = push_feishu_rich(f"📊 多智能体投研简报 {_date_label(snap)}",
                               build_brief_sections(snap, sentiment, attribution, judge, news))
    print(f"飞书富文本推送: {'成功' if ok else f'失败 {msg}'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
