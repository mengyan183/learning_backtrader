# -*- coding: utf-8 -*-
"""诊断（第二批）action ✓ —— 简报/数据/符号/截图诊断 + bsk 升级。

【边界】
  · 只依赖 `queue_core`（`ROOT` / `run` / `BSK_BIN`）+ 标准库 ✓
  · **不碰队列状态** ✗ —— `QUEUE` / `run_once` / flock 在调度器里
"""
import os
import subprocess
import sys
import time

from queue_core import BSK_BIN, ROOT, run as _run


def _act_diag_daily_log(params):
    """**查每日链日志里每一步的 rc** ✓（2026-11-03 排查 `fetch_*` 停更）。

    【为什么需要】
      用户告警：`sentiment`/`putcall`/`fedwatch`/`kalshi_fed`/`funding_rate`/
      `shoutu_fng`/`news_sentiment`/`stablecoin_usage`/`fred_dff` **全停更 20-26 天** ✗
      但日志尾部显示「简报成功 / 漂移监控成功 / 稳定币成功」✗ ⇒ **矛盾** ✗
      ⇒ 链是 `;` 串联 ✗ **某步失败不影响后面** ✗
      ⇒ 必须看**每一行 `[guard]` 的 rc** 才能定位 ✓

    【查什么】
      ① `/tmp/fg_daily.log` 里所有 `[guard] ... rc=` 行（最近 N 条）✓
      ② 非 0 的单独列出 ✓
      ③ 日志里最后的「日期」—— 判断日志是不是**今天的** ✗
         （如果日志是旧的 ✗ 那「简报成功」也是旧的 ✗ 就解释了矛盾 ✓）

    参数：`tail`（默认 400 行）✓
    """
    import re as _re

    n = int(params.get("tail") or 400)
    log = params.get("log") or "/tmp/fg_daily.log"
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:                # noqa: BLE001
        return {"ok": False, "error": "读不到 %s：%s" % (log, exc)}

    tail = lines[-n:]
    guards = [ln.rstrip() for ln in tail if "[guard]" in ln]
    fails = [g for g in guards if "rc=0" not in g]

    # 🔴 2026-11-04 用户要求：**还要抓 traceback** ✗
    #    因为 `backfill_stockanalysis.py` 里**只有 `return 0`** ✗
    #    它的 `rc=1` 来自**未捕获异常** ✗ ⇒ 日志里有完整 traceback ✓
    #    而原来只 grep `[guard]` ✗ 看不到 ✗
    traces = []
    for i, ln in enumerate(tail):
        if "Traceback (most recent call last)" in ln:
            # 抓后续 25 行 ✓（含异常类型和消息 ✓）
            traces.append("\n".join(x.rstrip() for x in tail[i:i + 25]))
    # 单独抓「Error / Exception」行 ✓（有些脚本不打印 traceback ✗）
    errs = [ln.rstrip() for ln in tail
            if ("Error:" in ln or "Exception:" in ln
                or "❌" in ln or "[ERROR]" in ln) and "[guard]" not in ln]
    # 日志里的日期（找 `MM-DD HH:MM:SS` 或 `YYYY-MM-DD`）
    dates = []
    for ln in tail:
        m = _re.search(r"\b(\d{4}-\d{2}-\d{2})\b", ln) or \
            _re.search(r"\b(\d{2}-\d{2} \d{2}:\d{2}:\d{2})\b", ln)
        if m:
            dates.append(m.group(1))

    return {"ok": True, "log": log,
            "total_lines": len(lines), "tail_lines": len(tail),
            "guard_count": len(guards), "fail_count": len(fails),
            "log_first_date": dates[0] if dates else "?",
            "log_last_date": dates[-1] if dates else "?",
            "note": "⚠️ 链是 `;` 串联 ⇒ **某步失败不影响后面** ✗ "
                    "所以「简报成功」不代表前面 fetch 成功 ✗",
            "fails": fails[-40:],
            "guards_tail": guards[-40:],
            "tracebacks": traces[-3:],
            "error_lines": errs[-20:]}


def _act_diagnose_symbols(params):
    """**查 `update_prices()` 为什么漏标的** ✓（2026-11-04 用户要求）。

    【背景】
      `config.FETCH_SYMBOLS` **39 个** ✗ 而 `prices.csv` 只有 **36 个** ✗
      长期缺失 11 个：
        DIA / EWY / ITB / KRE / TLT / VGK / XBI / XLE / XLK / XLU / XLV
      ⇒ 全是**主流 ETF** ✗ Nasdaq 不可能没有 ✗
      ⇒ 而 `fetch_symbol` **已有** `etf→stocks` 回退 + 3 轮退避重试 ✗
      ⇒ **所以问题在「增量逻辑」或「URL 参数」** ✗ 不在「标的不可得」✗

    【逐个标的查 4 件事】
      ① `prices.csv` 里有没有、行数、最新日期 ✓
      ② `missing_ranges(old, sym)` 返回什么 ✓ ← **最可疑**
      ③ 用它给的 `fromdate` 直接调 `fetch_symbol` 能否抓到 ✓
      ④ 抓不到时的**真实异常** ✓

    参数：`symbols`（逗号分隔 ✗ 默认 = FETCH_SYMBOLS 里 `prices.csv` 缺的那些 ✓）
    """
    import pandas as _pd

    want = str(params.get("symbols") or "").strip()
    path = os.path.join(ROOT, "Data", "raw", "prices.csv")
    old = _pd.DataFrame()
    if os.path.exists(path):
        old = _pd.read_csv(path, dtype={"symbol": str},
                           parse_dates=["date"])

    from fg_system import config as _cfg
    if want:
        syms = [x.strip() for x in want.split(",") if x.strip()]
    else:
        have = set(old["symbol"].unique()) if not old.empty else set()
        syms = [s for s in _cfg.FETCH_SYMBOLS if s not in have]

    from fg_system.data import fetch as _fetch

    out = {}
    for sym in syms:
        rec = {}
        sub = old[old["symbol"] == sym] if not old.empty else _pd.DataFrame()
        rec["in_csv"] = int(len(sub))
        if len(sub):
            rec["csv_last"] = str(sub["date"].max().date())
        # ② 增量逻辑怎么说 ✓
        try:
            start, end = _fetch.missing_ranges(old, sym)
            rec["missing_ranges"] = {
                "start": str(start.date()) if start is not None else None,
                "end": str(end.date()) if end is not None else None,
            }
            fromdate = (start.strftime("%Y-%m-%d")
                        if start is not None else "2010-01-01")
        except Exception as exc:            # noqa: BLE001
            rec["missing_ranges"] = {"error": str(exc)[:120]}
            fromdate = "2010-01-01"
        rec["fromdate_used"] = fromdate
        # ③④ 直接抓 ✓
        try:
            df = _fetch.fetch_symbol(sym, fromdate=fromdate)
            rec["fetch_ok"] = True
            rec["fetch_rows"] = int(len(df))
            if len(df):
                rec["fetch_range"] = "%s → %s" % (
                    df["date"].min().date(), df["date"].max().date())
        except Exception as exc:            # noqa: BLE001
            rec["fetch_ok"] = False
            rec["fetch_error"] = "%s: %s" % (type(exc).__name__,
                                             str(exc)[:200])
        out[sym] = rec

    ok_cnt = sum(1 for v in out.values() if v.get("fetch_ok"))
    return {"ok": True, "checked": len(out),
            "fetch_ok": ok_cnt, "fetch_fail": len(out) - ok_cnt,
            "symbols": out,
            "note": "⚠️ `fetch_ok=True` 但 `missing_ranges` 给了错日期 ⇒ "
                    "**增量逻辑是根因** ✗；"
                    "`fetch_ok=False` ⇒ 看 `fetch_error` ✓"}


def _act_inspect_snapshots(params):
    """**核实持仓/账户快照的真实积累情况** ✓（2026-11-05）。

    🔴 为什么要查 ✗：
       `verify_hypotheses` 在 **Mac** 上跑，却报
         `[H-006] pending — Data/accounts.csv（本机仅 1 日快照）`
       而同一天 `sync_positions` 在 **Mac** 上跑，输出
         `已写入：accounts 54 行（新增 2）/ positions 162 行（新增 6）`
       ⇒ **两者矛盾** ✗
       可能：① `verify_hypotheses` 读的路径/判断有 bug ✗
             ② 它读的是「某列唯一值」而非行数 ✗
             ③ 文件里 `date` 列只有 1 个值（其余行 date 为 NaN ✗）

    ⇒ 直接把**行数 / date 唯一值 / 各列非空数**打出来 ✓ 一看就清楚 ✓
    """
    import pandas as _pd
    out = {"ok": True, "files": {}}
    for name in ("accounts", "positions"):
        p = os.path.join(ROOT, "Data", "%s.csv" % name)
        rec = {"path": os.path.relpath(p, ROOT)}
        if not os.path.exists(p):
            rec["exists"] = False
            out["files"][name] = rec
            continue
        rec["exists"] = True
        rec["size_kb"] = round(os.path.getsize(p) / 1024.0, 1)
        try:
            d = _pd.read_csv(p)
            rec["rows"] = int(len(d))
            rec["columns"] = list(d.columns)
            if "date" in d.columns:
                dd = d["date"].astype(str)
                uniq = sorted(dd.dropna().unique())
                rec["date_unique"] = len(uniq)
                rec["date_first"] = uniq[0] if uniq else None
                rec["date_last"] = uniq[-1] if uniq else None
                rec["date_null"] = int(dd.isna().sum())
                rec["date_samples"] = uniq[:3] + uniq[-3:] if len(uniq) > 6 else uniq
            # 每列非空数 ✓（看是不是大部分列都空 ✗）
            rec["nonnull"] = {c: int(d[c].notna().sum())
                              for c in d.columns[:12]}
        except Exception as exc:            # noqa: BLE001
            rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        out["files"][name] = rec
    # 判读 ✓
    a = out["files"].get("accounts") or {}
    p2 = out["files"].get("positions") or {}
    n = max(int(a.get("date_unique") or 0), int(p2.get("date_unique") or 0))
    out["verdict"] = ("✓ **有 %d 个不同日期** ⇒ 数据够 ✓ "
                      "那 `verify_hypotheses` 的判断有 bug ✗" % n
                      if n >= 2 else
                      "✗ **只有 %d 个日期** ⇒ 确实没积累 ✗" % n)
    return out


def _act_news_diag(params):
    """排查「某个标的的新闻整行消失」✓（2026-11-11 用户要求查 BTC）。

    🔴 现象：11-11 三轮简报里 **BTC 行全部消失** ✗
       而 BTC 是唯一盈利仓，此前一直有
       `Live news: Bitcoin falls to nearly three-month low - CoinDesk` ✓
       同一轮 GDXU / AXTX 也消失了（那两只是「过滤后无内容」，合理）
       ⇒ 但 BTC 不该空 ✗

    查五件事（逐层往下，定位是哪一层滤掉的）：
      ① `snap["positions"]` 里有没有 BTC（防止上游就没给）
      ② 富途 `get_search_news("比特币")` 的**原始**标题（不滤）
      ③ Google News `bitcoin price` 的**原始**标题（不滤）
      ④ 每个原始标题过 `_news_is_noise` 的判定（模板标题层）
      ⑤ 每个原始标题过 `_news_relevant("BTC", t)` 的判定（相关性层）
    ⚠️ 只读，不改任何数据 ✓
    """
    out = {"steps": {}}

    # ① 持仓里有没有 BTC
    # 🔴 2026-11-11 修正：原来写 `sys.path.insert(0, SCRIPTS)` ✗
    #    但本模块**没有 `SCRIPTS` 常量**（只有 `ROOT`）⇒ `NameError` ✗
    #    其他 action 都是直接 `import invest_research`（入口已把 scripts/ 加进 path）✓
    try:
        import invest_research as _ir
        snap = _ir.build_snapshot()
        syms = [str(r.get("symbol") or "") for r in (snap.get("positions") or [])]
        out["steps"]["positions"] = syms
        out["steps"]["has_btc"] = any("BTC" in s for s in syms)
    except Exception as exc:              # noqa: BLE001
        out["steps"]["positions"] = "ERR %s: %s" % (type(exc).__name__,
                                                    str(exc)[:200])
        _ir = None
        snap = None

    target = str(params.get("symbol") or "BTC").strip().upper()
    out["target"] = target

    # ② 富途原始返回
    if _ir is not None:
        try:
            from futu import OpenQuoteContext
            kw = {"BTC": "比特币", "ETH": "以太坊"}.get(target, target)
            with _ir._alarm(45, "futu 新闻抓取超时"):
                q = OpenQuoteContext(host="127.0.0.1", port=11111)
                ret, data = q.get_search_news(kw, max_count=6)
                titles = ([str(t).strip() for t in data["title"].tolist()]
                          if ret == 0 and len(data) else [])
                q.close()
            out["steps"]["futu"] = {"kw": kw, "ret": ret, "n": len(titles),
                                    "titles": titles[:6]}
        except Exception as exc:          # noqa: BLE001
            out["steps"]["futu"] = "ERR %s: %s" % (type(exc).__name__,
                                                   str(exc)[:200])

        # ③ Google News 原始
        try:
            q = {"BTC": "bitcoin price", "ETH": "ethereum price"}.get(
                target, "%s stock" % target)
            tick = None if target in ("BTC", "ETH") else target
            urls = _ir._rss_sources(q, tick)
            raw = _ir._rss_titles_any(urls, 4)
            out["steps"]["gnews"] = {"q": q, "n": len(raw or []),
                                     "titles": list(raw or [])[:4],
                                     "sources": [u.split("?")[0][:70] for u in urls]}
        except Exception as exc:          # noqa: BLE001
            out["steps"]["gnews"] = "ERR %s: %s" % (type(exc).__name__,
                                                    str(exc)[:200])

        # ④⑤ 逐条判定：哪一层滤掉的
        try:
            rows = []
            for src in ("futu", "gnews"):
                blk = out["steps"].get(src)
                if not isinstance(blk, dict):
                    continue
                for t in (blk.get("titles") or []):
                    noise = _ir._news_is_noise(t)
                    rel = _ir._news_relevant(target, t)
                    rows.append({
                        "src": src,
                        "title": str(t)[:80],
                        "noise": noise,
                        "relevant": rel,
                        "verdict": ("滤·模板标题" if noise
                                    else ("保留" if rel else "滤·不含标的词")),
                    })
            out["steps"]["judge"] = rows
            out["steps"]["kept"] = sum(1 for r in rows if r["verdict"] == "保留")
        except Exception as exc:          # noqa: BLE001
            out["steps"]["judge"] = "ERR %s: %s" % (type(exc).__name__,
                                                    str(exc)[:200])

        # ⑥ **直接跑完整 `fetch_news`** ✓ —— 上面 ②~⑤ 是「手工重放」，
        #    可能和真实路径不同（比如 `fetch_news` 里富途段**整段超时**被吞 ✗）
        #    ⇒ 这一步才是「简报里到底拿到了什么」的**真凭实据** ✓
        try:
            import time as _t
            _t0 = _t.time()
            _news = _ir.fetch_news(snap)
            out["steps"]["fetch_news"] = {
                "seconds": round(_t.time() - _t0, 1),
                "keys": list(_news.keys()),
                "has_target": target in _news,
                "counts": {k: (len(v) if isinstance(v, list) else 1)
                           for k, v in _news.items()},
            }
        except Exception as exc:          # noqa: BLE001
            out["steps"]["fetch_news"] = "ERR %s: %s" % (
                type(exc).__name__, str(exc)[:250])

    out["ok"] = True
    _k = out["steps"].get("kept")
    out["hint"] = ("`judge` 里 verdict 全是「滤·…」⇒ 就是过滤层的问题 ✓；"
                   "`futu`/`gnews` 的 n 都是 0 ⇒ 是**抓取源**的问题 ✗（不是过滤）")
    return out


def _act_analyze_png(params):
    """**分析截图的「文字密度」** ✓（2026-11-05 用户要求「交给 Mac 的 AI 分析」）。

    🔴 为什么用密度而不是 OCR ✗：
       Mac 上**不一定有 tesseract** ✗ 而 PIL **一定有**（pandas 的依赖链里 ✗）
       而「有没有数据表格」这个判断 ✗ **密度就够了** ✓：
         - 数据表格 = **大量密集小字** ✗ ⇒ 暗像素比例高 ✓
         - 只有框架/图片 = **大片空白** ✗ ⇒ 暗像素比例低 ✓

    【怎么判】
      ① 全图暗像素比例（`< 2%` ⇒ 基本是空白 ✗）
      ② 切成 4×4 网格，**每格的暗像素比例** ✓
         ⇒ 表格通常出现在**中下部**，且**连续几格都很高** ✓
      ③ **横向连续高密度行数**（表格是横向排列的 ✗）
      ④ 与「典型表格页」的经验阈值比对 ✓

    参数：`path`（默认 `dist/cme.png`）、`grid`（默认 4）
    """
    path = str(params.get("path") or "dist/cme.png")
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    grid = int(params.get("grid") or 4)
    if not os.path.exists(path):
        return {"ok": False, "error": "文件不存在：%s ✗" % path}

    try:
        from PIL import Image
    except ImportError:
        return {"ok": False,
                "error": "**没有 PIL** ✗ 装 `pip install pillow` ✗"}

    try:
        im = Image.open(path).convert("L")   # 灰度 ✓
    except Exception as exc:                # noqa: BLE001
        return {"ok": False, "error": "打开失败：%s" % str(exc)[:150]}

    w, h = im.size
    px = im.load()
    # 全图暗像素比例 ✓（阈值 128 ✗ 保守一点用 160 抓浅色字 ✓）
    dark = 0
    total = 0
    step = max(1, min(w, h) // 600)         # 抽样加速 ✓（大图别逐像素 ✗）
    for y in range(0, h, step):
        for x in range(0, w, step):
            if px[x, y] < 160:
                dark += 1
            total += 1
    ratio = (dark / total) if total else 0.0

    # 网格密度 ✓
    cells = []
    for gy in range(grid):
        row = []
        for gx in range(grid):
            x0, x1 = gx * w // grid, (gx + 1) * w // grid
            y0, y1 = gy * h // grid, (gy + 1) * h // grid
            d = t = 0
            for y in range(y0, y1, step):
                for x in range(x0, x1, step):
                    if px[x, y] < 160:
                        d += 1
                    t += 1
            row.append(round((d / t) if t else 0.0, 4))
        cells.append(row)

    # 判据 ✓
    max_cell = max((max(r) for r in cells), default=0.0)
    hot_rows = sum(1 for r in cells if max(r) > 0.08)
    verdict = (
        "✗ **全图几乎空白**（暗像素 %.2f%%）⇒ 页面没渲染出内容 ✗"
        % (ratio * 100) if ratio < 0.02 else
        "⚠️ **只有零散文字**（%.1f%%，最高格 %.1f%%）"
        "⇒ 像「导航+标题」✗ 不像数据表格 ✗"
        % (ratio * 100, max_cell * 100) if max_cell < 0.10 else
        "✓ **有密集文字区**（%.1f%%，最高格 %.1f%%，%d 行高密度）"
        "⇒ **可能有数据表格** ✓ 值得再看 ✓"
        % (ratio * 100, max_cell * 100, hot_rows))

    return {"ok": True, "path": path, "size_kb": round(
                os.path.getsize(path) / 1024.0, 1),
            "image": {"w": w, "h": h},
            "dark_ratio": round(ratio, 4),
            "grid": grid, "cells": cells,
            "max_cell": max_cell, "hot_rows": hot_rows,
            "verdict": verdict,
            "note": "⚠️ 密度只能判「有没有密集文字」✗ "
                    "不能判「是不是 FedWatch 数据」✗ "
                    "⇒ 若显示「有密集文字区」⇒ 需人工看图确认 ✓"}


def _act_bsk_update(params):
    """**升级 bsk CLI** ✓（2026-11-05 用户要求）。

    🔴 为什么必须升级 ✗：
       实测 bsk 的**写操作全部失败** ✗：
         `click`     rc=1  `shared page control or observation changed` ✗
         `evaluate`  rc=1  同上 ✗
       而**只读操作全部成功** ✓（observe/snapshot/get-html/network/tab ✗）
       根因：`bsk status` 长期警告：
         `protocol ext 1.3 vs CLI 1.1 (app ext v0.3.3, CLI v0.2.0)`
       ⇒ **写操作需要 ext 1.3 的新协议** ✗ ⇒ 必须升级 CLI ✓

    🔴 **必须先配代理** ✗（用户特别叮嘱 ✗）：
       `bsk update` 要下载 npm 包 ✗ 而**国内直连 npm 经常超时** ✗
       ⇒ 显式注入 `HTTP_PROXY` / `HTTPS_PROXY`（Mac 上是 `127.0.0.1:7890` ✗）

    参数：
      - `proxy`：默认 `http://127.0.0.1:7890` ✓
      - `dry_run`：`1` = 只查不升 ✓
      - `daemon`：`restart` = 升完**停掉旧 daemon** 并回读 `bsk status --json` ✓
        🔴 2026-11-06 实测：CLI 二进制已是 **0.4.2**（`bsk update` 说 up to date）
           但 `bsk status` 仍报 `CLI v0.2.0` ⇒ **daemon 是旧进程** ✗
           ⇒ 只升级不重启 daemon = 白升 ✗（协议仍 1.1，扩展是 1.3）
    """
    proxy = str(params.get("proxy") or "http://127.0.0.1:7890")
    dry = str(params.get("dry_run") or "").lower() in ("1", "true", "yes")
    restart_daemon = str(params.get("daemon") or "").lower() in ("restart", "1",
                                                                "true", "yes")

    # ① 升级前版本 ✓
    def _ver():
        try:
            r = _run([BSK_BIN, "--version"], 30)
            return (r.stdout or r.stderr or "").strip()[:120]
        except Exception as exc:            # noqa: BLE001
            return "查不到：%s" % str(exc)[:100]

    before = _ver()

    # ② **带代理**跑 update ✓（用户明确要求 ✗）
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy"):
        env[k] = proxy
    # ⚠️ npm registry 走代理时**不要**把 localhost 也代理掉 ✗
    env.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
    env.setdefault("no_proxy", "127.0.0.1,localhost,::1")

    cmd = [BSK_BIN, "update"] + (["--check"] if dry else [])
    t0 = time.time()
    try:
        r = _run(cmd, 900, env=env)
        rc, so, se = r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return {"ok": False, "error": "**找不到 bsk** ✗（设 FG_BSK ✗）"}
    except subprocess.TimeoutExpired:
        rc, so, se = 124, "", "超过 900 秒 ✗（代理不通？✗）"
    secs = time.time() - t0

    after = _ver()

    def _bsk(args, timeout=90):
        """跑一条 bsk 子命令并回显（daemon 操作用）✓。"""
        try:
            r = _run([BSK_BIN] + list(args), timeout, env=env)
            return {"rc": r.returncode,
                    "out": (r.stdout or r.stderr or "").strip()[:1500]}
        except Exception as exc:            # noqa: BLE001
            return {"rc": -1, "out": str(exc)[:200]}

    out = {"ok": rc == 0, "rc": rc, "seconds": round(secs, 1),
           "proxy": proxy, "dry_run": dry,
           "version_before": before, "version_after": after,
           "changed": before != after,
           "stdout": so[-3000:], "stderr": se[-1500:],
           "note": ("⚠️ 升级后要**重启 daemon** 才生效 ✗"
                    "（`bsk daemon restart` 或重启 Chrome ✗）；"
                    "⚠️ 升级可能改变 CLI 行为 ✗ "
                    "`fetch_shoutu_history.py` 依赖它 ✓ 要回归 ✓")
           if rc == 0 and not dry else ""}
    if restart_daemon:
        # stop 之后**不需要** start：任何 bsk 命令都会自动拉起（SKILL.md）
        out["daemon_stop"] = _bsk(["daemon", "stop"])
        out["status_after"] = _bsk(["status", "--json"])
    return out


def _act_diagnose_data(params):
    """**数据断流诊断** ✓（2026-11-03 用户要求「Mac 上先修数据」）。

    【背景】
      `Data/raw/prices.csv` 停在 2026-10-12 ✗ 断 22 天 ✗
      而简报每天正常生成 ✗ ⇒ 「现价」「浮盈亏」全是 3 周前的数字 ✗
      ⇒ 先查**为什么停**，再决定怎么补 ✗

    【查什么】
      ① 每个 `Data/raw/*.csv` 的**行数 + 最新日期** ✓
      ② `/tmp/fg_daily.log` 尾部（找 `fetch_*` 的报错 ✗）
      ③ launchd 里 `fg-daily` 的**最后退出码** ✓

    参数：`tail`（日志行数，默认 40）✓
    """
    import glob as _glob
    from datetime import datetime as _dt

    n_tail = int(params.get("tail") or 40)
    out = {"checked_at": _dt.now().isoformat(timespec="seconds"),
           "files": {}, "log_tail": "", "launchd": ""}

    # ① 各 csv 的最新日期
    for p in sorted(_glob.glob(os.path.join(ROOT, "Data", "raw", "*.csv"))):
        name = os.path.basename(p)
        try:
            import pandas as _pd
            d = _pd.read_csv(p, usecols=["date"], parse_dates=["date"])
            last = d["date"].max()
            out["files"][name] = {
                "rows": int(len(d)),
                "last": str(last.date()) if _pd.notna(last) else "?",
            }
        except Exception as e:              # noqa: BLE001
            out["files"][name] = {"error": str(e)[:80]}

    # ② 每日链日志尾部
    log = "/tmp/fg_daily.log"
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        out["log_tail"] = "".join(lines[-n_tail:])[-3000:]
    except Exception as e:                  # noqa: BLE001
        out["log_tail"] = "读不到 %s：%s" % (log, e)

    # ③ launchd 状态
    try:
        r = _run(["launchctl", "print", "gui/%d/com.xingguo.fg-daily"
                  % os.getuid()], 60)
        txt = r.stdout or r.stderr or ""
        keep = [ln.strip() for ln in txt.splitlines()
                if any(k in ln for k in ("state =", "last exit", "runs =",
                                         "program ="))]
        out["launchd"] = "\n".join(keep[:8]) or "(无输出)"
    except Exception as e:                  # noqa: BLE001
        out["launchd"] = "查不到：%s" % e

    # 判断是否真的断流 ✓
    stale = []
    for name, v in out["files"].items():
        last = v.get("last")
        if not last or last == "?":
            continue
        try:
            gap = (_dt.now() - _dt.strptime(last, "%Y-%m-%d")).days
        except ValueError:
            continue
        if gap > 5:
            stale.append("%s 停 %d 天（%s）" % (name, gap, last))
    out["stale"] = stale
    out["ok"] = not stale
    return out

ACTIONS = {
    "news_diag": _act_news_diag,
    "diagnose_symbols": _act_diagnose_symbols,
    "diagnose_data": _act_diagnose_data,
    "diag_daily_log": _act_diag_daily_log,
    "analyze_png": _act_analyze_png,
    "inspect_snapshots": _act_inspect_snapshots,
    "bsk_update": _act_bsk_update,
}
