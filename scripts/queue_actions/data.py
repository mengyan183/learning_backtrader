# -*- coding: utf-8 -*-
"""数据抓取 / 审计 action ✓ —— 从 `run_task_queue.py` 拆出的第五个动作包。

【边界】
  · 只依赖 `queue_core`（`ROOT` / `run` / `safe_rel` / `READ_ALLOW`）+ 标准库 ✓
  · **不碰队列状态** ✗ —— `QUEUE` / `run_once` / flock 在调度器里
  · `FETCH_SCRIPTS`（`run_fetch_step` 的脚本白名单）随包走 ✓
"""
import glob
import os
import subprocess
import sys
import time

from queue_core import (ROOT, READ_ALLOW as _READ_ALLOW, run as _run,
                        safe_rel as _safe_rel)


def _act_audit_data(params):
    """**数据文件审计** ✓（谁读谁写 ⇒ 在用/孤儿/死文件）。

    🔴 必须在 **Mac** 跑 ✗ —— Windows 的 `Data/raw/` 只是旧快照 ✗
       （2026-11-03 用户澄清）
    """
    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "audit_data_files.py")]
    js = params.get("json") or "evolution/experiments/factor-adoption/data-audit.json"
    cmd += ["--json", str(js)]
    try:
        # 🔴 2026-11-03：`text=True` 在 Windows 用 **GBK** 解码 ✗
        #    而审计输出含 `✓`/`✗` ⇒ `UnicodeDecodeError` ✗（Mac 上无此问题 ✓）
        #    ⇒ 显式指定 utf-8 + replace ✓ 两边都稳 ✓
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超过 900 秒"}

    # 🔴 2026-11-03：**只回汇总 + 分类文件名** ✗ —— 全表 39 行会撑爆
    #    `_write_result` 的 8000 上限 ✗ 且 JSON 被截断就没法解析 ✗
    #    ⇒ 明细落盘（`--json`）✓ 返回值只带「能行动的结论」✓
    summary, groups = {}, {"used": [], "read_only": [], "orphan": [], "dead": []}
    try:
        import json as _json
        ap = os.path.join(ROOT, str(js))
        with open(ap, "r", encoding="utf-8") as f:
            data = _json.load(f)
        for name, rec in (data.get("audit") or {}).items():
            w, rd = len(rec.get("writers") or []), len(rec.get("readers") or [])
            if w and rd:
                groups["used"].append(name)
            elif rd:
                groups["read_only"].append(name)
            elif w:
                groups["orphan"].append(name)
            else:
                groups["dead"].append(name)
        summary = {k: len(v) for k, v in groups.items()}
    except Exception as exc:                # noqa: BLE001
        summary = {"error": str(exc)[:120]}

    return {"ok": r.returncode == 0,
            "json": js,
            "summary": summary,
            "groups": groups,
            # 🔴 2026-11-03 踩坑：`"~10% 误判 ... %s" % js` ✗
            #    第一个 `%` 后面跟的是中文「误」✗ ⇒
            #    `ValueError: unsupported format character '误' (0x8bef)` ✗
            #    ⇒ 任务直接 `failed` ✗ 整个动作白跑 ✗
            #    ⇒ 改用 `.format()` ✓ 不受 `%` 影响 ✓
            "note": ("⚠️ 审计有 ~10% 误判 ✗（动态拼名/消费者在别处 ✗）"
                     " ⇒ 删文件前务必人工复核 ✓；明细见 `{f}`").format(f=js),
            "stdout": (r.stdout or "")[-1200:],
            "stderr": (r.stderr or "")[-400:]}


def _act_prune_dead_data(params):
    """**删死文件** ✓（2026-11-03 用户裁定「死文件要删」）。

    安全措施：
      ① 默认 **dry-run** ✓ —— 必须显式 `apply=1` 才真删 ✗
      ② 真删前**备份**到 `dist/pruned/` ✓
      ③ 只删 `Data/raw/` 下**明确列出**的文件 ✓ 不递归扫 ✗
      ④ `Data/raw/` 已 gitignore ⇒ **git 不会有任何改动** ✓

    参数：
      - `apply`：`1` = 真删 ✓（默认只看 ✗）
      - `restore`：`1` = **全部从 `dist/pruned/` 恢复** ✓
        （2026-11-03 误删事故后加的 ✗）
      - `restore_files`：逗号分隔的**指定文件名** ✓ 优先于 `restore`
    """
    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "prune_dead_data.py")]
    rf = str(params.get("restore_files") or "").strip()
    if rf:
        cmd.append("--restore")
        cmd += [x.strip() for x in rf.split(",") if x.strip()]
    elif str(params.get("restore") or "").lower() in ("1", "true", "yes"):
        cmd.append("--restore")
    elif str(params.get("apply") or "").lower() in ("1", "true", "yes"):
        cmd.append("--apply")
    try:
        r = _run(cmd, 600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超过 600 秒"}
    return {"ok": r.returncode == 0,
            "applied": "--apply" in cmd,
            "note": "误删可从 `dist/pruned/` 拷回 ✓",
            "stdout": (r.stdout or "")[-5000:],
            "stderr": (r.stderr or "")[-400:]}
#: 🔴 `run_fetch_step` 的**脚本白名单** ✓（2026-11-03）
#: 为什么必须白名单：这个动作会**执行任意命令** ✗ 若不加限，
#: 一个拼错的任务 json 就能跑 `rm -rf` ✗


FETCH_SCRIPTS = (
    "fetch_sentiment.py", "fetch_putcall.py", "fetch_kalshi_fed.py",
    "fetch_fred.py", "fetch_fedwatch.py", "fetch_shoutu_api.py",
    "fetch_stablecoin_usage.py", "fetch_news.py", "fetch_trades_futu.py",
    # 🔴 2026-11-04：补 `shoutu_history.csv`（停在 10-14 ✗ 21 天）
    #    它是**服务端权威日值**（每只 ~600 天 ✗ 研究/回测用 ✗）
    #    ⚠️ **不在每日链里**（需会员 ✗ 至 2027-01-16）⇒ 只能手工/按需跑 ✓
    #    ⚠️ 缺口会**永久丢失** ✗（服务端只给最近 N 天 ✗）⇒ 该补 ✓
    "fetch_shoutu_history.py",
    # 🔴 2026-11-04：CME 改用 **bsk**（真实浏览器 ✗ headless 拿不到数据 ✗）
    # 🔴 2026-11-05：**最终方案** ✓ 富途 OpenD 官方接口 ✗ 不是爬虫 ✓
    #    市面调研结论：
    #      cme-fedwatch（PyPI）⇒ 已停维护 ✗
    #      fed-funds-target.json ⇒ 404 ✗
    #      curl_cffi/nodriver/FlareSolverr ⇒ 解决不了 iframe+Referer ✗
    #    富途 `get_fed_watch_target_rate()` ⇒ **官方** ✓ 零新增依赖 ✓
    "fetch_fedwatch_futu.py",
    # 🔴 2026-11-10：补 `sync_positions.py` ✓ —— 持仓停更 4 天（11-06）
    #    根因是 OpenD 挂了 ✗ 现在 OpenD 已恢复（`test_futu_fed` ret=0 / 1.28s）✓
    #    ⇒ 需要手动触发一次把 `positions.csv` 推到最新 ✓
    #    ⚠️ 它**不在每日链的 fetch 段**，而是由 `fg-daily` 串在 pipeline 之后 ✓
    "sync_positions.py",
)


def _act_update_crypto(params):
    """**补抓加密数据** ✓（2026-11-03 用户要求）。

    🔴 为什么单独做一个动作：
       `crypto_prices.csv` / `crypto_underlying.csv` 停在 **2026-09-29**（35 天 ✗）
       而它们由每日链里的 `python -c "fetch.update_crypto_prices();
       fetch.update_crypto_aux()"` 生成 ✗（`guard#7`）
       ⇒ 那不是独立脚本 ✗ `run_fetch_step` 的白名单覆盖不到 ✗
       ⇒ 单独做一个 ✓

    【和 `run_fetch_step` 一样对比跑前后日期】✓
    参数：`aux`（默认 1，顺带跑 `update_crypto_aux()` ✓）
    """
    do_aux = str(params.get("aux") or "1").lower() in ("1", "true", "yes")
    code = ("from fg_system.data import fetch;"
            "print('prices:', fetch.update_crypto_prices())")
    if do_aux:
        code += ";print('aux:', fetch.update_crypto_aux())"

    def _snap():
        import glob as _g
        snap = {}
        for p in _g.glob(os.path.join(ROOT, "Data", "raw", "*.csv")):
            name = os.path.basename(p)
            if not any(k in name for k in ("crypto", "btc", "eth")):
                continue
            try:
                import pandas as _pd
                last = None
                for col in ("date", "observation_date"):
                    try:
                        d = _pd.read_csv(p, usecols=[col], parse_dates=[col])
                        last = d[col].max()
                        break
                    except Exception:       # noqa: BLE001
                        continue
                snap[name] = (str(last.date())
                              if last is not None and _pd.notna(last) else "?")
            except Exception:               # noqa: BLE001
                snap[name] = "?"
        return snap

    before = _snap()
    t0 = time.time()
    try:
        r = _run([sys.executable, "-c", code], 1800)
        rc, so, se = r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        rc, so, se = 124, "", "超过 1800 秒"
    secs = time.time() - t0
    after = _snap()

    changed = {k: {"before": before.get(k), "after": v}
               for k, v in after.items() if before.get(k) != v}
    return {"ok": rc == 0, "rc": rc, "seconds": round(secs, 1),
            "aux": do_aux, "before": before, "after": after,
            "changed": changed,
            "verdict": ("rc=%d 但**加密文件无更新** ✗ ⇒ 静默失败 ✗"
                        % rc if rc == 0 and not changed
                        else "rc=%d，更新 %d 个" % (rc, len(changed))),
            "stdout": so[-4000:], "stderr": se[-2000:]}


def _act_run_fetch_step(params):
    """**单独重跑一个 fetch 脚本** ✓ 并对比跑前/跑后的数据日期。

    【为什么需要（2026-11-03）】
      7 个数据源在每日链里 `rc=0` ✗ 但数据停在 10-11~10-13 ✗
      ⇒ 链日志只记 rc ✗ **看不到脚本自己的输出** ✗
      ⇒ 必须单独跑一次，看它到底说了什么 ✓

    【本动作回答三个问题】
      ① 脚本**报错了吗**（stderr / 非 0 rc）✓
      ② 脚本**说成功但没写**吗（`before == after` ✗）✓ ← 最关键
      ③ 卡在**哪个环节**（完整 stdout 里有分步打印 ✓）

    参数：
      - `script`：**必须**是 `FETCH_SCRIPTS` 里的一个 ✓
      - `args`：额外参数（逗号分隔 ✗ 会被原样传给脚本 ✓）
      - `timeout`：默认 900 秒 ✓
    """
    script = str(params.get("script") or "").strip()
    if script not in FETCH_SCRIPTS:
        return {"ok": False,
                "error": "不允许的脚本：`%s` ✗（白名单：%s）"
                         % (script, ", ".join(FETCH_SCRIPTS))}

    raw_args = str(params.get("args") or "").strip()
    extra = [a for a in raw_args.split(",") if a] if raw_args else []
    limit = int(params.get("timeout") or 900)

    # ① 跑前快照 ✓ —— 只对比该脚本**可能写**的文件（全量太多 ✗）
    def _snap():
        import glob as _g
        snap = {}
        # 🔴 2026-11-10：原来只扫 `Data/raw/*.csv` ✗
        #    而 `sync_positions.py` 写的是 **`Data/positions.csv`**（顶层 ✗）
        #    ⇒ 快照漏掉它 ⇒ 跑完看不出「有没有更新」✗ ⇒ 两层都扫 ✓
        for p in (_g.glob(os.path.join(ROOT, "Data", "raw", "*.csv"))
                  + _g.glob(os.path.join(ROOT, "Data", "*.csv"))):
            name = os.path.basename(p)
            try:
                import pandas as _pd
                # 🔴 2026-11-03 踩坑：FRED 落盘用的是 **`observation_date`** ✗
                #    而原来写死 `usecols=["date"]` ✗ ⇒ 读 FRED 文件**抛异常** ✗
                #    ⇒ 记成 `"?"` ⇒ 被 `unchanged` 排除 ✗
                #    ⇒ 误判「`fetch_fred` 静默成功、无文件更新」✗（实际抓成功了 ✗）
                #    ⇒ 依次尝试 `date` / `observation_date` ✓
                last = None
                # 🔴 2026-11-10：补 `snapshot_date` / `as_of` ✗ ——
                #    `positions.csv` 的日期列**不叫 `date`** ✗ ⇒ 两个快照都记 `"?"` ✗
                #    ⇒ 明明写入了（`已写入 accounts 60 行 / positions 180 行`）✗
                #    却判「没有任何文件更新」✗（15:41 回执实测）
                for col in ("date", "observation_date", "snapshot_date", "as_of"):
                    try:
                        d = _pd.read_csv(p, usecols=[col], parse_dates=[col])
                        last = d[col].max()
                        break
                    except Exception:       # noqa: BLE001
                        continue
                # 🔴 再加**行数** ✓ —— 追加式文件（positions/accounts）日期列
                #    可能读不出，但行数一定变 ⇒ 用它兜底 ✓
                try:
                    rows = sum(1 for _ in open(p, encoding="utf-8",
                                               errors="replace")) - 1
                except OSError:
                    rows = -1
                _d = (str(last.date())
                      if last is not None and _pd.notna(last) else "?")
                snap[name] = "%s|%d" % (_d, rows)
            except Exception:               # noqa: BLE001
                snap[name] = "?"
        return snap

    # 🔴 2026-11-10：新增 `env` 参数 ✓ —— 有些脚本靠**环境变量**切模式 ✗
    #    实测 `sync_positions.py` 默认 `FG_SYNC_MODE=static`（公司电脑模式 ✗）
    #    ⇒ 完全不调富途 API ⇒ 持仓永远停在旧快照 ✗
    #    ⇒ 必须能传 `env=FG_SYNC_MODE=live` 才能真同步 ✓
    raw_env = str(params.get("env") or "").strip()
    extra_env = {}
    for kv in raw_env.split(","):
        if "=" in kv:
            _k, _v = kv.split("=", 1)
            if _k.strip():
                extra_env[_k.strip()] = _v.strip()
    run_env = dict(os.environ)
    run_env.update(extra_env)

    before = _snap()
    t0 = time.time()
    cmd = [sys.executable, os.path.join(ROOT, "scripts", script)] + extra
    try:
        r = _run(cmd, limit, env=run_env)
        rc, so, se = r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        rc, so, se = 124, "", "超过 %d 秒被强杀" % limit
    secs = time.time() - t0
    after = _snap()

    # ② 哪些文件的日期变了 ✓ / 没变 ✗
    changed, unchanged = {}, {}
    for name, av in after.items():
        bv = before.get(name)
        if bv != av:
            changed[name] = {"before": bv, "after": av}
        elif av != "?":
            unchanged[name] = av

    # 🔴 2026-11-05：**回报代理环境变量** ✓
    #    为什么必须回报 ✗：
    #      `install_daily_plist` 只**拷贝 plist 文件** ✗ **不重启进程** ✗
    #      而任务队列是**常驻进程**（`state = running` ✗）
    #      ⇒ **新补的代理不会生效** ✗ 直到重启 ✗
    #      ⇒ 所以「重跑 fetch_*」之前**必须先确认这里有没有代理** ✗
    env_proxy = {k: (os.environ.get(k) or "")
                 for k in ("FG_LLM_PROXY", "HTTP_PROXY", "HTTPS_PROXY",
                           "http_proxy", "https_proxy", "NO_PROXY")}

    return {"ok": rc == 0, "script": script, "args": extra, "rc": rc,
            "seconds": round(secs, 1),
            # 🔴 2026-11-10：把本次**额外注入的环境变量**回显 ✓
            #    否则「static 模式不调 API」这种坑看不出来 ✗
            "env_extra": extra_env,
            "env_proxy": env_proxy,
            "has_proxy": bool(env_proxy.get("FG_LLM_PROXY")
                              or env_proxy.get("HTTPS_PROXY")
                              or env_proxy.get("https_proxy")),
            "changed": changed, "unchanged": unchanged,
            "verdict": ("rc=%d 但**没有任何文件更新** ✗ ⇒ 「静默成功」✗"
                        % rc if rc == 0 and not changed
                        else "rc=%d，更新了 %d 个文件"
                             % (rc, len(changed))),
            "stdout": so[-6000:], "stderr": se[-2000:]}


def _act_clean_sync_partial(params):
    """删掉**指定包**的残留分片（`~/.openclaw/tmp/fg-sync-in/<pkg>_*.md`）✓。

    动机（MT-87，2026-10-28）：Windows 侧弃用的包永远收不齐 ✗ ⇒ bypass 每次同步
    都报「分片不齐，请补发」✗。只删 `pkg` 前缀的分片 ✓，不碰 `.done` / 其它包 ✗。
    """
    from fg_system.dashboard import sync_health
    pkg = str(params.get("pkg") or "")
    # 🔴 只允许 [A-Za-z0-9_] —— 挡住 `..`、`/`、`*` 这类会越出目录的写法 ✗
    if not pkg or any(not (c.isalnum() or c == "_") for c in pkg):
        return {"ok": False, "reason": "pkg 名非法（只允许 [A-Za-z0-9_]）：%r" % pkg}
    removed = []
    for p in sorted(glob.glob(os.path.join(sync_health.SHARD_IN, pkg + "_*.md"))):
        try:
            os.remove(p)
        except OSError as exc:
            return {"ok": False, "removed": removed,
                    "reason": "删 %s 失败：%s" % (os.path.basename(p), exc)}
        removed.append(os.path.basename(p))
    return {"ok": True, "removed": removed, "count": len(removed)}


def _act_fetch_prices(params):
    """**补抓行情**（`fetch.update_prices()`）✓（2026-11-03 数据断流修复）。

    【背景】
      每日链里**有**这一步（`python -c "fetch.update_prices()"` ✗）
      但 `prices.csv` 停在 2026-10-12 ✗ 断 22 天 ✗
      ⇒ 说明这一步**每天失败** ✗ 而日志被后面成功的步骤淹没了 ✗

    【做什么】
      ① 跑 `fetch.update_prices()` ✓ 抓完整 traceback ✓
      ② 跑完读 `prices.csv` 的**最新日期** ✓ 看有没有真更新 ✓
      ③ 同时补 `update_indices()`（VIX/VIX3M 也停了 22 天 ✗）

    参数：`indices`（默认 1，顺带抓 VIX ✓）
    """
    import pandas as _pd

    code = ("from fg_system.data import fetch;"
            "print('prices:', fetch.update_prices())")
    if str(params.get("indices") or "1").lower() in ("1", "true", "yes"):
        code += ";print('indices:', fetch.update_indices())"

    try:
        r = _run([sys.executable, "-c", code], 1800)
        so, se, rc = r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        so, se, rc = "", "超过 1800 秒", -1

    # 抓完看结果 ✓ —— 「跑成功」不等于「数据变了」✗
    after = {}
    for name in ("prices.csv", "vix.csv", "vix3m.csv"):
        p = os.path.join(ROOT, "Data", "raw", name)
        try:
            d = _pd.read_csv(p, usecols=["date"], parse_dates=["date"])
            after[name] = {"rows": int(len(d)),
                           "last": str(d["date"].max().date())}
        except Exception as e:              # noqa: BLE001
            after[name] = {"error": str(e)[:80]}

    return {"ok": rc == 0, "rc": rc,
            "stdout": so[-2500:], "stderr": se[-2000:],
            "after": after,
            "note": "⚠️ rc=0 但 `after` 里日期没变 ⇒ 抓取「成功但无新数据」✗"}


def _act_fetch_indices(params):
    """补抓 VIX / VIX3M（`fetch.update_indices()`）✓。

    2026-10-31：每日链每天跑这一步，但它**失败就整步抛错** ✗ ——
    `factor_diag` 只能看到结果，没法触发重抓 ✗
    ⇒ 加这个动作，用于「发现缺失 → 立刻补 → 再复核」的闭环 ✓。
    """
    code = ("from fg_system.data import fetch;"
            "print(fetch.update_indices())")
    try:
        r = _run([sys.executable, "-c", code], 600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 600 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1200:],
            "stderr": (r.stderr or "")[-800:]}


def _act_fetch_fred(params):
    """抓 FRED 系列 ✓（默认补 **DGS10** —— 它至今从未落盘 ✗）。

    2026-10-30：每日链跑 `fetch_fred --series DFF,DGS10,T10Y2Y`，
    但 `Data/raw/fred_DGS10.csv` **不存在** ✗；因为 `fed` 因子用的是 DFF，
    缺失一直无人发现 ✗。C2（ERP 估值锚）依赖它 ⇒ 需要先补齐 ✓。
    """
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "fetch_fred.py")]
    ser = str(params.get("series") or "DGS10").strip()
    if ser:
        cmd += ["--series", ser]
    if str(params.get("debug") or "") in ("1", "true", "yes"):
        cmd.append("--debug")
    try:
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1500:], "stderr": (r.stderr or "")[-600:]}


def _act_fetch_pe_ratio(params):
    """抓 S&P500 PE 月度历史 ✓ —— C2「ERP 估值锚」的数据源（`Data/raw/sp500_pe.csv`）。

    2026-10-30：FRED 没有 PE 系列 ✗，仓库也没有任何 PE 历史 ✗
    ⇒ 先解决数据源，再谈 C2 因子 ✓。
    """
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "fetch_pe_ratio.py")]
    if str(params.get("dry_run") or "") in ("1", "true", "yes"):
        cmd.append("--dry-run")
    # 2026-10-30：默认抓 PE + CAPE 两条 ✓（CAPE 作对照，判断「当期 PE 是否被
    # 一次性高盈利压低」✗）；可用 `series=pe|cape` 只抓一条 ✓
    ser = str(params.get("series") or "").strip()
    if ser in ("pe", "cape", "both"):
        cmd += ["--series", ser]
    try:
        r = _run(cmd, 180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 180 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1500:], "stderr": (r.stderr or "")[-600:]}


def _act_fetch_shoutu_history(params):
    """抓守猪待兔**服务端历史** ✓ —— 写 `Data/raw/shoutu_history.csv`。

    动机（2026-10-30）：建仓计划回测第一次跑空 ✗ —— 因为它读的是
    `shoutu_fng.csv`（**本地 06:30 采样**，只有近期几十天 ✗）。
    服务端历史（`stock_emotion/history`）才是权威日值 ✓，
    2024-04 起、每只 ~600 天 ✓（AXTX/CRCG 服务端没有 ⇒ 返回空表，不报错 ✓）。
    """
    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "fetch_shoutu_history.py")]
    syms = str(params.get("symbols") or "").strip()
    if syms:
        cmd += ["--symbols", syms]
    if str(params.get("debug") or "") in ("1", "true", "yes"):
        cmd.append("--debug")
    ids = str(params.get("ids") or "").strip()
    if ids:
        cmd += ["--ids", ids]
    if str(params.get("click_tab") or "") in ("1", "true", "yes"):
        cmd.append("--click-tab")
    if str(params.get("capture_all") or "") in ("1", "true", "yes"):
        cmd.append("--capture-all")
    try:
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-2000:], "stderr": (r.stderr or "")[-500:]}


def _act_inspect_csv(params):
    """**查任意 CSV 的尾部行 / 指定 symbol** ✓（2026-11-06）。

    🔴 为什么要查 ✗：
       `pipeline.run` 在 Mac 上失败 ✗ 报：
         `DataQualityError: SOXL 2026-11-05: SOXL 收益 -38.70% 与
          3×SOXX 收益 -70.97% 偏离 174.21pp`
       ⇒ **`SOXX` 一天跌 71%** ✗ 不可能 ✗ ⇒ 数据脏了 ✗
       而 **Windows 的 `prices.csv` 只到 10-12** ✗ 看不到 11-05 ✗
       ⇒ 必须从 **Mac** 取 ✓

    参数：`path`（默认 `Data/raw/prices.csv` ✗）、`symbol`（逗号分隔 ✗）、
          `n`（尾部行数 ✗ 默认 5 ✓）
    """
    import pandas as _pd
    # 🔴 2026-11-19 安全评审第三处：**原来完全没有白名单** ✗
    #    原写法：`if not os.path.isabs(path): path = join(ROOT, path)` ✗
    #    ⇒ ① 绝对路径直接放行（`/etc/passwd`、`~/.ssh/id_rsa` 都能读）✗
    #      ② 相对路径的 `..` 也不校验（`Data/raw/../../.env`）✗
    #    ⇒ 改用 `_safe_rel`：拒绝绝对路径 + 拒绝 `..` + 限定 `_READ_ALLOW` ✓
    _raw = str(params.get("path") or "Data/raw/prices.csv")
    # 🔴 2026-11-19：`os.path.isabs("/etc/passwd")` 在 Windows 上是 **False** ✗
    #    ⇒ 补一条「以分隔符开头」的判断，两个平台语义一致 ✓
    if os.path.isabs(_raw) or _raw.startswith(("/", "\\")):
        return {"ok": False, "error": "不接受绝对路径：%s ✗" % _raw}
    try:
        path = _safe_rel(_raw, _READ_ALLOW)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    n = int(params.get("n") or 5)
    syms = [x.strip().upper() for x in
            str(params.get("symbol") or "").split(",") if x.strip()]

    if not os.path.exists(path):
        return {"ok": False, "error": "文件不存在：%s ✗" % path}
    out = {"path": os.path.relpath(path, ROOT),
           "size_kb": round(os.path.getsize(path) / 1024.0, 1)}
    try:
        d = _pd.read_csv(path)
    except Exception as exc:                # noqa: BLE001
        return {"ok": False, "error": "%s: %s"
                % (type(exc).__name__, str(exc)[:200])}
    out["rows"] = int(len(d))
    out["columns"] = list(d.columns)

    if "symbol" in d.columns and syms:
        out["symbols"] = {}
        for s in syms:
            g = d[d["symbol"].astype(str).str.upper() == s]
            if not len(g):
                out["symbols"][s] = "**不存在** ✗"
                continue
            g = g.sort_values("date").tail(n)
            cols = [c for c in ("date", "close", "open", "high", "low")
                    if c in g.columns]
            out["symbols"][s] = g[cols].to_dict(orient="records")
            # 顺带算最近几天的**日收益** ✓（看跳变 ✗）
            if "close" in g.columns and len(g) > 1:
                r = g["close"].pct_change().dropna()
                out["symbols"][s + "_ret"] = [round(float(x), 4)
                                              for x in r.tail(n - 1)]
    elif "date" in d.columns:
        out["tail"] = d.sort_values("date").tail(n).to_dict(orient="records")
    else:
        out["tail"] = d.tail(n).to_dict(orient="records")
    out["ok"] = True
    return out


ACTIONS = {
    "fetch_prices": _act_fetch_prices,
    "fetch_indices": _act_fetch_indices,
    "fetch_fred": _act_fetch_fred,
    "fetch_pe_ratio": _act_fetch_pe_ratio,
    "fetch_shoutu_history": _act_fetch_shoutu_history,
    "update_crypto": _act_update_crypto,
    "audit_data": _act_audit_data,
    "inspect_csv": _act_inspect_csv,
    "prune_dead_data": _act_prune_dead_data,
    "run_fetch_step": _act_run_fetch_step,
    "clean_sync_partial": _act_clean_sync_partial,
}
