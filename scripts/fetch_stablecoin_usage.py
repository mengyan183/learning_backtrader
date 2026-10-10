#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-10 稳定币「使用效率」数据接入（H-034）。

假说 H-034（evolution/hypotheses.md）：
    使用效率 = 稳定币链上月交易量 / USDC 流通量（Circle 深度研读口径 ≈ 2.25）。
    使用效率提升先行于市值增长，链上活跃度可作币股基本面领先指标。
本脚本产出该指标的原始序列，供后续检验其对 CRCL/HOOD 后续 4/8/16 日收益的领先性。

--------------------------------------------------------------------------
数据源方案（**候选先行，未联网核实 —— 公司网络受限**）
--------------------------------------------------------------------------
本脚本把端点**参数化**，默认不绑定任何一家，联网核实后只改环境变量即可。

候选 A：DefiLlama 稳定币 API（首选，免 key）
    - 流通量：GET {STABLECOIN_API}/stablecoins
      字段：peggedAssets[].{symbol, circulating.{peggedUSD}, chainBalances...}
    - 链上交易量：DefiLlama 稳定币交易量已并入 /stablecoins 的
      chainBalances[].tokens[].{circulating, minted}；**逐日交易量**需
      `/stablecoincharts/{chain}` 或链上浏览器补全（字段名待联网核实）。
    - key：免费档通常不需要 key；若命中限流需 `?apikey=`，走 STABLECOIN_API_KEY。

候选 B：Artemis（https://api.artemisxyz.com）
    - 字段：稳定币 transfer volume / active addresses（逐日）。
    - key：**必需** —— 注册后把 key 写入环境变量 STABLECOIN_API_KEY，
      或写入被 gitignore 的 Data/stablecoin_key（二选一，见 load_key）。

候选 C：CoinGecko 稳定币市场数据（https://api.coingecko.com/api/v3）
    - 流通量：/coins/{id}（usd-coin）的 market_data.circulating_supply。
    - 交易量：稳定币**市场成交额** ≠ 链上转账量，口径不同，仅作交叉校验。
    - key：免费档有限流，Pro 版走 x-cg-pro-api-key（STABLECOIN_API_KEY）。

⚠️ 联网核实后：以「能同时给出**链上月交易量**与**USDC 流通量**」的源为准；
   交易量与流通量**必须同源同口径**，否则 usage_efficiency 无量纲意义。

--------------------------------------------------------------------------
产物
--------------------------------------------------------------------------
Data/raw/stablecoin_usage.csv（列**固定**，顺序不得变，见 COLUMNS）：
    date, symbol, monthly_volume, circulation, usage_efficiency
其中 usage_efficiency = monthly_volume / circulation（circulation>0 时，否则留空）。

参数化（URL 与 key）
- 端点：环境变量 STABLECOIN_API（默认候选 A 的 base URL）。
- key：环境变量 STABLECOIN_API_KEY，或 Data/stablecoin_key（被 .gitignore 覆盖）。
  **严禁**把 key 写进源码。

失败口径（可解释失败，不抛栈）
- 无 key（当所选源需要 key 时）→ stderr 明确说明 + 提示如何配置 → 退出码 2。
- 无网络（连接/超时/DNS 失败）→ stderr 明确说明 + 提示检查代理 → 退出码 2。
- 解析失败 / 返回空数据 → stderr 明确说明 → 退出码 2。

用法：py -3.10 scripts/fetch_stablecoin_usage.py
      py -3.10 scripts/fetch_stablecoin_usage.py --help
      py -3.10 scripts/fetch_stablecoin_usage.py --out Data/raw/stablecoin_usage.csv
退出码：0=成功写出；2=无 key / 无网络 / 无数据（可解释失败）。
"""
import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request

# §6.2 第 4 条：脚本自带 stdout utf-8，避免 Windows GBK 崩溃。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 走 config 路径常量（照抄既有脚本风格）。
try:
    sys.path.insert(0, REPO)
    from fg_system import config  # noqa: E402
    RAW_DIR = config.RAW_DIR
    DEFAULT_PROXY = config.PROXY
except Exception:                                     # pragma: no cover
    RAW_DIR = os.path.join(REPO, "Data", "raw")
    DEFAULT_PROXY = os.environ.get("FG_PROXY", "")

DEFAULT_OUT = os.path.join(RAW_DIR, "stablecoin_usage.csv")
# key 文件放在 Data/ 下，被 .gitignore 显式覆盖（`Data/stablecoin_key`，2026-10-10 WT-12 R-4 已补）
KEY_FILE = os.path.join(REPO, "Data", "stablecoin_key")

# 候选 A 的 base URL（免 key 首选）。联网核实后可用 STABLECOIN_API 覆盖。
DEFAULT_API = "https://stablecoins.llama.fi"
UA = {"User-Agent": "Mozilla/5.0 (compatible; fg-system/1.0)"}

# 产物列**固定**，顺序不得变（验收标准）。
COLUMNS = ["date", "symbol", "monthly_volume", "circulation", "usage_efficiency"]
SYMBOL = "USDC"


def _err(msg, code=2):
    """可解释失败：打印到 stderr 并返回退出码，不抛栈。"""
    print("✗ fetch_stablecoin_usage: %s" % msg, file=sys.stderr)
    return code


def load_key(path=None):
    """读取 API key：环境变量 STABLECOIN_API_KEY 优先，其次 Data/stablecoin_key。

    两者都没有 → 返回 None（由调用方决定是否需要 key 并报可解释错误）。
    **严禁**把 key 写进源码。
    """
    path = KEY_FILE if path is None else path
    key = os.environ.get("STABLECOIN_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or None
    return None


def api_base(base=None):
    """端点参数化：环境变量 STABLECOIN_API 优先，其次显式入参，最后内置默认。"""
    return (base or os.environ.get("STABLECOIN_API") or DEFAULT_API).rstrip("/")


def _opener(proxy=None):
    """按需要构建 opener。代理为空则直连。"""
    proxy = DEFAULT_PROXY if proxy is None else proxy
    proxies = ({"http": proxy, "https": proxy} if proxy else {})
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))


def fetch_json(url, retries=3, proxy=None, timeout=25):
    """带重试的 GET → dict。

    失败抛 `StablecoinFetchError`（含可解释原因），由 main 统一转成退出码 2。
    """
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with _opener(proxy).open(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (401, 403):
                raise StablecoinFetchError(
                    "远端返回 HTTP %d（多半是 key 缺失/无效）：%s" % (exc.code, url))
            if exc.code == 404:
                break
        except Exception as exc:      # 连接 / 超时 / DNS / JSON 解析等
            last = exc
    raise StablecoinFetchError("请求失败 %s: %s" % (url, last))


class StablecoinFetchError(Exception):
    """可解释的抓取失败（区别于程序 bug）。"""


def parse_usage(payload):
    """把 DefiLlama `/stablecoins` 响应解析为 USDC 使用效率行。

    DefiLlama 的 `/stablecoins` 给出**当前截面**（含流通量），**不含逐日
    链上月交易量**。故本函数解析出 `circulation`；`monthly_volume` 由
    候选 B/C 的逐日端点补全（`parse_monthly_volume`）。此处返回的行
    `monthly_volume` 可能为空 —— 联网核实端点后按真实字段填空。

    返回 `list[dict]`，key 为 COLUMNS。
    """
    rows = []
    assets = payload.get("peggedAssets") if isinstance(payload, dict) else None
    for a in assets or []:
        if str(a.get("symbol", "")).upper() != SYMBOL:
            continue
        circ = (a.get("circulating") or {}).get("peggedUSD")
        if circ is None:
            continue
        rows.append({
            "date": _as_of_date(a),
            "symbol": SYMBOL,
            "monthly_volume": "",          # 待逐日端点补全
            "circulation": float(circ),
            "usage_efficiency": "",         # circulation / volume 齐备后再算
        })
    return rows


def parse_monthly_volume(payload):
    """把候选 B/C 的**逐日**交易量响应解析为 {date: volume}。

    ⚠️ 端点字段名待联网核实。此处按最保守约定：接受
    `[{"date": ..., "volume": ...}, ...]` 或 `{"data": [...]}` 两种形态。
    联网核实后按真实字段调整本函数（**只改这里**）。
    """
    items = payload.get("data") if isinstance(payload, dict) else payload
    out = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        day = it.get("date") or it.get("timestamp") or it.get("day")
        vol = it.get("volume") or it.get("transfer_volume") or it.get("monthly_volume")
        if day is None or vol is None:
            continue
        out[str(day)[:10]] = float(vol)
    return out


def _as_of_date(asset):
    """取资产行的日期；缺省用今天（DefiLlama 截面 = 最新）。"""
    import datetime
    d = asset.get("date") or asset.get("as_of")
    if d:
        return str(d)[:10]
    return datetime.date.today().isoformat()


def compute_efficiency(row):
    """usage_efficiency = monthly_volume / circulation（circulation>0 时）。"""
    try:
        vol = float(row["monthly_volume"])
        circ = float(row["circulation"])
    except (TypeError, ValueError, KeyError):
        return ""
    if circ <= 0:
        return ""
    return round(vol / circ, 6)


def write_csv(path, rows):
    """写出固定列顺序的 CSV，返回写出的行数。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            for c in COLUMNS:
                r.setdefault(c, "")
            r["usage_efficiency"] = compute_efficiency(r)
            w.writerow(r)
    return len(rows)


def build_rows(payload_circ, payload_vol=None):
    """合并流通量与逐日成交量 → 完整行（含 usage_efficiency）。"""
    rows = parse_usage(payload_circ)
    if payload_vol is not None:
        vols = parse_monthly_volume(payload_vol)
        for r in rows:
            if r["date"] in vols:
                r["monthly_volume"] = vols[r["date"]]
    for r in rows:
        r["usage_efficiency"] = compute_efficiency(r)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="B-10 稳定币使用效率抓取（H-034）：链上月交易量 / USDC 流通量 → "
                    "Data/raw/stablecoin_usage.csv")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出 CSV 路径（默认 Data/raw/stablecoin_usage.csv）")
    ap.add_argument("--api", default=None, help="稳定币 API base URL（默认读 STABLECOIN_API）")
    ap.add_argument("--require-key", action="store_true",
                    help="强制要求 API key（候选 B/C 需要时用）；缺 key 则退出 2")
    ap.add_argument("--retries", type=int, default=3, help="网络重试次数（默认 3）")
    args = ap.parse_args(argv)

    base = api_base(args.api)
    key = load_key()
    print("=== B-10 稳定币使用效率抓取（H-034）===")
    print("  端点: %s/stablecoins" % base)
    if args.require_key and not key:
        return _err(
            "缺少 API key。请设置环境变量 STABLECOIN_API_KEY，"
            "或把 key 写入 %s（该文件不入库）。" % KEY_FILE)

    url = "%s/stablecoins" % base
    if key:
        url += "?apikey=%s" % key
    try:
        payload = fetch_json(url, retries=args.retries)
    except StablecoinFetchError as exc:
        return _err(
            "抓取失败：%s\n  → 检查网络/代理（FG_PROXY=%s），或用 --api 覆盖端点。"
            % (exc, DEFAULT_PROXY or "(直连)"))

    rows = build_rows(payload)
    if not rows:
        return _err("解析后无 %s 数据（端点结构可能已变，请核对字段）。" % SYMBOL)

    n = write_csv(args.out, rows)
    print("  ✓ 写出 %d 行 → %s" % (n, args.out))
    print("  列: %s" % ", ".join(COLUMNS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
