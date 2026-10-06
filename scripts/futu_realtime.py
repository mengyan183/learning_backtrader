#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""富途实时行情订阅服务（常驻后台，launchd 开机自启）。

能力（对应 2026-10-05 用户批准的增强顺序）：
1. 持仓标的 + QQQ 实时行情订阅（KLINE_1M 主通道，回调失败自动降级轮询 snapshot）
   → 实时写 Data/realtime_state.json（现价/当日涨跌%/更新时间）。
2. 盘中指数预览：用实时 QQQ 重算 price 因子，其余因子取 features 尾行，
   合成"预览指数"（标注预览，绝不写 features.csv / signals）。
3. 盘中异动 → 新闻联动飞书告警：当日涨跌 |x| ≥ 5%（env RT_ALERT_PCT 可配）
   触发 get_search_news 归因 + push_feishu；每标的 60 分钟去重节流。

用法：
  .venv/bin/python scripts/futu_realtime.py            # 前台运行（launchd 用）
  环境变量：FG_REALTIME_OFF=1 可一键关闭（launchd 里配合使用）。

依赖：futu-api + 本机 FutuOpenD(127.0.0.1:11111) + 美股行情权限。
非交易时段无新 K 线，状态文件保持最后值，属正常。
"""
import json
import os
import sys
import time
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

STATE_PATH = os.path.join(REPO, "Data", "realtime_state.json")
ALERT_PCT = float(os.environ.get("RT_ALERT_PCT", "5.0"))
ALERT_COOLDOWN = 3600  # 每标的小时级去重
SYMBOL_CODES = {}      # {"QQQ": "US.QQQ", ...} 运行时填充
state = {}             # 模块级共享状态（回调线程 + 主循环 + 告警）


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"updated": None, "prices": {}, "preview_index": None, "alerts": {}}


def save_state(state):
    state["updated"] = now_iso()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def holding_symbols():
    """positions.csv 最新快照的美股 symbol（去 -USDT 加密；富途无 BTC 现货）。"""
    import pandas as pd
    p = os.path.join(REPO, "Data", "positions.csv")
    syms = []
    if os.path.exists(p):
        pos = pd.read_csv(p, parse_dates=["date"])
        pos = pos[pos["date"] == pos["date"].max()]
        for s in pos["symbol"]:
            s = str(s).replace("-USDT", "")
            if s not in ("BTC", "ETH"):
                syms.append(s)
    syms += ["QQQ"]  # 指数预览需要
    return sorted(set(syms))


# ---------------------------------------------------------------- 行情回调
def subscribe_kline():
    """KLINE_1M 订阅（主通道）。返回 ctx；回调线程更新 state。"""
    import futu
    ctx = futu.OpenQuoteContext(host="127.0.0.1", port=11111)

    class KLine(futu.CurKlineHandlerBase):
        def on_recv_cur_kline(self, data):
            if data.empty:
                return
            sym = str(data.iloc[-1]["code"]).replace("US.", "", 1)
            row = data.iloc[-1]
            close = float(row["close"])
            prev = float(row.get("prev_close", 0) or 0)
            chg = (close / prev - 1) * 100 if prev else None
            st = state["prices"].get(sym, {})
            st.update({"price": round(close, 4), "day_chg_pct": round(chg, 2)
                       if chg is not None else st.get("day_chg_pct"),
                       "ts": now_iso()})
            state["prices"][sym] = st
            check_alert(sym, st)

    codes = [SYMBOL_CODES[s] for s in holding_symbols() if s in SYMBOL_CODES]
    for c in codes:
        ret, msg = ctx.subscribe([c], ["K_1M"], subscribe_push=True)
        if ret != 0:
            print(f"[rt] subscribe 失败 {c}: {msg}")
    ctx.set_handler(KLine())
    return ctx


def snapshot_fallback():
    """降级通道：get_market_snapshot 轮询（订阅无数据时每 15s 拉一次快照）。"""
    import futu
    ctx = futu.OpenQuoteContext(host="127.0.0.1", port=11111)
    while True:
        try:
            ret, df = ctx.get_market_snapshot([SYMBOL_CODES[s] for s in holding_symbols()
                                               if s in SYMBOL_CODES])
            if ret == 0 and not df.empty:
                for _, r in df.iterrows():
                    sym = str(r["code"]).replace("US.", "", 1)
                    price = float(r.get("last_price", 0) or 0)
                    prev = float(r.get("prev_close_price", 0) or 0)
                    chg = (price / prev - 1) * 100 if prev else None
                    st = state["prices"].get(sym, {})
                    st.update({"price": round(price, 4),
                               "day_chg_pct": round(chg, 2) if chg is not None
                               else st.get("day_chg_pct"), "ts": now_iso()})
                    state["prices"][sym] = st
                    check_alert(sym, st)
                save_state(state)
        except Exception as e:
            print(f"[rt] snapshot 轮询异常: {e}")
        time.sleep(15)


# ---------------------------------------------------------------- 交易时段
def _us_now():
    """美东当前时间（America/New_York）。"""
    from zoneinfo import ZoneInfo
    from datetime import datetime
    return datetime.now(ZoneInfo("America/New_York"))


def _in_trading_hours():
    """美股常规交易时段判定：周一至周五 09:30–16:00（美东）。

    盘前/盘后/周末 snapshot 的 last_price 仍是上一交易日收盘价，
    算出的 day_chg 是**历史涨跌**而非当下异动（2026-10-05 盘前误报根因）。
    仅在交易时段内做盘中异动告警。
    """
    now = _us_now()
    if now.weekday() >= 5:      # 周六/周日
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


# ---------------------------------------------------------------- 指数预览
def preview_index():
    """用实时 QQQ 重算 price 因子，其余因子取 features 尾行 → 预览指数。

    当预览与收盘差异显著（|delta| ≥ 2）且当日未生成过归因时，
    调 NVIDIA NIM 生成一句话归因（每日至多 1 次，节流）。
    """
    import numpy as np
    import pandas as pd
    from fg_system import config, index as index_mod, pipeline
    from fg_system.factors.price import PriceFactor
    rt = state["prices"].get("QQQ", {}).get("price")
    if rt is None:
        return None
    try:
        wide = pipeline.load_wide()
        wide.loc[wide.index[-1], ("QQQ", "close")] = float(rt)
        price_score = float(PriceFactor().score(wide).iloc[-1])
        feat = pd.read_csv(config.FEATURES_PATH)
        last = feat.iloc[-1]
        scores = pd.DataFrame([{
            "vix": float(last["vix"]), "term": float(last["term"]),
            "breadth": float(last["breadth"]), "fed": float(last["fed"]),
            "price": price_score,
        }])
        fg = float(index_mod.combine(scores).iloc[0])
        zone = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"][
            int(np.clip(np.searchsorted([20, 40, 60, 80], fg, side="right"), 0, 4))]
        closed = float(last["fg_index"])
        out = {"fg_index": round(fg, 1), "zone": zone,
               "closed_index": round(closed, 1),
               "delta": round(fg - closed, 1),
               "ts": now_iso()}
        # NIM 归因：|delta|≥2 且当日未生成过
        day = _us_now().strftime("%Y-%m-%d")
        if abs(out["delta"]) >= 2 and state.get("nim_reason_date") != day:
            reason = _nim_preview_reason(out, scores.iloc[0], last)
            if reason:
                out["reason"] = reason
                state["nim_reason_date"] = day
        return out
    except Exception as e:
        print(f"[rt] 预览指数失败: {e}")
        return None


def _nim_preview_reason(preview, factor_row, feat_last):
    """NVIDIA NIM 一句话归因（复用 invest_research 的 NIM 通道）。"""
    try:
        from scripts.invest_research import (NIM_URL, NIM_MODEL, PROXY, _chat,
                                            _read_nim_key)
        movers = [f"{k} {v.get('day_chg_pct'):+.1f}%" for k, v in
                  state["prices"].items() if isinstance(v, dict)
                  and v.get("day_chg_pct") is not None
                  and abs(v.get("day_chg_pct", 0)) >= 3]
        system = "你是贪恐指数归因分析师，擅长一句话讲清指数盘中变化的主驱动。"
        user = (f"收盘指数 {preview['closed_index']}（{preview['zone']}），"
                f"盘中预览 {preview['fg_index']}（Δ{preview['delta']:+.1f}）。"
                f"因子分：vix={factor_row['vix']:.1f}, term={factor_row['term']:.1f}, "
                f"price={factor_row['price']:.1f}, breadth={factor_row['breadth']:.1f}, "
                f"fed={factor_row['fed']:.1f}。异动标的：{'、'.join(movers) or '无'}。"
                "一句话归因（≤80字，直接给结论，不解释过程）：")
        out = _chat(NIM_URL, _read_nim_key(), NIM_MODEL, system, user,
                    max_tokens=200, proxy=PROXY, timeout=90, retries=1)
        return (out or "").strip().replace("\n", " ")[:120]
    except Exception as e:
        print(f"[rt] NIM 归因失败: {e}")
        return None


# ---------------------------------------------------------------- OKX 实时 BTC
def okx_ticker_loop():
    """OKX WebSocket 订阅 BTC-USDT tickers（公共行情，免 key）。

    富途无 BTC 现货，加密持仓用 OKX 实时价补齐（2026-10-05 延伸）。
    断线自动重连；心跳保持连接。
    """
    import websocket
    url = "wss://ws.okx.com:8443/ws/v5/public"
    while True:
        try:
            ws = websocket.WebSocket()
            ws.connect(url, timeout=30,
                       http_proxy_host="127.0.0.1", http_proxy_port=7890,
                       header={"User-Agent": "fg-realtime/1.0"})
            ws.send(json.dumps({"op": "subscribe",
                                "args": [{"channel": "tickers", "instId": "BTC-USDT"}]}))
            last_ping = time.time()
            while True:
                ws.settimeout(30)
                raw = ws.recv()
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8")
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("event") == "error":
                    print(f"[okx] 订阅错误: {msg.get('code')} {msg.get('msg')}")
                    break
                data = msg.get("data") or []
                for d in data:
                    if d.get("instId") != "BTC-USDT":
                        continue
                    last = float(d.get("last") or 0)
                    open24 = float(d.get("open24h") or 0)
                    chg = (last / open24 - 1) * 100 if open24 else None
                    state.setdefault("prices", {})["BTC"] = {
                        "price": round(last, 2),
                        "day_chg_pct": round(chg, 2) if chg is not None else None,
                        "ts": now_iso(), "source": "OKX",
                    }
                    save_state(state)
                if time.time() - last_ping > 20:   # 心跳
                    ws.send("ping")
                    last_ping = time.time()
        except Exception as e:
            print(f"[okx] 连接断开: {e}，5s 后重连")
        time.sleep(5)


# ---------------------------------------------------------------- 异动告警
_ALERT_KB_THEMES = {
    "YINN": "china leveraged etf",
    "GDXU": "gold miners etf",
    "CONL": "bitcoin leveraged etf",
    "CRCG": "crypto leveraged etf",
    "AXTX": "leveraged etf",
}


def _alert_kb_query(sym):
    """异动标的 → 知识库检索主题（未映射标的用通用个股风险）。"""
    return _ALERT_KB_THEMES.get(sym, f"{sym} stock trading risk")


def check_alert(sym, st):
    """盘中异动告警。**仅交易时段判定**：盘前/盘后/周末 snapshot 的
    day_chg 是上一交易日涨跌，不触发（2026-10-05 盘前误报根因）。"""
    if not _in_trading_hours():
        return
    chg = st.get("day_chg_pct")
    if chg is None or abs(chg) < ALERT_PCT:
        return
    alerts = state.get("alerts", {})
    last_ts = alerts.get(sym)
    if last_ts and time.time() - last_ts < ALERT_COOLDOWN:
        return
    try:
        from futu import OpenQuoteContext
        q = OpenQuoteContext(host="127.0.0.1", port=11111)
        ret, data = q.get_search_news(sym, max_count=2)
        titles = [str(t).strip() for t in data["title"].tolist()] if ret == 0 and len(data) else []
        q.close()
        news_txt = ("；相关新闻：" + " / ".join(titles[:2])) if titles else ""
    except Exception as e:
        print(f"[rt] 告警新闻抓取失败 {sym}: {e}")
        news_txt = ""
    from scripts.invest_research import push_feishu, kb_note
    kb_txt = kb_note(_alert_kb_query(sym))
    kb_line = (kb_txt + "\n") if kb_txt else ""
    msg = (f"⚠️ 盘中异动 {sym} {chg:+.1f}%（实时价 {st.get('price')}，"
           f"{st.get('ts', '')[:16]}）{news_txt}\n"
           f"{kb_line}"
           f"数据源：富途实时订阅 · 仅供研究，不构成操作指令")
    ok, m = push_feishu(msg)
    print(f"[rt] 告警 {sym} {chg:+.1f}% push={ok} {m if not ok else ''}")
    state.setdefault("alerts", {})[sym] = time.time()
    save_state(state)


# ---------------------------------------------------------------- 主循环
def _acquire_single_instance():
    """flock 单实例锁：拿不到即退出（防 launchd/手动多实例重复告警）。"""
    import fcntl
    lock_path = "/tmp/fg_realtime.lock"
    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[rt] 已有实例在运行，退出")
        sys.exit(0)
    return fd


def main():
    _acquire_single_instance()
    if os.environ.get("FG_REALTIME_OFF") == "1":
        print("[rt] FG_REALTIME_OFF=1，退出")
        return
    global SYMBOL_CODES, state
    state = load_state()
    syms = holding_symbols()
    SYMBOL_CODES = {s: "US." + s for s in syms}
    print(f"[rt] 订阅标的: {syms}")

    from futu import OpenQuoteContext
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    # 先拉一次初始快照，让状态文件立即有值
    ret, df = ctx.get_market_snapshot([SYMBOL_CODES[s] for s in syms])
    if ret == 0 and not df.empty:
        for _, r in df.iterrows():
            sym = str(r["code"]).replace("US.", "", 1)
            price = float(r.get("last_price", 0) or 0)
            prev = float(r.get("prev_close_price", 0) or 0)
            chg = (price / prev - 1) * 100 if prev else None
            st = state["prices"].get(sym, {})
            st.update({"price": round(price, 4),
                       "day_chg_pct": round(chg, 2) if chg is not None else None,
                       "ts": now_iso()})
            state["prices"][sym] = st
            check_alert(sym, st)
        save_state(state)
        print("[rt] 初始快照已写入 realtime_state.json")

    # 订阅 KLINE_1M 并启动回调线程
    ctx = subscribe_kline()
    ctx.start()

    # OKX 实时 BTC（富途无 BTC 现货）
    import threading
    threading.Thread(target=okx_ticker_loop, daemon=True).start()
    print("[rt] OKX BTC 实时线程已启动")

    # 主线程：每 60s 保存状态 + 重算预览指数；订阅无数据时 180s 无更新则降级轮询
    last_snapshot = time.time()
    no_update_since = time.time()
    try:
        while True:
            time.sleep(60)
            for sym, st in list(state.get("prices", {}).items()):
                if isinstance(st, dict):
                    check_alert(sym, st)
            save_state(state)
            pi = preview_index()
            if pi:
                state["preview_index"] = pi
                save_state(state)
                print(f"[rt] 预览指数 {pi['fg_index']} {pi['zone']} (收盘 {pi['closed_index']}, Δ{pi['delta']:+.1f})")
            # 兜底：若最近 180s 内回调无任何更新，切 snapshot 轮询线程
            any_new = any(
                (time.time() - _ts_of(v)) < 180
                for v in state["prices"].values() if isinstance(v, dict)
            )
            if not any_new and time.time() - last_snapshot > 180:
                print("[rt] 订阅无新数据，降级 snapshot 轮询")
                import threading
                threading.Thread(target=snapshot_fallback, args=(),
                                 daemon=True).start()
                last_snapshot = time.time()
    except KeyboardInterrupt:
        print("[rt] 退出")
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def _ts_of(v):
    try:
        return datetime.fromisoformat(v.get("ts", "1970-01-01")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


if __name__ == "__main__":
    main()
