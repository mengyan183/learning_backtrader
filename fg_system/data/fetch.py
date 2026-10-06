# -*- coding: utf-8 -*-
"""数据抓取：Nasdaq 官方 API（价格）+ CBOE cdn（VIX/VIX3M）。

数据源实测结论见设计文档 §4.1。请求逻辑可直接复用 scripts/fetch_market_data.py。
"""
import json
import os
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

from fg_system import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

PRICE_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume"]
INDEX_COLUMNS = ["date", "open", "high", "low", "close"]


_OPENER = {}           # {"direct": opener, "proxy": opener}
_LAST_CALL = [0.0]        # 上次请求时刻（单调时钟）；**模块级**，跨调用生效


def _opener(url=None):
    """复用同一个 opener（原实现每次请求都新建，含 SSL 上下文）。

    **按域名分流代理**（2026-10-06 修复数据停更）：config.PROXY 默认是
    **公司代理**（10.30.6.49:9090），家里 Mac 访问不到；nasdaq/cboe/
    alternative.me 国内**直连即可**。只有 `config.PROXY_HOSTS` 白名单内的
    域名（如 okx.com）才走代理，其余一律直连 —— 避免把「拉不到价格」的
    故障从一个网络环境带进另一个。
    """
    global _OPENER
    host = urllib.parse.urlparse(url).hostname if url else None
    use_proxy = bool(host and config.PROXY and any(
        h in host for h in config.PROXY_HOSTS))
    key = "proxy" if use_proxy else "direct"
    cached = _OPENER.get(key)
    if cached is None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # ProxyHandler({}) = 显式不用代理
        proxies = ({"http": config.PROXY, "https": config.PROXY} if use_proxy else {})
        cached = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            urllib.request.HTTPSHandler(context=ctx),
        )
        _OPENER[key] = cached
    return cached


def _throttle(clock=None, sleep=None):
    """请求**前**强制最小间隔（第 12.14 条）。

    为什么必须节流：实测连续抓 12 个标的时从第 8 个起全部失败（**连 SPY 都失败**），
    是数据源**限流**而非无数据。原实现只在**失败后**固定 sleep 2 秒，对
    「成功但过于密集」的请求毫无作用——而限流恰恰由密集的**成功**请求触发。

    `clock` / `sleep` 可注入，便于测试（默认取 `time.monotonic` / `time.sleep`）。
    """
    clock = time.monotonic if clock is None else clock
    sleep = time.sleep if sleep is None else sleep
    wait = config.FETCH_MIN_INTERVAL - (clock() - _LAST_CALL[0])
    if wait > 0:
        sleep(wait)
    _LAST_CALL[0] = clock()


def _backoff(attempt, rng=None):
    """指数退避 + 抖动（第 12.14 条）。

    抖动取 **[50%, 100%]** 区间：避免多次重试/多个进程同时打过去（惊群）。
    """
    rng = random.random if rng is None else rng
    base = min(config.FETCH_BACKOFF_BASE * (2 ** attempt), config.FETCH_BACKOFF_MAX)
    return base * (0.5 + rng() * 0.5)


def _get(url, retries=None):
    """带**请求前节流**与**指数退避重试**的 GET。

    404 视为**永久失败**立即放弃（重试无意义，只会浪费限流额度）。
    """
    retries = config.FETCH_RETRIES if retries is None else retries
    last = None
    for i in range(retries):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with _opener(url).open(req, timeout=35) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404:
                break
            time.sleep(_backoff(i))
        except Exception as exc:      # 网络类异常统一重试
            last = exc
            time.sleep(_backoff(i))
    raise RuntimeError("请求失败 %s: %s" % (url, last))


# ================================================================ 守猪待兔 partner API
# 契约与参数见 config.SHOUTU_API_* 与 docs/trading-discipline.md 第 14.5 条。

def _post_form(url, fields, headers=None, retries=None):
    """带**请求前节流**与**指数退避重试**的 POST（`application/x-www-form-urlencoded`）。

    与 `_get` 的分工：守猪待兔 partner API 需要 body 与自定义 header（`X-Auth`）。
    实测确认 `urlencoded` 即可，**不需要 multipart/form-data**（文档写的是 "form-data"）。

    **报错信息绝不包含 headers** —— 里面是会员激活码。同 `shoutu.load_token` 的
    原则：否则密钥会随报错进入终端记录与日志（第 14.5 条）。
    """
    retries = config.FETCH_RETRIES if retries is None else retries
    body = urllib.parse.urlencode(fields).encode("utf-8")
    hdr = {"User-Agent": UA, "Accept": "*/*",
           "Content-Type": "application/x-www-form-urlencoded"}
    hdr.update(headers or {})
    last = None
    for i in range(retries):
        _throttle()
        try:
            req = urllib.request.Request(url, data=body, headers=hdr, method="POST")
            with _opener(url).open(req, timeout=35) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404:
                break
            time.sleep(_backoff(i))
        except Exception as exc:      # 网络类异常统一重试
            last = exc
            time.sleep(_backoff(i))
    raise RuntimeError("POST 失败 %s: %s" % (url, last))


def fetch_shoutu_score(symbol, lever, emo_area):
    """调用守猪待兔 partner API 取**单标的**贪恐值，返回原始 payload dict。

    密钥经 `shoutu.load_token()`（环境变量 `SHOUTU_TOKEN` 优先）读取 ——
    **源码树中永不出现密钥**。

    **`emo_area` 必须逐标的对应**（`config.SHOUTU_API_PARAMS`）：它决定服务端
    用哪个贪恐模型，填错**不报错、只给错值**（第 14.5 条 §2）。
    """
    from fg_system.data import shoutu          # 局部导入避免循环依赖
    payload = _post_form(
        config.SHOUTU_API_URL,
        {"code": "US." + symbol, "lever": str(lever), "emo_area": emo_area},
        headers={"X-Auth": shoutu.load_token()},
    )
    return json.loads(payload.decode("utf-8"))


def _num(value):
    """剥离 Nasdaq 的 $ 与千分位后转 float。etf 与 stocks 两种格式通用。"""
    return float(str(value).replace(",", "").replace("$", ""))


def parse_nasdaq_rows(rows, symbol):
    """解析 Nasdaq tradesTable.rows。字段顺序：date,close,volume,open,high,low。

    注意：`assetclass=etf` 的价格不带 `$`，`assetclass=stocks` 的**所有价格字段都带 `$`**
    （实测 MSTR/COIN）。因此三个价格字段都必须剥离 `$`，否则 stocks 格式的每一行
    都会在 float() 处抛 ValueError 被静默 skip，返回空表。
    """
    recs = []
    for r in rows:
        try:
            recs.append({
                "date": pd.to_datetime(r["date"], format="%m/%d/%Y"),
                "symbol": symbol,
                "open": _num(r["open"]),
                "high": _num(r["high"]),
                "low": _num(r["low"]),
                "close": _num(r["close"]),
                "volume": float(str(r["volume"]).replace(",", "") or 0),
            })
        except (ValueError, KeyError, TypeError):
            continue
    if not recs:
        # 空数据必须返回带列名的空表。真实场景：本地数据已是最新时，Nasdaq 对未来
        # 日期返回 0 行；此时若无条件 sort_values("date") 会因无列而抛 KeyError。
        return pd.DataFrame(columns=PRICE_COLUMNS)
    return pd.DataFrame(recs).sort_values("date").reset_index(drop=True)


def fetch_symbol(symbol, limit=9999, fromdate="2010-01-01"):
    """抓取单标的日线。

    **`assetclass` 必须回退 etf → stocks**：Nasdaq 对 ETF 用 `assetclass=etf`，
    对**个股**用 `assetclass=stocks`。原实现硬编码 `etf`，导致个股（实测
    **AXTI / CRCL**）返回空表，被上层误判为「该标的无数据」。
    能抓到 MSTR / COIN 只是因为 Nasdaq 也把它们归在 etf 下，不具普遍性。

    回退是**严格改进**：`etf` 有数据时行为完全不变；只有 `etf` 返回空表时才多试一次。
    """
    last_err = None
    for assetclass in ("etf", "stocks"):
        url = "%s?assetclass=%s&fromdate=%s&limit=%d" % (
            config.NASDAQ_API.format(symbol=urllib.parse.quote(symbol)),
            assetclass, fromdate, limit)
        try:
            data = json.loads(_get(url).decode("utf-8"))
        except RuntimeError as exc:
            last_err = exc
            continue
        rows = ((data.get("data") or {}).get("tradesTable") or {}).get("rows") or []
        df = parse_nasdaq_rows(rows, symbol)
        if not df.empty:
            return df
    if last_err is not None:
        raise last_err
    return pd.DataFrame(columns=PRICE_COLUMNS)


def fetch_cboe_index(name):
    """下载 CBOE 指数历史 CSV（VIX / VIX3M），返回 date,open,high,low,close。"""
    url = config.CBOE_CDN.format(name=name)
    text = _get(url).decode("utf-8", errors="replace")
    lines = [l for l in text.splitlines() if l.strip()]
    start = next((i for i, l in enumerate(lines) if l.upper().startswith("DATE,")), 0)
    rows = [l.split(",") for l in lines[start + 1:]]
    recs = []
    for r in rows:
        try:
            recs.append({
                "date": pd.to_datetime(r[0].strip(), format="%m/%d/%Y"),
                "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
            })
        except (ValueError, IndexError):
            continue
    if not recs:
        return pd.DataFrame(columns=INDEX_COLUMNS)
    return pd.DataFrame(recs).sort_values("date").reset_index(drop=True)


def missing_ranges(existing, symbol):
    """返回该标的需要抓取的起始日期（本地最大日期的下一天）。"""
    if existing is None or existing.empty:
        return None, None
    sub = existing[existing["symbol"] == symbol]
    if sub.empty:
        return None, None
    return sub["date"].max() + pd.Timedelta(days=1), None


def merge_incremental(old, new):
    """追加去重排序，保证幂等（§4.2）。"""
    if old is None or old.empty:
        return new.sort_values(["symbol", "date"]).reset_index(drop=True)
    if new is None or new.empty:
        return old.sort_values(["symbol", "date"]).reset_index(drop=True)
    merged = pd.concat([old, new], ignore_index=True)
    return (merged.drop_duplicates(subset=["symbol", "date"], keep="last")
            .sort_values(["symbol", "date"]).reset_index(drop=True))


def update_prices(path=None, symbols=None, sleep=1.0):
    """增量更新价格文件。返回 (合并后 DataFrame, 各标的本次新增行数)。

    增量语义：本地已有该标的时，只请求 missing_ranges 给出的起始日期之后的数据
    （Nasdaq 的 fromdate 参数生效，见设计文档 §4.1）；本地没有该标的时从
    NDAQ_FROMDATE（2010-01-01）全量拉取。这样每日更新只需传输极少量数据。
    """
    path = path or os.path.join(config.RAW_DIR, "prices.csv")
    symbols = symbols or config.FETCH_SYMBOLS
    old = pd.DataFrame()
    if os.path.exists(path):
        old = pd.read_csv(path, dtype={"symbol": str}, parse_dates=["date"])

    before_counts = {sym: (len(old[old["symbol"] == sym]) if not old.empty else 0)
                     for sym in symbols}

    frames = []
    for sym in symbols:
        start, _ = missing_ranges(old, sym)
        fromdate = start.strftime("%Y-%m-%d") if start is not None else "2010-01-01"
        frames.append(fetch_symbol(sym, fromdate=fromdate))
        time.sleep(sleep)

    merged = merge_incremental(old, pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged.to_csv(path, index=False, encoding="utf-8")

    # added 必须按「合并后的实际新增行数」统计。注意 fresh 是**增量窗口**而非累计量，
    # 用 len(fresh) - before 在增量语义下会得到错误（甚至负数）的计数。
    added = {sym: len(merged[merged["symbol"] == sym]) - before_counts[sym] for sym in symbols}
    return merged, added


def update_indices(raw_dir=None):
    """增量更新 vix.csv / vix3m.csv。"""
    raw_dir = raw_dir or config.RAW_DIR
    os.makedirs(raw_dir, exist_ok=True)
    out = {}
    for name, fname in [("VIX", "vix.csv"), ("VIX3M", "vix3m.csv")]:
        df = fetch_cboe_index(name)
        df.to_csv(os.path.join(raw_dir, fname), index=False, encoding="utf-8")
        out[name] = len(df)
    return out


# ================================================================ v2 加密数据源

FNG_COLUMNS = ["date", "value", "classification"]
BTC_COLUMNS = ["date", "close"]


def fng_url(limit=0):
    """alternative.me 贪恐指数 URL。limit=0 表示全量（3151 条，2018-02-01 起）。"""
    return "%s?limit=%d&format=json" % (config.ALTERNATIVE_ME_API, limit)


def btc_spot_url(timespan="10years"):
    """blockchain.info BTC 现货 URL。

    **必须带 sampled=false**：默认 sampled=true 会降采样到 2-4 天间隔
    （timespan=10years 只剩 1826 点），CF2 的动量/RSI/波动率都依赖日度粒度。
    """
    return "%s?timespan=%s&sampled=false&format=json" % (config.BLOCKCHAIN_CHART_API, timespan)


def parse_fng_payload(payload):
    """解析 alternative.me 响应为 date,value,classification（升序）。"""
    recs = []
    for item in (payload or {}).get("data") or []:
        try:
            recs.append({
                "date": pd.to_datetime(int(item["timestamp"]), unit="s").normalize(),
                "value": float(item["value"]),
                "classification": str(item.get("value_classification") or ""),
            })
        except (ValueError, KeyError, TypeError):
            continue
    if not recs:
        return pd.DataFrame(columns=FNG_COLUMNS)
    return (pd.DataFrame(recs).drop_duplicates(subset=["date"], keep="last")
            .sort_values("date").reset_index(drop=True))


def parse_btc_payload(payload):
    """解析 blockchain.info 响应为 date,close（升序）。

    剔除 y=0.0 的记录：2009 年 BTC 尚无市场价格，blockchain.info 返回 0，
    保留会把「无价」误当成「价格为零」，使后续收益率计算产生 inf。
    """
    recs = []
    for item in (payload or {}).get("values") or []:
        try:
            price = float(item["y"])
            if price <= 0:
                continue
            recs.append({
                "date": pd.to_datetime(int(item["x"]), unit="s").normalize(),
                "close": price,
            })
        except (ValueError, KeyError, TypeError):
            continue
    if not recs:
        return pd.DataFrame(columns=BTC_COLUMNS)
    return (pd.DataFrame(recs).drop_duplicates(subset=["date"], keep="last")
            .sort_values("date").reset_index(drop=True))


def fetch_crypto_fng():
    """抓取加密贪恐指数全量历史。"""
    payload = json.loads(_get(fng_url()).decode("utf-8"))
    return parse_fng_payload(payload)


def fetch_btc_spot(timespan="10years"):
    """抓取 BTC 现货日度价格。"""
    payload = json.loads(_get(btc_spot_url(timespan)).decode("utf-8"))
    return parse_btc_payload(payload)


def fetch_crypto_symbol(symbol, limit=9999, fromdate="2010-01-01"):
    """抓取加密 ETF / 币股（走 Nasdaq，assetclass 自动判断）。

    Nasdaq 的 assetclass 参数对 ETF 与股票不同：加密 ETF（BITX/MSTX/CONL 等）
    用 etf，币股（MSTR/COIN）用 stocks。
    """
    assetclass = "etf" if symbol in config.CRYPTO_FETCH_SYMBOLS else "stocks"
    url = "%s?assetclass=%s&fromdate=%s&limit=%d" % (
        config.NASDAQ_API.format(symbol=urllib.parse.quote(symbol)), assetclass, fromdate, limit)
    data = json.loads(_get(url).decode("utf-8"))
    rows = ((data.get("data") or {}).get("tradesTable") or {}).get("rows") or []
    return parse_nasdaq_rows(rows, symbol)


def update_crypto_prices(path=None, sleep=1.0):
    """增量更新加密 ETF + 币股价格，返回 (合并后 DataFrame, 各标的本次新增行数)。"""
    path = path or config.CRYPTO_PRICES_PATH
    symbols = config.CRYPTO_FETCH_SYMBOLS + ["MSTR", "COIN"]
    old = pd.DataFrame()
    if os.path.exists(path):
        old = pd.read_csv(path, dtype={"symbol": str}, parse_dates=["date"])

    before = {s: (len(old[old["symbol"] == s]) if not old.empty else 0) for s in symbols}

    frames = []
    for sym in symbols:
        start, _ = missing_ranges(old, sym)
        fromdate = start.strftime("%Y-%m-%d") if start is not None else "2010-01-01"
        frames.append(fetch_crypto_symbol(sym, fromdate=fromdate))
        time.sleep(sleep)

    merged = merge_incremental(
        old, pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged.to_csv(path, index=False, encoding="utf-8")
    added = {s: len(merged[merged["symbol"] == s]) - before[s] for s in symbols}
    return merged, added


def update_crypto_aux(raw_dir=None):
    """更新 crypto_fng.csv 与 crypto_underlying.csv（BTC 现货）。"""
    raw_dir = raw_dir or config.RAW_DIR
    os.makedirs(raw_dir, exist_ok=True)
    fng = fetch_crypto_fng()
    fng.to_csv(config.CRYPTO_FNG_PATH, index=False, encoding="utf-8")
    btc = fetch_btc_spot()
    btc.to_csv(config.CRYPTO_UNDERLYING_PATH, index=False, encoding="utf-8")
    return {"fng_rows": len(fng), "btc_rows": len(btc)}
