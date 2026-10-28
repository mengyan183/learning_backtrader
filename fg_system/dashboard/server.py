# -*- coding: utf-8 -*-
"""仪表盘只读 HTTP 服务（手机访问用）。

【需求（用户，2026-09-23）】支持在**手机上打开**，**每次打开/刷新时主动重新计算**，
**不需要手机后台常驻**。

⇒ 架构：Mac 上起一个只读 HTTP 服务；**每次请求**重跑 pipeline 并渲染 HTML；
手机浏览器打开/刷新即得最新状态。**手机侧不装任何东西、不跑后台进程。**

【为什么改用 Flask + Jinja2（2026-10-02）】
页面已演进为多路由（PWA manifest / 图标 / APK / 静态资源）和多区块模板，
并持续打磨手机端 UI。Flask 提供路由、静态文件与 WSGI 服务一体化，
Jinja2 让模板独立成文件、不再需要 `%%` 转义。`make_server` 接口保持兼容，
`scripts/serve_dashboard.py` 与既有测试无需改动。

【⚠️ 本服务**绝不无条件抓取**守猪待兔】见 `tests/dashboard/test_server.py` 的
`test_server_never_fetches_from_api`。两条理由，任一条都足以禁止：

1. 该指数**实时更新**，而 `append_records` 对同一 `(date, symbol)` 是**覆盖**
   语义 ⇒ **每次刷新都抓 = 每次刷新都污染当天样本**（§14.5 已实际发生过一次）
2. 每次刷新都消耗 `query_api` 额度（5000/月）

⇒ 仪表盘默认**纯计算**（读已有 CSV）；2026-10-07 起，刷新时仅当检测到
**当天快照缺失**且行情过期，才由 `freshness.py` 后台补抓**一次**（当天已有
记录则跳过，节流 10 分钟）——见 `tests/dashboard/test_freshness.py`。

【⚠️ 安全 —— 页面里有**持仓指令**】
本服务**默认无鉴权**（只适合可信局域网）。一旦要**远程访问**：

1. **不要**把 8000 端口直接映射到公网 —— 等于公开你的仓位
2. 先建**加密隧道**（Tailscale / 蒲公英 / 路由器 IPSec），详见 `docs/remote-access.md`
3. 再加 `--password 用户名:密码`（HTTP Basic）做**纵深防御**

   ⚠️ Basic 在**纯 HTTP** 下是**明文**传输，所以它**必须**和隧道（或 HTTPS）
   搭配使用，不能单独扛公网。
"""
import base64
import hmac
import os
import re
import socket
import sys

from fg_system import config
from fg_system.dashboard import pwa
from fg_system.dashboard import report

APK_MIME = "application/vnd.android.package-archive"
MANIFEST_MIME = "application/manifest+json"
_ICON_RE = re.compile(r"^/icon-(\d+)\.png$")
_ICON_SIZES = (192, 512)


def render_dashboard(features=None, prices_path=None):
    """渲染一份**新鲜**的仪表盘 HTML（纯计算：不写盘、不改状态、**不抓取**）。"""
    if features is None:
        from fg_system import pipeline
        features = pipeline.run(write=False)     # write=False：只读视图，不落盘
    return report.render_html(features, prices_path=prices_path)


def check_basic_auth(header, user, password):
    """校验 `Authorization: Basic ...`。用 `compare_digest` 防时序侧信道。"""
    if not header or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:].strip()).decode("utf-8")
    except Exception:
        return False
    got_user, sep, got_pass = raw.partition(":")
    if not sep:
        return False
    return (hmac.compare_digest(got_user, user)
            and hmac.compare_digest(got_pass, password))


def parse_auth(spec):
    """把 `user:pass` 解析成 `(user, pass)`；空/非法返回 None。"""
    if not spec:
        return None
    user, sep, password = spec.partition(":")
    if not sep or not user or not password:
        raise ValueError("密码格式应为 用户名:密码，例如 fg:mysecret")
    return user, password


def make_handler(get_features, prices_path=None, apk_path=None, auth=None):
    """构造 Flask 应用（WSGI callable）。

    `get_features()` 在**每次请求**时调用 —— 这正是「打开/刷新即最新」的实现，
    也是用户明确要求的行为（而不是启动时算一次后缓存）。

    路由：
      `GET /`               仪表盘（每次重新计算）
      `GET /manifest.json`  PWA manifest —— 「添加到主屏幕」用
      `GET /icon-N.png`     PWA 图标（N=192/512，**手绘生成，不落盘**）
      `GET /apk`            Android 客户端安装包（**不触发计算**）
      `GET /static/*`       本地静态资源（echarts.min.js 等，离线可用）

    `auth` 为 `(user, password)` 时，**所有路由**都要求 HTTP Basic 认证。
    不设则完全不校验（只适合**可信局域网**）—— 见模块 docstring 的安全说明。
    """
    from flask import Flask, Response, request, send_file

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    if auth:
        @app.before_request
        def _guard():
            # 鉴权放在**最前面**：任何路由（含静态资源）都不能绕过，
            # 未通过时**不返回任何仪表盘内容**。
            if not check_basic_auth(request.headers.get("Authorization"),
                                    auth[0], auth[1]):
                return Response(
                    "需要登录。\n", status=401,
                    headers={
                        "WWW-Authenticate":
                            'Basic realm="fg-dashboard", charset="UTF-8"',
                        "Cache-Control": "no-store",
                    })

    # ---- 首页渲染缓存（2026-10-28）----
    # 缓存 HTML 而不是 features：渲染本身也耗时，缓存结果才能让手机端秒开 ✓
    import threading
    import time
    INDEX_TTL_SEC = 300
    _cache = {"html": None, "ts": 0.0, "busy": False}
    _cache_lock = threading.Lock()

    def _refresh_cache():
        try:
            html = render_dashboard(get_features(), prices_path=prices_path)
            with _cache_lock:
                _cache["html"], _cache["ts"] = html, time.time()
        except Exception:
            pass          # 后台刷新失败 ⇒ 保留旧 HTML，下次请求再试
        finally:
            with _cache_lock:
                _cache["busy"] = False

    @app.route("/manifest.json")
    def _manifest():
        resp = Response(pwa.manifest_json(), mimetype=MANIFEST_MIME)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    _icon_sizes = set(_ICON_SIZES)

    @app.route("/icon-<int:size>.png")
    def _icon(size):
        if size not in _icon_sizes:
            return Response("Not Found", status=404)
        resp = Response(pwa.icon_png(size), mimetype="image/png")
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/apk")
    def _apk():
        p = apk_path or config.APK_PATH
        if not os.path.isfile(p):
            return Response(
                "APK 尚未构建。\n\n在开发机上运行：\n"
                "    bash mobile/build_apk.sh\n\n产物路径：\n    %s\n\n"
                "（本服务只负责分发；构建需要 JDK 21 + Android SDK，"
                "见 mobile/README.md）" % p,
                status=404, mimetype="text/plain; charset=utf-8")
        resp = send_file(p, mimetype=APK_MIME, as_attachment=True,
                         download_name="fg-dashboard.apk")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/api/human30/review", methods=["GET"])
    def _human30_review_endpoint():
        """AI 复盘（H-REV-001，C-3 已审批 2026-10-10）。
        点按生成：阻塞该请求约 30-60s（threaded=True 不阻塞其他请求）；
        模型不可用/超时自动降级确定性统计（见 human30_review.review）。
        返回 {"text": "AI 复盘（🟡 研究参考，非系统信号）：..."}。
        """
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "scripts"))
        try:
            from human30_review import review as _review
            text = _review(days=7)
        except Exception as e:
            text = "AI 复盘（🟡 研究参考，非系统信号）：生成失败（%s），已降级。" % e
        resp = Response(_json_ok({"text": text}), mimetype="application/json")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/static/<path:filename>")
    def _static(filename):
        # 只允许 static/ 目录内的文件，防路径穿越
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        target = os.path.normpath(os.path.join(base, filename))
        if not target.startswith(base) or not os.path.isfile(target):
            return Response("Not Found", status=404)
        resp = send_file(target, conditional=True, max_age=86400)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/realtime")
    def _realtime():
        """富途实时行情状态（futu_realtime.py 常驻服务写入）。无服务时 404。"""
        p = os.path.join(config.DATA_DIR, "realtime_state.json")
        if not os.path.isfile(p):
            return Response("{}", status=404, mimetype="application/json")
        with open(p, encoding="utf-8") as f:
            data = f.read()
        resp = Response(data, mimetype="application/json")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/api/human30", methods=["POST"])
    def _human30_write():
        """Human 3.0 页面打卡写入（Data/human30.json，运行态）。

        入参 JSON：{mind, body, spirit, vocation, note?}，四象限 0-100。
        校验失败 400；成功返回最新记录 + 聚合。当日重复打卡覆盖当日。
        自动附带当日市场快照（Data/features.csv 尾行 fg_index/zone，读不到则无）。
        注：与页面其余部分一样**无鉴权**，仅适合可信局域网（见模块 docstring）。
        """
        from fg_system import human30
        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception:
            payload = {}
        # 问答打卡：{answers: {mind:1-5, body:1-5, spirit:1-5, vocation:1-5}} → 确定性映射转分
        answers = payload.get("answers")
        if isinstance(answers, dict) and any(k in answers for k in human30.QUADRANTS):
            try:
                vals = human30.answers_to_scores(answers)
            except ValueError as e:
                return Response(str(e), status=400,
                                mimetype="text/plain; charset=utf-8")
            note = str(payload.get("note") or "")[:200]
            rec = human30.record(vals["mind"], vals["body"], vals["spirit"],
                                 vals["vocation"], note=note, market=_market_snapshot())
        else:
            vals = {}
            for q in human30.QUADRANTS:
                v = payload.get(q)
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    return Response("参数 %s 必须是 0-100 数字" % q, status=400,
                                    mimetype="text/plain; charset=utf-8")
                if not (0 <= v <= 100):
                    return Response("参数 %s 超出 0-100" % q, status=400,
                                    mimetype="text/plain; charset=utf-8")
                vals[q] = v
            note = str(payload.get("note") or "")[:200]
            rec = human30.record(vals["mind"], vals["body"], vals["spirit"],
                                 vals["vocation"], note=note, market=_market_snapshot())
        agg = human30.aggregate(rec)
        resp = Response(
            _json_ok({"date": rec["date"], "record": rec, "aggregate": agg}),
            mimetype="application/json")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/")
    @app.route("/index.html")
    def _index():
        # 2026-10-07：刷新时检查底层文件新鲜度，过期则后台触发更新
        # （见 freshness.py：节流 10min、守猪待兔仅当天缺失才补、不阻塞页面）。
        try:
            from fg_system.dashboard import freshness
            freshness.check_and_refresh()
        except Exception:
            pass      # 新鲜度检查失败绝不影响页面可用
        # 🔴 2026-10-28：原来每次请求都 `pipeline.run()` 重算整页 ✗ ——
        # 本机 2524 行 0.8s，Mac 全量数据实测「手机上刷新一次要等近 1 分钟」✗。
        # 改成 stale-while-revalidate：有缓存立刻返回（最多旧 INDEX_TTL 秒），
        # 过期由后台线程重算 ⇒ 用户只在服务刚启动那一次需要等 ✓。
        # ⚠️ 数据本身是日频，5 分钟陈旧对结论无影响；实时价走 `/realtime` 另算 ✓。
        # `?fresh=1` ⇒ 跳过缓存强制重算（页面上的「强制重算」按钮走这条）✓
        force = bool(request.args.get("fresh"))
        with _cache_lock:
            cached, cached_ts, busy = _cache["html"], _cache["ts"], _cache["busy"]
        if force:
            cached = None
        if cached is not None:
            if time.time() - cached_ts > INDEX_TTL_SEC and not busy:
                with _cache_lock:
                    _cache["busy"] = True
                threading.Thread(target=_refresh_cache, daemon=True).start()
            resp = Response(cached, mimetype="text/html; charset=utf-8")
            resp.headers["Cache-Control"] = "no-store"   # 浏览器侧仍不许缓存
            resp.headers["X-Render"] = "cache-%ds" % int(time.time() - cached_ts)
            return resp
        try:
            html = render_dashboard(get_features(), prices_path=prices_path)
        except Exception as exc:      # 渲染失败不能把服务搞挂
            return Response("渲染失败：%s: %s" % (type(exc).__name__, exc),
                            status=500, mimetype="text/plain; charset=utf-8")
        with _cache_lock:
            _cache["html"], _cache["ts"] = html, time.time()
        resp = Response(html, mimetype="text/html; charset=utf-8")
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Render"] = "cold"
        return resp

    @app.route("/api/factors")
    def _factors_api():
        """R1.3 分因子独立报告：尾行六因子 分 + 档位 + 方向 + 权重（JSON）。"""
        try:
            import pandas as pd
            from fg_system import config
            from fg_system.index import factor_score_summary
            path = os.path.join(config.ROOT, "Data", "features.csv")
            row = pd.read_csv(path).tail(1).iloc[-1]
            summary = factor_score_summary(row)
            labels = {"vix": "波动率 VIX", "term": "期限利差", "price": "价格动量",
                      "breadth": "市场广度", "fed": "美联储政策", "putcall": "Put-Call 情绪"}
            out = {
                "date": str(row.get("date", "")),
                "fg_index": (float(row["fg_index"]) if pd.notna(row.get("fg_index"))
                             else None),
                "factors": [
                    {
                        "key": k, "label": labels.get(k, k),
                        "score": s["score"], "zone": s["zone"],
                        "zone_name": s["zone_name"], "direction": s["direction"],
                        "weight": s["weight"],
                    }
                    for k, s in summary.items()
                ],
            }
            return _json_ok(out)
        except Exception as exc:
            return Response("factors api 失败：%s: %s" % (type(exc).__name__, exc),
                            status=500, mimetype="text/plain; charset=utf-8")

    # ---- 定时任务监控 API（2026-10-14）：状态查询 + 白名单一键重试 ----

    # 重试白名单：数据项 → 执行方式。
    # 形式：["scripts/相对脚本", 参数...] ｜ ["-c", "代码"] ｜
    #      ["launchctl:{kickstart 子命令}"]（重试 launchd 任务本身，
    #      含 <uid> 占位；shoutu 系走任务，保持"shoutu 抓取由定时任务独占"纪律）。
    # **只允许这些映射**，绝不执行任意命令（页面按钮无法注入命令）。
    _RETRY_MAP = {
        "vix":            ["scripts/fetch_sentiment.py"],
        "sentiment":      ["scripts/fetch_sentiment.py"],
        "funding_rate":   ["scripts/fetch_sentiment.py"],
        "putcall":        ["scripts/fetch_putcall.py"],
        "fedwatch":       ["scripts/fetch_fedwatch.py"],
        "kalshi_fed":     ["scripts/fetch_kalshi_fed.py"],
        "shoutu_fng":     ["launchctl:kickstart gui/<uid>/com.xingguo.fg-shoutu-refresh"],
        "shoutu_history": ["launchctl:kickstart gui/<uid>/com.fg.shoutu-history"],
        "news_sentiment": ["scripts/fetch_news.py"],
        "stablecoin_usage": ["scripts/fetch_stablecoin_usage.py", "--incremental"],
        "fred_dff":   ["scripts/fetch_fred.py", "--series", "DFF,DGS10,T10Y2Y"],
        "fred_dgs10": ["scripts/fetch_fred.py", "--series", "DFF,DGS10,T10Y2Y"],
        "fred_t10y2y": ["scripts/fetch_fred.py", "--series", "DFF,DGS10,T10Y2Y"],
        "prices":         ["-c", "from fg_system.data import fetch; fetch.update_prices()"],
        "features":       ["-c", "from fg_system import pipeline; pipeline.run(write=True)"],
    }

    @app.route("/api/symbol_fg")
    def _symbol_fg_api():
        """按标的查**系统贪恐系数**（个股级 0-100，高分=贪婪）。

        复用 `scripts/query_symbol_fg.query()` ✓ —— 与看板「系统」列、CLI **同源** ✓，
        **不在此处重写算法** ✗。

        参数：`symbols=NVDA,GDXU`（逗号分隔，中文逗号也认 ✓，最多 12 个 ✓）
        返回：`{"data_date": "...", "items": [{symbol, underlying, rows,
                value, zone, source, error}]}`

        🔴 `source` **三态必须透出** ✗（否则页面无法分辨 ✗）：
          - `个股` ✓ —— 真正的个股分；
          - `大盘回退` ✓ —— 已登记但底层历史 < 816 行 ✗，`error` 里写明行数；
          - `null` ✗ —— **未登记** ⇒ `value` 也为 `null` ✗（**绝不给大盘分冒充** ✗）。
        `data_date` 是市场级 `fg_index` 的数据日期 ✓ —— 页面必须显示它 ✗，
        否则用户会把几周前的数字当成「现在」✗。
        """
        import importlib.util

        from fg_system import config as _cfg

        raw = (request.args.get("symbols") or "").replace("，", ",")
        syms = [s.strip().upper() for s in raw.split(",") if s.strip()][:12]
        if not syms:
            # ⚠️ `_json_ok` 返回**字符串** ✗ ⇒ 必须显式给 `application/json` ✓，
            # 否则前端 `r.json()` 拿不到对象 ✗（2026-10-20 实测踩到 ✓）
            return Response(_json_ok({"error": "缺 symbols 参数（例：?symbols=NVDA,GDXU）",
                                      "items": []}),
                            status=400, mimetype="application/json")

        # 🔴 整段包 try ✗ —— 原来异常会返回 Flask 默认 **500 HTML** ✗，
        # 前端 `r.json()` 直接抛错 ✓（与 400 分支的 `application/json` 自相矛盾 ✗）
        try:
            path = os.path.join(_cfg.ROOT, "scripts", "query_symbol_fg.py")
            spec = importlib.util.spec_from_file_location("query_symbol_fg", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            prices = None
            p = os.path.join(_cfg.RAW_DIR, "prices.csv")
            if os.path.exists(p):
                import pandas as pd
                prices = pd.read_csv(p, dtype={"symbol": str},
                                     parse_dates=["date"])

            items = [mod.query(s, prices=prices) for s in syms]
            _fg, data_date = mod._market_fg()
            return Response(_json_ok({"data_date": data_date, "items": items}),
                            mimetype="application/json")
        except Exception as exc:      # noqa: BLE001 —— 任何异常都必须回 JSON ✓
            return Response(
                _json_ok({"error": "查询失败：%s: %s"
                                   % (type(exc).__name__, exc), "items": []}),
                status=500, mimetype="application/json")

    @app.route("/api/watchlist_3x")
    def _watchlist_3x_api():
        """MT-66：3× 做多 ETF 关注列表（纯本地 CSV，**不联网** ✓）。

        每行：官网现价（universe）+ 系统贪恐个股分（query()）+ 守猪待兔分
        （复用 `_shoutu_of()` ✓）。底层未登记 ⇒ 贪恐分 `null` ✗（不给大盘分冒充 ✓）。
        """
        import importlib.util

        from fg_system import config as _cfg

        try:
            wl_path = os.path.join(_cfg.RAW_DIR, "watchlist_3x.csv")
            if not os.path.exists(wl_path):
                return Response(_json_ok(
                    {"error": "关注清单缺失，请先跑 scripts/build_watchlist_3x.py",
                     "items": []}), status=404, mimetype="application/json")

            import pandas as pd
            wl = pd.read_csv(wl_path, dtype={"symbol": str, "name": str,
                                             "underlying": str})

            # 市场级数据日期（与 /api/symbol_fg 同源 ✓）
            qpath = os.path.join(_cfg.ROOT, "scripts", "query_symbol_fg.py")
            spec = importlib.util.spec_from_file_location("query_symbol_fg", qpath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            prices = None
            p = os.path.join(_cfg.RAW_DIR, "prices.csv")
            if os.path.exists(p):
                prices = pd.read_csv(p, dtype={"symbol": str},
                                     parse_dates=["date"])

            # universe 最新日（官网现价口径日期 ✓）
            as_of = None
            up = os.path.join(_cfg.RAW_DIR, "shoutu_etf_universe.csv")
            if os.path.exists(up):
                as_of = str(pd.read_csv(up, usecols=["date"])["date"].max())[:10]

            items = []
            for _, r in wl.iterrows():
                sym = str(r["symbol"]).strip().upper()
                q = mod.query(sym, prices=prices, auto=False)
                items.append({
                    "symbol": sym,
                    "name": str(r["name"]),
                    "underlying": q.get("underlying") or r.get("underlying"),
                    "list_source": r.get("source"),
                    "price": r.get("price"),
                    "universe_fg": r.get("universe_fg"),
                    "fg_value": q.get("value"),
                    "fg_zone": q.get("zone"),
                    "fg_source": q.get("source"),
                    "fg_date": q.get("date"),
                    "fg_stale": q.get("stale", False),
                    "shoutu": q.get("shoutu"),
                    "shoutu_zone": q.get("shoutu_zone"),
                    "shoutu_date": q.get("shoutu_date"),
                    "shoutu_stale": q.get("shoutu_stale", False),
                })
            _fg, data_date = mod._market_fg()
            return Response(_json_ok({"as_of": as_of, "data_date": data_date,
                                      "items": items}),
                            mimetype="application/json")
        except Exception as exc:      # noqa: BLE001
            return Response(
                _json_ok({"error": "关注列表失败：%s: %s"
                                   % (type(exc).__name__, exc), "items": []}),
                status=500, mimetype="application/json")

    @app.route("/api/tasks")
    def _tasks_api():
        """定时任务与数据新鲜度状态（复用 scripts/task_monitor.collect_status）。"""
        import datetime as _dt
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            if root not in sys.path:
                sys.path.insert(0, root)
            from scripts import task_monitor as _tm
            st = _tm.collect_status()
            out = {
                "checked_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "all_ok": st["all_ok"],
                "issues": st["issues"],
                "data": st["data"],
                "tasks": st["tasks"],
            }
            resp = Response(_json_ok(out), mimetype="application/json")
            resp.headers["Cache-Control"] = "no-store"
            return resp
        except Exception as exc:
            return Response("tasks api 失败：%s: %s" % (type(exc).__name__, exc),
                            status=500, mimetype="text/plain; charset=utf-8")

    @app.route("/api/tasks/retry", methods=["POST"])
    def _tasks_retry():
        """页面「重试」：白名单映射 → 后台执行对应抓取/合成脚本，立即返回。

        互斥：Data/task_retry.lock 记 target+pid，进程存活时拒绝新重试
        （同一时刻只允许一个重试在跑，防重复触发与写盘冲突）。
        日志：logs/task_retry.log（追加）。
        """
        import datetime as _dt
        import json as _json
        import subprocess as _sp
        payload = request.get_json(force=True, silent=True) or {}
        target = str(payload.get("target") or "")
        cmd = _RETRY_MAP.get(target)
        if not cmd:
            return Response("不支持的 target：%s" % target, status=400,
                            mimetype="text/plain; charset=utf-8")

        lock_p = os.path.join(config.DATA_DIR, "task_retry.lock")
        if os.path.exists(lock_p):
            try:
                with open(lock_p, encoding="utf-8") as f:
                    d = _json.load(f)
                try:
                    os.kill(int(d.get("pid", -1)), 0)
                    return Response("已有重试正在运行（%s，PID %s），请稍候再试"
                                    % (d.get("target"), d.get("pid")),
                                    status=409, mimetype="text/plain; charset=utf-8")
                except (ProcessLookupError, ValueError, TypeError):
                    pass
            except Exception:
                pass

        if cmd[0] == "-c":
            full = [sys.executable, "-c", cmd[1]]
        elif cmd[0].startswith("launchctl:"):
            import shlex as _shlex
            spec = cmd[0].split(":", 1)[1].replace("<uid>", str(os.getuid()))
            full = ["launchctl"] + _shlex.split(spec)
        else:
            full = [sys.executable,
                    os.path.join(config.ROOT, cmd[0])] + list(cmd[1:])
        log = os.path.join(config.ROOT, "logs", "task_retry.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n=== %s 重试 %s ===\n"
                    % (_dt.datetime.now().isoformat(timespec="seconds"), target))
        proc = _sp.Popen(full, cwd=config.ROOT,
                         stdout=open(log, "a", encoding="utf-8"),
                         stderr=_sp.STDOUT)
        with open(lock_p, "w", encoding="utf-8") as f:
            _json.dump({"target": target, "pid": proc.pid,
                        "started": _dt.datetime.now().isoformat(timespec="seconds")}, f)
        return _json_ok({"ok": True, "target": target, "pid": proc.pid})

    @app.route("/api/sync_health")
    def _sync_health_api():
        """同步链路体检（2026-10-28）：读 Mac 本地四个观测点，给出「卡在哪一段」的结论。

        Windows 侧只能看到「已发」和「gitee 有无新提交」两头 ✗，
        中间态（消息积压 / bypass 未跑 / 半收滞留 / 回执失败）只有 Mac 本地看得见 ✓。
        """
        from fg_system.dashboard import sync_health as _sh
        try:
            resp = Response(_json_ok(_sh.collect()), mimetype="application/json")
            resp.headers["Cache-Control"] = "no-store"
            return resp
        except Exception as exc:
            return Response("sync_health 失败：%s: %s" % (type(exc).__name__, exc),
                            status=500, mimetype="text/plain; charset=utf-8")

    @app.route("/api/task_queue")
    def _task_queue_api():
        """任务队列状态（只读）：读 `docs/task-queue/*.json`，result 覆盖 pending。

        2026-10-28：页面上的一次性动作改为「任务下发」后，这里就是它的状态面板 ✓
        （下发方看得到 done/failed/耗时，失败还带输出尾巴）。
        """
        import glob as _glob
        import json as _json
        q = os.path.join(config.ROOT, "docs", "task-queue")
        merged = {}
        for p in _glob.glob(os.path.join(q, "*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    d = _json.load(f)
            except (OSError, ValueError):
                continue
            tid = d.get("id") or os.path.basename(p)
            status = str(d.get("status") or "pending")
            item = {"id": tid, "action": d.get("action"), "status": status,
                    "at": d.get("finished_at") or d.get("created_at"),
                    "duration_s": d.get("duration_s"),
                    "output": str(d.get("output") or "")[:160]}
            if tid not in merged or status != "pending":
                merged[tid] = item
        items = sorted(merged.values(), key=lambda x: str(x.get("at") or ""),
                       reverse=True)[:10]
        agent = {}
        try:
            from scripts import run_task_queue as _rtq
            agent = _rtq.agent_status()
        except Exception:
            pass
        resp = Response(_json_ok({"items": items, "agent": agent}),
                        mimetype="application/json")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/api/install_agent", methods=["POST"])
    def _install_agent():
        """安装任务队列的 launchd 定时器（看板本身跑在 Mac 上，有权限 ✓）。

        安全边界：源是仓库里固定的 plist、目标是固定的 `~/Library/LaunchAgents`、
        不接受任何用户输入、重复点会先 bootout 再 bootstrap（幂等）✓。
        """
        payload = request.get_json(force=True, silent=True) or {}
        if str(payload.get("confirm") or "") != "install_agent":
            return Response("需要二次确认：POST {\"confirm\": \"install_agent\"}",
                            status=400, mimetype="text/plain; charset=utf-8")
        from scripts import run_task_queue as _rtq
        try:
            r = _rtq.install_agent()
        except Exception as exc:
            return Response("安装失败：%s: %s" % (type(exc).__name__, exc),
                            status=500, mimetype="text/plain; charset=utf-8")
        return _json_ok(r)

    @app.route("/api/sync_cleanup", methods=["POST"])
    def _sync_cleanup():
        """清理插件层堆积：把 30 分钟前的历史文件**挪进 archive 子目录**（不删 ✓）。

        为什么做成按钮而不是让 Mac 侧 agent 干：清理是「看一眼就知道该不该做」的事，
        而 agent 要耗一次会话 + 还得给它写权限 ✗。
        🔴 安全（本服务默认无鉴权）：
          ① 必须带 `{"confirm": "cleanup"}`；
          ② **只挪不删** ⇒ 挪错了 `mv archive_xxx/* .` 就能还原 ✓；
          ③ 只动 `fg-sync-bypass-in/` 里 30 分钟前的 `.md` ——
             不碰 `fg-sync-in/`（那是待入库分片，动了会丢包 ✗）、不碰 `Data/` ✓。
        """
        payload = request.get_json(force=True, silent=True) or {}
        if str(payload.get("confirm") or "") != "cleanup":
            return Response("需要二次确认：POST {\"confirm\": \"cleanup\"}",
                            status=400, mimetype="text/plain; charset=utf-8")
        from fg_system.dashboard import sync_health as _sh
        try:
            r = _sh.archive_backlog()
        except Exception as exc:
            return Response("清理失败：%s: %s" % (type(exc).__name__, exc),
                            status=500, mimetype="text/plain; charset=utf-8")
        out = {"ok": r["moved"] > 0}
        out.update(r)
        return _json_ok(out)

    @app.route("/api/deploy", methods=["POST"])
    def _deploy():
        """一键部署：`git fetch origin main` + `git merge --ff-only origin/main`，再重启看板。

        🔴 安全（本服务默认**无鉴权**，只靠 Tailscale ⇒ 这是唯一会改代码的入口 ✗）：
          ① 必须带 `{"confirm": "deploy"}` 二次确认（防误触；GET 不可触发）；
          ② 只跑**固定命令**，不接受任何用户参数 ✗（无注入面）；
          ③ `Data/deploy.lock` 互斥，同一时刻只允许一个部署；
          ④ 日志 `logs/deploy.log`，返回 tail 便于手机上直接看结果 ✓。

        ⚠️ 用 `merge --ff-only` 而不是 `git pull`：Mac 上 `evolution/lookahead-audit.*`
           会被测试改写而变脏 ✗，`pull` 会因「工作区不干净」直接拒绝 ✗；
           `merge` 只在**会被覆盖**的文件脏时才拒绝 ✓（2026-10-28 Windows 侧同型实测）。
        """
        import datetime as _dt
        import json as _json
        import subprocess as _sp
        payload = request.get_json(force=True, silent=True) or {}
        if str(payload.get("confirm") or "") != "deploy":
            return Response("需要二次确认：POST {\"confirm\": \"deploy\"}",
                            status=400, mimetype="text/plain; charset=utf-8")

        lock_p = os.path.join(config.DATA_DIR, "deploy.lock")
        if os.path.exists(lock_p):
            try:
                with open(lock_p, encoding="utf-8") as f:
                    d = _json.load(f)
                os.kill(int(d.get("pid", -1)), 0)
                return Response("已有部署在跑（PID %s），请稍候" % d.get("pid"),
                                status=409, mimetype="text/plain; charset=utf-8")
            except (ProcessLookupError, ValueError, TypeError, OSError):
                pass                      # 旧锁的进程已死 ⇒ 继续

        log = os.path.join(config.ROOT, "logs", "deploy.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(lock_p, "w", encoding="utf-8") as f:
            _json.dump({"pid": os.getpid(),
                        "started": _dt.datetime.now().isoformat(timespec="seconds")}, f)
        lines = ["", "=== %s 部署开始 ===" % _dt.datetime.now().isoformat(timespec="seconds")]
        old, best, url, behind = "", None, None, 0
        try:
            def _git(*args):
                r = _sp.run(["git"] + list(args), cwd=config.ROOT,
                            capture_output=True, text=True, timeout=180)
                lines.append("$ git %s\n%s%s" % (" ".join(args), r.stdout, r.stderr))
                return r

            old = _git("rev-parse", "--short", "HEAD").stdout.strip()
            branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            # 🔴 2026-10-28 修正：**不能写死 origin** ✗ —— Mac 的 origin 可能是 github，
            # 而代码实际从 gitee 进来 ⇒ `fetch origin` 拿到的是旧的 ⇒ 页面显示「无变更」
            # 却根本没部署 ✗（用户实测「一键部署不生效」就是这个）。
            # ⇒ fetch --all，然后在所有 `*/main` 里挑**落后最多**的那个部署 ✓
            _git("fetch", "--all", "--prune")
            remotes = []
            for r in _git("remote").stdout.split():
                if _git("rev-parse", "--verify", "-q", r + "/main").returncode == 0:
                    remotes.append(r)
            if not remotes:
                raise RuntimeError("没有任何远程的 main 分支可部署（fetch --all 之后仍无）")
            best, best_behind = None, -1
            for r in remotes:
                c = _git("rev-list", "--left-right", "--count",
                         "HEAD..." + r + "/main").stdout.split()
                b = int(c[1]) if len(c) > 1 else 0
                lines.append("  %s/main 落后 %d" % (r, b))
                if b > best_behind:
                    best, best_behind = r, b
            ref = best + "/main"
            url = _git("remote", "get-url", best).stdout.strip()
            lines.append("选用远程 %s（%s）" % (best, url))
            # 🔴 分叉守卫（2026-10-28）：本地有未推送提交时 `--ff-only` 必然失败 ✗，
            # 而原始 git 报错对手机上的用户毫无意义 ✗ ⇒ 提前算清楚并给出可执行的结论 ✓
            cnt = _git("rev-list", "--left-right", "--count", "HEAD..." + ref).stdout.split()
            ahead = int(cnt[0]) if cnt else 0
            behind = int(cnt[1]) if len(cnt) > 1 else 0
            lines.append("分支 %s · 领先 %d · 落后 %d" % (branch, ahead, behind))
            if ahead:
                # 领先但**内容完全一致**（只是提交元数据不同，例如入库后又被收平过）
                # ⇒ 安全对齐 ✓（用 --mixed：只动 HEAD 与索引，工作区文件一个不碰 ✓）
                if _git("diff", "--quiet", ref, "HEAD").returncode == 0:
                    _git("reset", "--mixed", ref)
                    lines.append("领先 %d 但内容一致 ⇒ 已对齐到 %s（工作区未动）" % (ahead, ref))
                    ahead = 0
                else:
                    raise RuntimeError(
                        "本地分支 %s 有 %d 个未推送提交且**含实际改动** ⇒ "
                        "自动丢弃会丢代码 ✗。先在 Mac 上 `git push`，"
                        "或确认这些改动不要了再 `git reset --hard %s`"
                        % (branch, ahead, ref))
            if behind:
                _git("merge", "--ff-only", ref)
            new = _git("rev-parse", "--short", "HEAD").stdout.strip()
            lines.append("HEAD %s → %s%s" % (old, new, "" if old != new else "（无变化）"))
            ok, err = True, None
        except Exception as exc:
            new, ok, err = old, False, str(exc)
            lines.append("❌ " + err)
        finally:
            try:
                os.remove(lock_p)
            except OSError:
                pass
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        # 代码变了才重启（Flask 不会自动重载 .py ⇒ 不重启等于没部署 ✗）。
        restarted = ok and old != new and _schedule_restart()
        return _json_ok({"ok": ok, "old": old, "new": new, "error": err,
                         "remote": best, "url": url, "behind": behind,
                         "restart_scheduled": restarted,
                         "log_tail": "\n".join(lines[-8:])})

    @app.route("/api/restart", methods=["POST"])
    def _restart():
        """**只**重启看板服务（不碰 git）—— 改了 `.py` 但 HEAD 没变时用。

        典型场景（2026-10-28）：Mac 入库时自己 commit 了 ⇒ HEAD 已是最新 ⇒
        「一键部署」会报「无变更，未重启」✗，但新代码还没被 Flask 加载 ✗。
        这里给一个纯粹的「重启」入口，免去进终端敲 launchctl ✓。
        """
        import json as _json
        payload = request.get_json(force=True, silent=True) or {}
        if str(payload.get("confirm") or "") != "restart":
            return Response("需要二次确认：POST {\"confirm\": \"restart\"}",
                            status=400, mimetype="text/plain; charset=utf-8")
        if sys.platform != "darwin":
            return Response("只有 macOS（launchd）支持重启，当前平台：%s" % sys.platform,
                            status=501, mimetype="text/plain; charset=utf-8")
        if not _schedule_restart():
            return Response("重启调度失败（launchctl 不可用？）", status=500,
                            mimetype="text/plain; charset=utf-8")
        return _json_ok({"ok": True, "restart_scheduled": True})

    return app


def _market_snapshot():
    """读 Data/features.csv 尾行取 fg_index/zone（打卡市场快照，读不到返回 None）。"""
    import csv as _csv
    p = os.path.join(config.DATA_DIR, "features.csv")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8-sig") as f:
            rows = list(_csv.DictReader(f))
        if not rows:
            return None
        last = rows[-1]
        return {"fg_index": float(last["fg_index"]), "zone": int(float(last["zone"]))}
    except Exception:
        return None


def _json_ok(obj):
    import json as _json
    return _json.dumps(obj, ensure_ascii=False, default=str)


#: 看板服务的 launchd 标签（重启用）
DASHBOARD_LABEL = "com.xingguo.fg-dashboard"


def _schedule_restart(delay=2):
    """调度看板服务重启，成功返回 True。

    🔴 必须**延迟 + 脱离**：`launchctl kickstart -k` 会立刻杀掉当前进程 ✗，
    在请求处理中直接调用会丢掉 HTTP 响应 ✗ ⇒ 起一个脱离的 sh，睡几秒再踢 ✓。
    非 macOS 直接返回 False（Windows 开发机上无 launchd）。
    """
    import subprocess as _sp
    if sys.platform != "darwin":
        return False
    try:
        _sp.Popen(["/bin/sh", "-c",
                   "sleep %d; launchctl kickstart -k gui/%d/%s"
                   % (delay, os.getuid(), DASHBOARD_LABEL)],
                  start_new_session=True,
                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        return True
    except Exception:
        return False


def make_server(host="0.0.0.0", port=8000, get_features=None, prices_path=None,
                apk_path=None, auth=None):
    """创建（**未启动**的）WSGI HTTP 服务。`port=0` 表示随机端口（测试用）。

    返回对象兼容旧接口：`serve_forever()` / `server_close()` / `server_address`。
    `auth` 为 `(user, password)` 时要求 HTTP Basic 认证，见 `make_handler`。
    """
    if get_features is None:
        def get_features():
            from fg_system import pipeline
            return pipeline.run(write=False)
    from werkzeug.serving import make_server as wsgi_server
    return wsgi_server(host, port, make_handler(
        get_features, prices_path=prices_path, apk_path=apk_path, auth=auth),
        threaded=True)


# ============================================================ 手机该访问哪个地址
# 「手机上怎么访问」是启动服务后**第一个**会卡住的问题。
# 一台机器常有多个网卡（Wi-Fi / 有线 / VPN / Docker），**只猜一个很容易猜错**，
# 所以把候选**都列出来**让用户换着试。

def _is_usable(ip):
    """排除回环与链路本地（169.254.x.x，通常意味着没连上网）。"""
    return not (ip.startswith("127.") or ip.startswith("169.254."))


def _primary_ip():
    """内核选出的默认出口 IP —— 最可能是手机该用的那个。

    连 UDP 8.8.8.8 不会**真的发包**，只是让内核按路由表挑一个源地址。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


def _hostname_ips():
    """本机主机名解析出的所有 IPv4（作为补充候选）。"""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out:
                out.append(ip)
    except Exception:
        pass
    return out


def lan_addresses():
    """返回 `(primary, others)` —— 手机可用的局域网 IP。

    `primary` 最可能对；`others` 是其余候选（换着试）。
    一个都没有时 `primary` 为 None（例如只绑了 127.0.0.1）。
    """
    primary = _primary_ip()
    if primary is not None and not _is_usable(primary):
        primary = None

    others = [ip for ip in _hostname_ips()
              if _is_usable(ip) and ip != primary]
    if primary is None and others:
        primary = others.pop(0)
    return primary, others


def bonjour_name():
    """macOS 上 `<主机名>.local` 经 Bonjour 可直接解析 —— **换 IP 也能用**。

    非 macOS 返回 None（Windows 需要额外装 Bonjour 服务）。
    """
    if sys.platform != "darwin":
        return None
    host = socket.gethostname()
    if not host:
        return None
    return host if host.endswith(".local") else host + ".local"
