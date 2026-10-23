#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询**指定标的**的系统贪恐系数（个股级，0-100，高分=贪婪）。

【为什么需要】
`fg_system/factors/symbol.py::symbol_fg_index()` 早就支持逐标的计算 ✓，
但**只挂在持仓看板的「系统」列**上 ✗ ⇒ 想查一个**非持仓**的标的（如 NVDA）
没有入口 ✗。本脚本补这个入口 ✓。

【口径】
- 个股分 = 三因子合成（`mom60 0.5 / mom20 0.3 / vol20 反向 0.2`，756 日滚动分位，
  权重**禁止优化**）✓ —— 与看板「系统」列**同源** ✓，不新造算法 ✗。
- 必须走**无杠杆底层** ✓（`config.SIGNAL_UNDERLYING_MAP` / `CRYPTO_UNDERLYING`），
  禁止直接用杠杆 ETF 价格 ✗（波动率拖累会被误读成恐惧 ✗）。
- 底层数据不足（< 窗口 756 + 60 交易日）⇒ **回退市场级 `fg_index`** ✓ 并**明确标注**
  「（大盘）」✗ —— 不允许静默混用 ✗。

【用法】
    py -3.10 scripts/query_symbol_fg.py NVDA
    py -3.10 scripts/query_symbol_fg.py NVDA GDXU BTC-USDT
    py -3.10 scripts/query_symbol_fg.py --json NVDA
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                        # noqa: E402
from fg_system.factors import symbol as sym_mod     # noqa: E402

#: 底层历史下限：滚动分位窗口 756 + 动量 60 ✓
MIN_ROWS = int(config.RANK_WINDOW) + 60
ZONE_EDGES = [20, 40, 60, 80]
ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


def _zone(v):
    import numpy as np
    return ZONE_NAMES[int(np.clip(np.searchsorted(ZONE_EDGES, v, side="right"), 0, 4))]



# ---------------------------------------------------------------- 守猪待兔（shoutu）
#: 守猪待兔信号的最大有效滞后天数 ✓（`config.SHOUTU_SIGNAL_MAX_LAG_DAYS` ✓）
SHOUTU_MAX_LAG = int(getattr(config, "SHOUTU_SIGNAL_MAX_LAG_DAYS", 3))


def _shoutu_of(symbol, records=None):
    """取该标的**最新**守猪待兔系数 ✓。

    :returns: `{"raw": -100~100, "value": 0~100, "zone": str, "date": str,
               "stale": bool}` ✓；未覆盖 / 无数据 ⇒ `None` ✗
    """
    try:
        from fg_system.data import loader as _ld
        d = records if records is not None else _ld.load_shoutu_records()
    except (OSError, ValueError, ImportError):
        return None
    if d is None or getattr(d, "empty", True) or "symbol" not in d.columns:
        return None
    sub = d[d["symbol"].astype(str).str.upper() == symbol]
    if sub.empty:
        return None
    sub = sub.sort_values("date")
    last = sub.iloc[-1]
    try:
        raw = float(last["value"])
    except (TypeError, ValueError):
        return None
    # 🔴 映射 **(x+100)/2** ✓ —— 与 `loader.shoutu_to_system_scale` 同口径 ✓
    val = round((raw + 100.0) / 2.0, 1)
    dstr = str(last["date"])[:10]
    _fg, mdate = _market_fg()
    stale = bool(mdate and dstr and dstr < mdate)
    try:
        from datetime import date as _d
        lag = (_d.fromisoformat(mdate) - _d.fromisoformat(dstr)).days if mdate else 0
        if lag > SHOUTU_MAX_LAG:
            stale = True
    except (ValueError, TypeError):
        pass
    return {"raw": raw, "value": val, "zone": _zone(val),
            "date": dstr, "stale": stale}


def _market_fg():
    """市场级 `fg_index` 最新值（回退用）✓；读不到 ⇒ None。"""
    path = os.path.join(config.DATA_DIR, "features.csv")
    if not os.path.exists(path):
        return None, None
    try:
        d = pd.read_csv(path)
        d = d.dropna(subset=["fg_index"])
        if d.empty:
            return None, None
        last = d.iloc[-1]
        return float(last["fg_index"]), str(last["date"])[:10]
    except (KeyError, ValueError, OSError):
        return None, None


def query(symbol, prices=None, auto=False):
    """单个标的的结果字典 ✓（`source` 明确标 个股 / 大盘回退 ✗）。"""
    out = {"symbol": symbol, "underlying": None, "rows": 0,
           "value": None, "zone": None, "date": None, "stale": False,
           "source": None, "error": None,
           # 守猪待兔（与贪恐**并列**的第二系统 ✓，−100~100 ⇒ 0~100 ✓）
           "shoutu": None, "shoutu_raw": None, "shoutu_zone": None,
           "shoutu_date": None, "shoutu_stale": False}

    # 🔴 与 `underlying_close()` 共用**同一归一**（`BTC-USDT` → `BTC`）✗ ——
    # 否则 `und=None` 却仍能算出分 ✗ ⇒ 同一行「既有分数又报未登记」✓
    # （2026-10-20 团队审查 P1 实测 ✓）。
    lookup = "BTC" if symbol == "BTC-USDT" else symbol
    und = (config.SIGNAL_UNDERLYING_MAP.get(lookup)
           or config.CRYPTO_UNDERLYING.get(lookup))
    out["underlying"] = und

    # 守猪待兔系数 ✓ —— **独立于贪恐** ✓（未登记贪恐也照样有 ✓）
    _sh = _shoutu_of(symbol)
    if _sh:
        out["shoutu"] = _sh["value"]
        out["shoutu_raw"] = _sh["raw"]
        out["shoutu_zone"] = _sh["zone"]
        out["shoutu_date"] = _sh["date"]
        out["shoutu_stale"] = _sh["stale"]
    elif symbol not in set(getattr(config, "SHOUTU_SYMBOLS", ())):
        out["shoutu_error"] = "该标的不在守猪待兔覆盖范围 ✗（config.SHOUTU_SYMBOLS ✓）"

    try:
        close = sym_mod.underlying_close(symbol, prices=prices)
    except (OSError, KeyError, ValueError) as exc:
        out["error"] = "读底层失败：%s" % exc
        return out

    if close is not None:
        out["rows"] = int(len(close))

    if und is None and auto:
        und, meta = auto_resolve(symbol, prices=prices)
        if und:
            out["underlying"] = und
            out["auto"] = meta
    if und is None:
        # 🔴 未登记时给**模糊建议** ✗ —— 用户常把代码打错（2026-10-21 实测：
        # 输入 `KOORU` 而本意是 `KORU` ✓）⇒ 直接说「是否想查 XXX」✓ 比只报错有用 ✓
        import difflib
        known = sorted(set(config.SIGNAL_UNDERLYING_MAP)
                       | set(config.CRYPTO_UNDERLYING))
        near = difflib.get_close_matches(symbol, known, n=2, cutoff=0.6)
        hint = ("；是否想查 %s ？" % " / ".join(near)) if near else ""
        out["error"] = ("未在 config.SIGNAL_UNDERLYING_MAP / CRYPTO_UNDERLYING 登记 ✗ "
                        "⇒ 无法确定无杠杆底层（需先登记 ✓）" + hint)
    series = sym_mod.symbol_fg_index(symbol, prices=prices)
    if series is not None and not series.dropna().empty:
        s = series.dropna()
        out["value"] = round(float(s.iloc[-1]), 1)
        out["zone"] = _zone(out["value"])
        out["date"] = str(s.index[-1])[:10]
        out["source"] = "个股"
        # 🔴 **逐项滞后校验** ✗：底层数据可能停更（Mac 实测 `COIN` 停在 2026-10-01 ✗），
        # 只看分数会把旧值当成「现在」✗ ⇒ 与市场级 `data_date` 比对并透出 `stale` ✓
        _fg, mdate = _market_fg()
        out["stale"] = bool(mdate and out["date"] and out["date"] < mdate)
        return out

    # 🔴 **未登记** ⇒ 连底层都没有 ⇒ **不给分数** ✗（给了就等于把大盘分冒充成个股分 ✗）
    if und is None:
        return out

    # 已登记但底层不足 ⇒ 回退：明确标注来源 ✗（不静默混用 ✓）
    fg, d = _market_fg()
    if fg is not None:
        out["value"] = round(fg, 1)
        out["zone"] = _zone(fg)
        out["date"] = d
        out["source"] = "大盘回退"
        out["stale"] = False      # 回退值就是市场级最新日 ⇒ 自身不滞后 ✓
        if not out["error"]:
            # 🔴 文案必须**按真实原因分支** ✗ —— 原来任何失败都写「N 行 < 816 行」✓，
            # 行数够但因 NaN 失败时会给出**假原因** ✗（2026-10-20 审查 P1）
            if out["rows"] < MIN_ROWS:
                out["error"] = ("底层历史 %d 行 < 下限 %d 行 ✗ ⇒ 已回退市场级 fg_index ✓"
                                % (out["rows"], MIN_ROWS))
            else:
                out["error"] = ("底层历史 %d 行（≥ 下限 %d）✗ 但算不出分数 "
                                "⇒ 疑似全 NaN / 窗口不足 ⇒ 已回退市场级 fg_index ✓"
                                % (out["rows"], MIN_ROWS))
    elif not out["error"]:
        out["error"] = "既算不出个股分，也没有市场级 fg_index 可回退 ✗"
    return out



# ---------------------------------------------------------------- 自动推断（方案 B）
#: 自动推断结果的**缓存**（`Data/` 下 ✓ 不入库 ✓，可人工删掉重推 ✓）
AUTO_CACHE = os.path.join(config.DATA_DIR, "underlying_map_auto.csv")

#: 回归需要的最少重叠交易日 ✓（与 `underlying_infer.MIN_OVERLAP` 一致 ✓）
MIN_OVERLAP = 60


def _close_of(symbol, prices=None):
    """从 `prices`（DataFrame）取该标的收盘价 Series ✓；没有 ⇒ None ✗。"""
    if prices is None or prices.empty:
        return None
    d = prices[prices["symbol"] == symbol]
    if d.empty:
        return None
    s = d.set_index(pd.to_datetime(d["date"]))["close"].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def _fetch_close(symbol, limit=900):
    """**现场抓**单标的日线 ✓（Nasdaq ✓）。失败 ⇒ None ✗（不抛 ✓，由调用方决定 ✓）。"""
    try:
        from fg_system.data import fetch as _f
        df = _f.fetch_symbol(symbol, limit=limit)
    except Exception as exc:                 # noqa: BLE001 —— 抓数失败不该让查询崩 ✗
        print("  [warn] 抓取 %s 失败：%s" % (symbol, exc))
        return None
    if df is None or df.empty:
        return None
    s = df.set_index(pd.to_datetime(df["date"]))["close"].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def _load_auto_cache():
    """读自动推断缓存 ⇒ `{symbol: underlying}` ✓。"""
    if not os.path.exists(AUTO_CACHE):
        return {}
    try:
        d = pd.read_csv(AUTO_CACHE, dtype={"symbol": str, "underlying": str})
    except (OSError, ValueError):
        return {}
    return {str(r["symbol"]).strip(): str(r["underlying"]).strip()
            for _, r in d.iterrows()}


def _save_auto_cache(symbol, hit):
    """写缓存 ✓（**失败不影响查询** ✓）。"""
    try:
        row = pd.DataFrame([{"symbol": symbol, "underlying": hit["symbol"],
                             "beta": hit["beta"], "r2": hit["r2"],
                             "n": hit["n"],
                             "direction": hit["direction"],
                             "leverage": hit["leverage"]}])
        old = pd.DataFrame()
        if os.path.exists(AUTO_CACHE):
            old = pd.read_csv(AUTO_CACHE, dtype={"symbol": str})
            old = old[old["symbol"] != symbol]
        pd.concat([old, row], ignore_index=True).to_csv(AUTO_CACHE, index=False)
    except OSError as exc:
        print("  [warn] 推断缓存写入失败：%s" % exc)


def auto_resolve(symbol, prices=None, limit=900):
    """**自动推断底层** ✓（方案 B ✓）。

    流程：缓存 ⇒ 目标日线（本地优先 ✓，缺则现场抓 ✓）⇒ 候选池（**只读本地** ✗
    —— 现场抓 48 个太慢 ✓，靠 `scripts/fetch_candidates.py` 预热 ✓）⇒ β 回归 ✓。

    :returns: `(underlying | None, meta)` ✓
    """
    from fg_system.factors import underlying_infer as ui

    cached = _load_auto_cache().get(symbol)
    if cached:
        return cached, {"from": "cache"}

    tgt = _close_of(symbol, prices)
    if tgt is None or len(tgt) < MIN_OVERLAP:
        tgt = _fetch_close(symbol, limit)
    if tgt is None or len(tgt) < MIN_OVERLAP:
        return None, {"error": "目标标的日线不足 %d 日 ✗（无法回归 ✓）" % MIN_OVERLAP}

    pool = {}
    for cand in ui.load_candidates():
        c = _close_of(cand, prices)
        if c is not None and len(c) >= MIN_OVERLAP:
            pool[cand] = c
    if not pool:
        return None, {"error": "候选池无本地数据 ✗ ⇒ 请先跑 "
                               "`scripts/fetch_candidates.py` ✓"}

    hit = ui.pick(tgt, pool)
    if not hit:
        return None, {"error": "候选池（%d 个）里没有匹配的底层 ✗（R²<0.90 ✓）"
                               % len(pool)}
    _save_auto_cache(symbol, hit)
    return hit["symbol"], {"from": "infer", **hit}


def _print(results):
    print("%-10s %-10s %-7s %-7s %-9s %-11s %-12s %-9s %s"
          % ("标的", "底层", "行数", "分数", "档位", "来源", "数据日期",
             "守猪待兔", "守猪日期"))
    for r in results:
        val = "—" if r["value"] is None else "%.1f" % r["value"]
        # 🔴 CLI 也必须显示**逐项数据日期 + 滞后标记** ✗ —— 原来只有 JSON/页面有 ✓，
        # 命令行看到的分数可能是几周前的 ✗（2026-10-20 审查 P1）
        dtxt = r["date"] or "—"
        if r.get("stale"):
            dtxt += " ⚠️滞后"
        sh = ("—" if r.get("shoutu") is None
              else "%.1f %s" % (r["shoutu"], r.get("shoutu_zone") or ""))
        shd = r.get("shoutu_date") or "—"
        if r.get("shoutu_stale"):
            shd += " ⚠️"
        print("%-10s %-10s %-7d %-7s %-9s %-11s %-12s %-9s %s"
              % (r["symbol"], r["underlying"] or "未登记", r["rows"],
                 val, r["zone"] or "—", r["source"] or "—", dtxt, sh, shd))
        if r["error"]:
            print("           ⚠️ %s" % r["error"])
    print("\n口径：三因子 mom60/mom20/vol20（756 日滚动分位，权重禁止优化）✓；"
          "需底层历史 ≥ %d 行 ✓；不足则回退市场级并标「大盘回退」✗" % MIN_ROWS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="查询指定标的的系统贪恐系数（0-100）")
    ap.add_argument("symbols", nargs="+", help="标的代码，可多个（如 NVDA GDXU BTC-USDT）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（便于程序消费）")
    ap.add_argument("--auto", action="store_true",
                    help="未登记/无底层数据时**自动推断**底层 ✓"
                         "（β 回归 ✓；需先跑 scripts/fetch_candidates.py 预热候选池 ✓）")
    args = ap.parse_args(argv)

    prices = None
    path = os.path.join(config.RAW_DIR, "prices.csv")
    if os.path.exists(path):
        prices = pd.read_csv(path, dtype={"symbol": str}, parse_dates=["date"])
    else:
        print("⚠️ 缺 %s ⇒ 个股分全部无法计算 ✗（只能回退大盘）" % path)

    results = [query(s.upper(), prices=prices, auto=args.auto)
               for s in args.symbols]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        _print(results)
    # 有任何一个「完全无结果」⇒ 退出码 1（便于脚本判断 ✓）
    return 0 if all(r["value"] is not None for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
