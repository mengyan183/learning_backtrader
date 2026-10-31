# -*- coding: utf-8 -*-
"""Mac 侧任务队列执行器：读 `docs/task-queue/*.json` → 跑白名单 action → 写 result → 提交。

【为什么要有它 —— 2026-10-28 用户拍板】
看板上「清理堆积 / 同步运行副本」这类**一次性任务**不该各占一个按钮 ✗ ——
每下发一次任务就新增一个按钮，页面必然失控 ✗，而且点完没有执行历史 ✗。
⇒ 改成「任务下发」：

    Windows  写 docs/task-queue/<id>.json（status=pending）→ 飞书分片
    Mac      本脚本扫到 pending → 执行白名单 action → 写 <id>.result.json
             → git add/commit/push（docs/ 在白名单内 ✓）
    Windows  git fetch → 看板读 result 显示任务历史 ✓

🔴 白名单是 **action 名**，不是命令字符串 ✗ —— 后者等于把 RCE 开在飞书群里
   （MT-49 那类洞：任何能给飞书发消息的人都能在 Mac 上执行任意命令）。
   新增动作必须改本文件的 ACTIONS 并过 code review ✓。

用法（Mac）：
    .venv/bin/python scripts/run_task_queue.py            # 跑一次（launchd 每 10s 调）
    .venv/bin/python scripts/run_task_queue.py --no-commit  # 只执行不提交（调试）
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "docs", "task-queue")

#: launchd 定时器（本脚本每 10s 被调一次）—— 看板可一键安装 ✓
LABEL = "com.xingguo.fg-task-queue"
PLIST_SRC = os.path.join(ROOT, "scripts", LABEL + ".plist")
PLIST_DST = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                         LABEL + ".plist")


def agent_status():
    """定时器是否已安装 / 已加载（看板据此决定要不要显示安装按钮）。"""
    installed = os.path.isfile(PLIST_DST)
    loaded = False
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True,
                           text=True, timeout=15)
        loaded = LABEL in (r.stdout or "")
    except (subprocess.SubprocessError, OSError):
        pass
    return {"installed": installed, "loaded": loaded, "label": LABEL}


def install_agent():
    """把 plist 装进 `~/Library/LaunchAgents` 并 bootstrap（幂等，重复点会先 bootout）。

    🔴 为什么可以在页面上做：看板服务本身就跑在 Mac 本地、以用户身份运行 ✓，
    有写 `~/Library/LaunchAgents` 和执行 `launchctl` 的权限 ✓。
    安全边界：源是仓库里的固定 plist、目标是固定的 LaunchAgents 路径、无用户输入 ✓。
    """
    if sys.platform != "darwin":
        return {"ok": False, "reason": "只有 macOS 支持 launchd（当前 %s）" % sys.platform}
    if not os.path.isfile(PLIST_SRC):
        return {"ok": False, "reason": "仓库里没有 plist：%s" % PLIST_SRC}
    try:
        os.makedirs(os.path.dirname(PLIST_DST), exist_ok=True)
        shutil.copy2(PLIST_SRC, PLIST_DST)
    except OSError as exc:
        return {"ok": False, "reason": "拷贝 plist 失败：%s" % exc}

    dom = "gui/%d" % os.getuid()
    try:
        # 先卸再装（幂等）：未加载时 bootout 会报错，忽略即可 ✓
        subprocess.run(["launchctl", "bootout", dom + "/" + LABEL],
                       capture_output=True, timeout=30)
        r = subprocess.run(["launchctl", "bootstrap", dom, PLIST_DST],
                           capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "launchctl 执行失败：%s" % exc}
    st = agent_status()
    out = {"ok": bool(st["loaded"]) or r.returncode == 0,
           "stdout": (r.stdout or "")[-300:], "stderr": (r.stderr or "")[-300:]}
    out.update(st)
    return out

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _act_cleanup_backlog(params):
    """把插件层 30 分钟前的历史文件挪进 archive（见 sync_health.archive_backlog）。"""
    from fg_system.dashboard import sync_health
    r = sync_health.archive_backlog()
    # 「没有够老的文件」= **成功**（无事可做）✓；「目录不存在」才是失败 ✗
    ok = bool(r.get("moved")) or "没有超过" in str(r.get("reason") or "")
    return dict(r, ok=ok)


def _act_sync_runtime(params):
    """把仓库版 bypass 覆盖到运行时副本（见 sync_health.sync_runtime_copy）。"""
    from fg_system.dashboard import sync_health
    return sync_health.sync_runtime_copy()


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


def _act_install_evolve_tasks(params):
    """重新注册 evolve 定时器（跑仓库里的 `install_evolve_tasks.sh`）✓。

    动机（2026-10-29）：plist 只改仓库副本**不生效** ✗ —— 真身是
    `~/Library/LaunchAgents/*.plist`，必须重跑安装脚本才会重新 bootstrap ✓。
    固定脚本、固定路径，不接受任何参数 ✓（与白名单同一原则 ✗）。
    """
    script = os.path.join(ROOT, "scripts", "install_evolve_tasks.sh")
    if not os.path.exists(script):
        return {"ok": False, "reason": "找不到 %s" % script}
    try:
        r = subprocess.run(["bash", script], cwd=ROOT, capture_output=True,
                           text=True, timeout=180)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-900:], "stderr": (r.stderr or "")[-400:]}


def _act_futu_preflight(params):
    """探一次富途 OpenD 端口 ✓ —— 只读、2 秒超时、零副作用 ✓。

    动机（2026-10-29）：新加的「预检 + 硬超时」要等到明天 05:30 才被跑到 ✗，
    这里让 Mac **立刻验一次** ✓，顺带把状态落盘（简报里就能看到）✓。
    """
    if os.path.join(ROOT, "scripts") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import futu_health
    ok, why = futu_health.preflight()
    futu_health.write_status(ok, why, "queue:futu_preflight")
    return {"ok": bool(ok), "reason": why}


#: 需要「从仓库副本装到 LaunchAgents」的 plist ✓
PLISTS = ["com.xingguo.fg-daily.plist", "com.xingguo.fg-task-queue.plist"]


def _act_install_daily_plist(params):
    """把仓库里的 plist 装到 `~/Library/LaunchAgents` 并重新 bootstrap ✓。

    动机（2026-10-29）：plist 只改仓库副本**不生效** ✗ —— 真身是
    `~/Library/LaunchAgents/*.plist`，launchd 读的是那份 ✗。
    （每日链套 `run_guarded`、队列加 PATH 都靠这一步落地 ✓。）

    🔴 `com.xingguo.fg-task-queue` **不能当场 bootout** ✗ —— 执行本任务的进程
    正是它启动的 ✗，当场 bootout 会把自己杀掉、结果永远写不出来 ✗
    ⇒ 用**延迟 8 秒的游离 shell** 去重装 ✓。
    """
    agent = os.path.expanduser("~/Library/LaunchAgents")
    domain = "gui/%d" % os.getuid()
    out = {}
    for name in PLISTS:
        src = os.path.join(ROOT, "scripts", name)
        if not os.path.exists(src):
            out[name] = "缺文件 %s" % src
            continue
        dst = os.path.join(agent, name)
        label = name[:-len(".plist")]
        try:
            os.makedirs(agent, exist_ok=True)
            shutil.copy2(src, dst)
        except OSError as exc:
            out[name] = "拷贝失败：%s" % exc
            continue
        if label.endswith("fg-task-queue"):
            # 延迟重装：先让本任务把结果写完 ✓
            # 🔴 2026-10-29：重装结果**必须落盘** ✗ —— 原来起个游离 shell 就返回，
            # `ok:true` 只代表「拷贝成功」，8 秒后成没成无人回收 ✗
            # ⇒ 那个 shell 把结果写进 `<tid>.reinstall.json` ✓，下一轮 `_collect_reinstall`
            #   读回来并回写进任务结果 ✓（看板可见 ✓）。
            tid = str(params.get("_tid") or ("plist-" + time.strftime("%H%M%S")))
            marker = os.path.join(QUEUE, tid + ".reinstall.json")
            script = (
                "sleep 8; "
                "launchctl bootout {dom}/{lab} 2>/dev/null; "
                "launchctl bootstrap {dom} {dst}; RC=$?; "
                "launchctl enable {dom}/{lab} 2>/dev/null; "
                "printf '{{\"ok\": %s, \"rc\": %s, \"at\": \"%s\","
                " \"label\": \"{lab}\"}}' "
                "\"$([ $RC -eq 0 ] && echo true || echo false)\" \"$RC\" "
                "\"$(date +%Y-%m-%dT%H:%M:%S)\" > {marker}"
            ).format(dom=domain, lab=label, dst=dst, marker=marker)
            subprocess.Popen(["/bin/sh", "-c", script],
                             start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out[name] = "已拷贝（8 秒后重装，结果下轮回写）"
            continue
        try:
            subprocess.run(["launchctl", "bootout", "%s/%s" % (domain, label)],
                           capture_output=True, timeout=30)
            r = subprocess.run(["launchctl", "bootstrap", domain, dst],
                               capture_output=True, text=True, timeout=60)
            subprocess.run(["launchctl", "enable", "%s/%s" % (domain, label)],
                           capture_output=True, timeout=30)
            out[name] = "ok" if r.returncode == 0 else (r.stderr or "")[-200:]
        except (subprocess.SubprocessError, OSError) as exc:
            out[name] = "launchctl 失败：%s" % exc
    return {"ok": all(v.startswith("ok") or v.startswith("已拷贝")
                      for v in out.values()), "result": out}


def _act_fetch_indices(params):
    """补抓 VIX / VIX3M（`fetch.update_indices()`）✓。

    2026-10-31：每日链每天跑这一步，但它**失败就整步抛错** ✗ ——
    `factor_diag` 只能看到结果，没法触发重抓 ✗
    ⇒ 加这个动作，用于「发现缺失 → 立刻补 → 再复核」的闭环 ✓。
    """
    code = ("from fg_system.data import fetch;"
            "print(fetch.update_indices())")
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                           capture_output=True, text=True, timeout=600)
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
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
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
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 180 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1500:], "stderr": (r.stderr or "")[-600:]}


def _act_c1_backtest(params):
    """C1 回测裁判（M2.2）✓ —— 两步：把 `baa10y_z` 并入研究 features → 跑 probe。

    2026-10-30：相关性复核**通过**（无 `|ρ|>0.5 且 n≥250` 的列 ⇒ 跳过正交化）✓
    ⇒ 直接进回测裁判 ✓。
    `factor_backtest_probe.py` 只认 features 里的**列** ✗，而 baa10y 在
    `Data/raw/fred_baa10y_avail.csv` ⇒ 先 dump 一份研究专用 features ✓。
    """
    feat = str(params.get("features")
               or "evolution/experiments/factor-adoption/features_c1.csv")
    # 2026-10-30：支持**多组合扫描** ✓（`symbols`/`directions` 逗号分隔）——
    # ⚠️ 这是**多重检验** ✗：同一份数据反复试直到通过 = 过拟合 ✓
    # ⇒ 结果只作**探索性分析**，**不作为采纳依据** ✗（提案里必须写明）
    syms = [x.strip() for x in str(params.get("symbols")
                                   or params.get("symbol") or "TQQQ").split(",")
            if x.strip()]
    dirs = [x.strip() for x in str(params.get("directions")
                                   or params.get("direction") or "positive").split(",")
            if x.strip()]
    sym = syms[0]
    # C1 是**逆向**因子：信用利差高（z 高）= 恐慌 = 看多 ⇒ direction=positive ✓
    direc = dirs[0]
    steps = [[sys.executable, os.path.join(ROOT, "scripts", "eval_baa10y.py"),
              "--dump-features", feat]]
    for s in syms:
        for d in dirs:
            steps.append(
                [sys.executable,
                 os.path.join(ROOT, "scripts", "factor_backtest_probe.py"),
                 "--factor", "baa10y_z", "--symbol", s,
                 "--direction", d, "--features", feat])
    out = []
    for cmd in steps:
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                               timeout=1800)
        except subprocess.TimeoutExpired:
            out.append({"cmd": " ".join(cmd[1:]), "rc": -1,
                        "stdout": "", "stderr": "超过 1800 秒"})
            continue
        # 🔴 probe 判 FAIL 时 **exit 1** ✗ —— 那是**结论**不是崩溃 ✓
        # ⇒ 不能因为 rc!=0 就 break，否则后面的组合全被跳过 ✗
        out.append({"cmd": " ".join(cmd[1:]), "rc": r.returncode,
                    "stdout": (r.stdout or "")[-1800:],
                    "stderr": (r.stderr or "")[-400:]})
    return {"ok": all(x["rc"] == 0 for x in out),
            "combos": len(syms) * len(dirs),
            "warning": "⚠️ 多组合扫描 = 多重检验 ⇒ 仅作探索，不作为采纳依据 ✗",
            "steps": out}


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
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-2000:], "stderr": (r.stderr or "")[-500:]}


def _act_backtest_plan(params):
    """在 Mac 上跑**建仓/加仓计划回测** ✓（`shoutu_fng.csv` 只在 Mac 本地 ✗）。

    `symbols` 非空 ⇒ 覆盖默认 6 个标的 ✓；`json` 非空 ⇒ 完整结果落盘 ✓。
    """
    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "backtest_position_plan.py")]
    syms = str(params.get("symbols") or "").strip()
    if syms:
        cmd += ["--symbols", syms]
    out = str(params.get("json") or "").strip()
    if out:
        cmd += ["--json", out if os.path.isabs(out) else os.path.join(ROOT, out)]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-3000:], "stderr": (r.stderr or "")[-500:]}


def _act_key_diag(params):
    """找本机 API key ✓ —— **只回前缀与长度，绝不回明文** ✗。

    动机（2026-10-29）：NIM 免费通道走不通（唯一可用模型卡死、其余 404），
    要切 DeepSeek 官方，但得先确认 key 在哪、是什么结构 ——
    `~/.dsh/.credentials.yaml` 里既有 `nvapi-`（NVIDIA）也可能有 `sk-`（DeepSeek）✗。
    """
    import re

    root = os.path.expanduser(str(params.get("dir") or "~/.dsh"))
    if not os.path.isdir(root):
        return {"ok": False, "reason": "目录不存在：%s" % root}
    pats = {"nvapi": re.compile(r"nvapi-[A-Za-z0-9_\-]{8,}"),
            "sk": re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
            "sk-or": re.compile(r"sk-or-[A-Za-z0-9_\-]{16,}")}
    files, hits, seen = [], [], set()
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for f in names:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            files.append("%s（%d B）" % (rel, sz))
            if sz > 512 * 1024:                 # 大文件（模型/日志）不扫 ✓
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read()
            except OSError:
                continue
            for kind, rx in pats.items():
                for m in rx.finditer(txt):
                    v = m.group(0)
                    sig = (rel, kind, v[:10], len(v))
                    if sig in seen:
                        continue
                    seen.add(sig)
                    hits.append({"file": rel, "kind": kind,
                                 "prefix": v[:10] + "…", "len": len(v)})
    return {"ok": True, "result": {"dir": root,
                                   "files": files[:40],
                                   "hits": hits[:40]}}


def _act_run_pipeline(params):
    """重算 `features.csv`（与每日链**同一条**调用序列 ✓）。

    动机（2026-10-29 实测）：`features.csv` 尾行的 `vix`/`term` 是空 ✗，
    而 `raw/vix.csv`、`raw/prices.csv` 都已到新日期 ✓ ⇒ 说明 pipeline 当时
    **在 vix 数据补齐之前**就跑了，尾行因子只能留空，之后没人重算 ✗。

    🔴 会**覆写** `features.csv` / `portfolio_features.csv` ✗ —— 所以只跑
    与每日链完全相同的三步（不多做、不少做），避免两条口径打架 ✓。
    """
    code = ("from fg_system import pipeline;"
            "pipeline.run(write=True);"
            "us=pipeline.run_equity_v2();"
            "cr=pipeline.run_crypto(write=True);"
            "pipeline.run_portfolio(us, cr, write=True)")
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 1800 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1200:],
            "stderr": (r.stderr or "")[-500:]}


def _act_factor_diag(params):
    """查六因子为什么缺 ✓ —— 只读，报各数据源的尾行日期与近 30 行非空数。

    动机（2026-10-29）：简报里 `VIX — 数据缺失` / `TERM — 数据缺失` ✗，
    但没人知道是 features 没算、还是原始 csv 没更新 ✗ ⇒ 只能上 Mac 查 ✓。
    """
    import pandas as pd

    data = os.path.join(ROOT, "Data")
    out = {}

    def _tail(path):
        try:
            d = pd.read_csv(path, parse_dates=["date"])
            if d.empty:
                return "空文件"
            return "%s（%d 行）" % (d["date"].iloc[-1].date(), len(d))
        except Exception as exc:                   # noqa: BLE001
            return "读不出：%s" % exc

    out["raw/vix.csv"] = _tail(os.path.join(data, "raw", "vix.csv"))
    out["raw/prices.csv"] = _tail(os.path.join(data, "raw", "prices.csv"))
    out["features.csv"] = _tail(os.path.join(data, "features.csv"))

    try:
        f = pd.read_csv(os.path.join(data, "features.csv"), parse_dates=["date"])
        last = f.iloc[-1]
        out["features 尾行"] = {
            c: (None if pd.isna(last.get(c)) else float(last[c]))
            for c in ("fg_index", "vix", "term") if c in f.columns}
        out["features 尾行"]["date"] = str(last["date"].date())
        # 从哪一天开始断的：倒着数连续为空的长度
        for c in ("vix", "term"):
            if c not in f.columns:
                continue
            s = f[c]
            n = 0
            for v in reversed(list(s)):
                if pd.isna(v):
                    n += 1
                else:
                    break
            out["%s 连续缺失" % c] = "%d 行" % n
        out["近30行非空"] = {c: int(f[c].tail(30).notna().sum())
                          for c in ("vix", "term") if c in f.columns}
    except Exception as exc:                       # noqa: BLE001
        out["features 尾行"] = "读不出：%s" % exc

    try:
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "check_freshness.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=180)
        out["check_freshness"] = {"rc": r.returncode,
                                  "out": (r.stdout or "")[-800:]}
    except (subprocess.SubprocessError, OSError) as exc:
        out["check_freshness"] = "执行失败：%s" % exc
    return {"ok": True, "result": out}


def _act_net_probe(params):
    """探「本地代理端口」+「经代理取一次」✓ —— 只读、秒级。

    动机（2026-10-29）：简报两个 LLM 阶段都 `timed out`（不是 connection refused ✗）
    ⇒ 怀疑本地代理（Clash 127.0.0.1:7890）能连上但上游卡住 ✗。
    队列跑在 launchd 里，环境与登录 shell 不同 ✗ ⇒ 只能在 Mac 本地实测 ✓。
    """
    import socket
    import urllib.error
    import urllib.parse
    import urllib.request

    proxy = str(params.get("proxy") or "http://127.0.0.1:7890")
    url = str(params.get("url") or "https://integrate.api.nvidia.com/v1/models")
    out = {"proxy": proxy, "url": url}

    # ① 代理端口能不能连（3 秒）
    u = urllib.parse.urlsplit(proxy)
    t0 = time.time()
    try:
        s = socket.create_connection((u.hostname, u.port or 80), timeout=3)
        s.close()
        out["proxy_port"] = {"ok": True,
                             "ms": int((time.time() - t0) * 1000)}
    except OSError as exc:
        out["proxy_port"] = {"ok": False, "reason": str(exc)}

    # ② 经代理真取一次 ✓
    # `method`/`body`/`auth`/`secs` 可调 —— 2026-10-29 实测 GET 521ms 通、
    # POST chat 60 秒无响应 ✗ ⇒ 必须能**分别**验 GET 与 POST ✗
    method = str(params.get("method") or "GET").upper()
    body = params.get("body")
    secs = int(params.get("secs") or 10)
    headers = {}
    if body is not None:
        body = str(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if str(params.get("auth") or "") in ("1", "true", "yes"):
        try:
            if os.path.join(ROOT, "scripts") not in sys.path:
                sys.path.insert(0, os.path.join(ROOT, "scripts"))
            import invest_research as ir
            headers["Authorization"] = "Bearer " + ir._read_nim_key()
        except Exception as exc:                   # noqa: BLE001
            out["auth"] = "读 key 失败：%s" % exc

    t0 = time.time()
    status = None
    try:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method=method)
        with op.open(req, timeout=secs) as r:
            status = r.status
            out["via_proxy"] = {"ok": True, "status": status, "method": method,
                                "ms": int((time.time() - t0) * 1000)}
            # `body_out=1` ⇒ 解析出**模型 id 列表** ✓（不回传原始正文 ✗）
            # 2026-10-29 踩坑：原始正文 3000 字，而 `_write_result` 只留尾部
            # `output[-2000:]` ✗ ⇒ 开头的 `deepseek-ai/*` 正好被截掉 ✗
            # ⇒ 只回「数量 + 按关键词筛过的 id」，几十个字就够 ✓
            if str(params.get("body_out") or "") in ("1", "true", "yes"):
                try:
                    import re
                    n = max(1000, min(int(params.get("body_len") or 20000), 60000))
                    txt = r.read(n).decode("utf-8", "replace")
                    ids = re.findall(r'"id"\s*:\s*"([^"]+)"', txt)
                    kw = str(params.get("models_like") or "deepseek,qwen,llama-3.3")
                    keys = [k.strip().lower() for k in kw.split(",") if k.strip()]
                    out["via_proxy"]["model_count"] = len(ids)
                    out["via_proxy"]["models"] = [
                        i for i in ids
                        if any(k in i.lower() for k in keys)][:40]
                except Exception as exc:           # noqa: BLE001
                    out["via_proxy"]["models"] = "解析失败：%s" % exc
    except urllib.error.HTTPError as exc:
        # 401/404 这类**也是有效情报** ✓ —— 说明链路通、只是鉴权/路径不对 ✓
        out["via_proxy"] = {"ok": False, "status": exc.code, "method": method,
                            "ms": int((time.time() - t0) * 1000),
                            "reason": "HTTP %s" % exc.code}
    except Exception as exc:                       # noqa: BLE001
        out["via_proxy"] = {"ok": False, "status": status, "method": method,
                            "ms": int((time.time() - t0) * 1000),
                            "reason": "%s: %s" % (type(exc).__name__, exc)}

    # ③ `chat=1` ⇒ 真打一次 chat/completions（max_tokens=8）✓
    # 2026-10-29 实测：GET 模型列表 641ms 通，但简报的归因阶段仍 240s 超时 ✗
    # ⇒ 必须区分「网络不通」和「**生成太慢**」✗，只有真打一次才知道 ✓
    if str(params.get("chat") or "") in ("1", "true", "yes"):
        t0 = time.time()
        try:
            if os.path.join(ROOT, "scripts") not in sys.path:
                sys.path.insert(0, os.path.join(ROOT, "scripts"))
            import invest_research as ir
            # `model` 可覆盖 ⇒ 换模型前先单测候选 ✓（2026-10-29）
            reply = ir._chat(ir.NIM_URL, ir._read_nim_key(),
                             str(params.get("model") or ir.NIM_MODEL),
                             "你是连通性探针。", "只回复 OK", max_tokens=8,
                             proxy=ir.PROXY, timeout=60, retries=1)
            out["chat"] = {"ok": True, "ms": int((time.time() - t0) * 1000),
                           "reply": str(reply)[:40]}
        except Exception as exc:                   # noqa: BLE001
            out["chat"] = {"ok": False,
                           "ms": int((time.time() - t0) * 1000),
                           "reason": "%s: %s" % (type(exc).__name__, exc)}

    ok = out["proxy_port"].get("ok") and out["via_proxy"].get("ok")
    if "chat" in out:
        ok = ok and out["chat"].get("ok")
    return {"ok": ok, "result": out}


def _act_eval_baa10y(params):
    """在 Mac 上跑 **C1 信用利差评测** ✓（`fred_baa10y_avail.csv` 只在 Mac 本地 ✗）。

    `orth` 非空 ⇒ 先剔除该列（如 `fed`）再评测 ✓（用户裁定：先正交化再进裁判 ✓）；
    `json` 非空 ⇒ 把完整报告写到该路径（相对路径按仓库根解析 ✓）。
    """
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "eval_baa10y.py")]
    orth = str(params.get("orth") or "").strip()
    if orth:
        cmd += ["--orthogonalize", orth]
    out = str(params.get("json") or "").strip()
    if out:
        cmd += ["--json", out if os.path.isabs(out) else os.path.join(ROOT, out)]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "orth": orth or None,
            "stdout": (r.stdout or "")[-2500:], "stderr": (r.stderr or "")[-500:]}


def _act_run_invest_research(params):
    """跑一次投研简报 ✓ —— 默认 `--dry-run`（不推飞书）✓。

    动机（2026-10-29）：简报连停两天，改完需要**今天就能验证** ✗，
    而不是干等明天 05:30 ✗。`--dry-run` 只写文件 + 打印开头 ⇒ 从结果里
    就能确认「🔌 数据源健康」这节在不在 ✓。要真发：`--param push=1` ✓。
    """
    push = str(params.get("push") or "") in ("1", "true", "yes")
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "invest_research.py")]
    if not push:
        cmd.append("--dry-run")
    try:
        # 🔴 2026-10-29：600 → **900** 秒 ✗ —— 实测一次 dry-run 到 600 秒被杀，
        # 而串行版历史耗时 478 秒（并发版不该更慢）⇒ 说明阶段耗时波动很大 ✗。
        # 与每日链 `run_guarded` 给这步的 900 秒对齐 ✓。
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"
                "（阶段级进度见 daily_log_tail --which invest）"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode, "push": push,
            "stdout": (r.stdout or "")[-1500:], "stderr": (r.stderr or "")[-500:]}


#: 允许 tail 的日志 —— **固定白名单** ✓（不接受任意路径 ✗，否则等于远程读文件 ✗）
#: `evolve_verify` 是**仓库内** logs/ 下的日志（plist 的 StandardOutPath）✓ ——
#: 2026-10-29 加：验证 06:10 那次复检有没有真的带上 `--quiet` ✓
TAIL_LOGS = {
    "daily": "/tmp/fg_daily.log",
    "task_queue": "/tmp/fg_task_queue.log",
    "evolve_verify": os.path.join(ROOT, "logs", "evolve_verify.log"),
    # 2026-10-29：简报阶段级日志 ✓ —— 队列超时杀进程时 stdout 全丢 ✗，
    # 只有这个文件能看出卡在新闻还是某个 LLM 阶段 ✓
    "invest": os.path.join(ROOT, "Data", "health", "invest_stages.log"),
}


def _act_daily_log_tail(params):
    """回传某个运行日志的尾巴 ✓。

    动机（2026-10-29）：简报连续两天没发，只能靠 `/tmp/fg_daily.log` 定位 ✗ ——
    而「让用户去 Mac 上敲命令」违反「Mac 侧操作一律走队列」✗。
    `which` 走白名单，`lines` 上限 200 ✓。
    """
    which = str(params.get("which") or "daily")
    path = TAIL_LOGS.get(which)
    if not path:
        return {"ok": False,
                "reason": "未知日志 %r（可选：%s）" % (which, ", ".join(sorted(TAIL_LOGS)))}
    try:
        n = max(1, min(int(params.get("lines") or 60), 200))
    except (TypeError, ValueError):
        n = 60
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tail = fh.readlines()[-n:]
    except OSError as exc:
        return {"ok": False, "reason": "读不到 %s：%s" % (path, exc)}
    return {"ok": True, "which": which, "path": path,
            "lines": len(tail), "tail": "".join(tail)}


#: 需要 `_tid` 的动作 ✓ —— 只有「结果要延迟回写」的才需要知道自己是哪个任务
#: （`install_daily_plist` 的游离 shell 要把结果写成 `<tid>.reinstall.json` ✓）
NEEDS_TID = {"install_daily_plist"}


#: 🔴 唯一可执行清单。键是**任务名**，值是固定函数 —— 不接受任何命令字符串 ✓
ACTIONS = {
    "cleanup_backlog": _act_cleanup_backlog,
    "sync_runtime": _act_sync_runtime,
    "clean_sync_partial": _act_clean_sync_partial,
    "daily_log_tail": _act_daily_log_tail,
    "install_evolve_tasks": _act_install_evolve_tasks,
    "futu_preflight": _act_futu_preflight,
    "run_invest_research": _act_run_invest_research,
    "install_daily_plist": _act_install_daily_plist,
    "eval_baa10y": _act_eval_baa10y,
    "net_probe": _act_net_probe,
    "factor_diag": _act_factor_diag,
    "run_pipeline": _act_run_pipeline,
    "c1_backtest": _act_c1_backtest,
    "fetch_pe_ratio": _act_fetch_pe_ratio,
    "fetch_fred": _act_fetch_fred,
    "fetch_indices": _act_fetch_indices,
    "key_diag": _act_key_diag,
    "backtest_plan": _act_backtest_plan,
    "fetch_shoutu_history": _act_fetch_shoutu_history,
}


def _load_pending():
    """列出待执行任务（status=pending），按 created_at 升序（先来先做）。"""
    out = []
    if not os.path.isdir(QUEUE):
        return out
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".json") or name.endswith(".result.json"):
            continue
        p = os.path.join(QUEUE, name)
        try:
            with open(p, encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError) as exc:
            # 🔴 2026-10-29 实测：一个被写坏的 json（文件末尾粘了 patch 头 ✗）
            # 会被**每轮静默跳过** ✗ ⇒ 任务永久饿死、且没人知道 ✗
            # ⇒ 打一行警告并改名成 `.broken`（不再匹配 *.json，不再空转）✓
            print("[warn] 任务文件读不出，已隔离为 .broken：%s（%s）"
                  % (name, exc))
            try:
                os.replace(p, p + ".broken")
            except OSError:
                pass
            continue
        if str(spec.get("status") or "pending") != "pending":
            continue
        spec["_path"] = p
        tid = str(spec.setdefault("id", name[:-5]))
        # 已有 result ⇒ 不再执行 ✓ —— 原任务文件里的 status 永远是 pending（我们不回写它），
        # launchd 每 10s 扫一次会**重复执行** ✗（2026-10-28 测试抓到的真 bug）
        if os.path.exists(os.path.join(QUEUE, tid + ".result.json")):
            continue
        out.append(spec)
    # 🔴 2026-10-29：按 **id** 排序（先进先出）✗ —— id 是
    # `t-YYYYmmdd-HHMMSS-<action>`，字典序**恒等于**时间序 ✓；
    # 而 `created_at` 可能缺失/手写错误（缺失会排最前，抢跑 ✗）。
    out.sort(key=lambda s: str(s.get("id") or ""))
    return out


def _write_result(spec, status, rc, output, started, finished):
    rec = {
        "id": spec["id"],
        "action": spec.get("action"),
        "params": spec.get("params") or {},
        "status": status,
        "rc": rc,
        "output": output[-2000:],       # 只留尾部，避免 result 文件膨胀
        "started_at": started,
        "finished_at": finished,
        "duration_s": round(time.time() - spec.get("_t0", time.time()), 2),
    }
    p = os.path.join(QUEUE, spec["id"] + ".result.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return p


def _auto_clean():
    """每轮顺手自愈：插件层堆积超阈值就归档（2026-10-28 A 方案）。

    为什么不做成「下发任务」：这是**周期性自愈**，不是一次性动作 ——
    每 10s 跑一次、超阈值才动，不需要人记得下发 ✓。
    为什么还要保留手动按钮：自愈是兜底，手动是「我现在就想清」。
    """
    try:
        from fg_system.dashboard import sync_health as sh
        if sh._bypass_stats(time.time())["count"] < sh.BACKLOG_WARN:
            return None
        return sh.archive_backlog()
    except Exception:
        return None            # 自愈失败绝不能影响正常任务 ✓


#: 队列里只留最近这么多个**已完成**任务 ✓（每个任务两个 json，不清理会无限涨 ✗）
KEEP_TASKS = 10


def _task_ids():
    """`{id: [文件路径…]}` —— 一个任务是 `<id>.json` + `<id>.result.json` 两个文件 ✓。"""
    out = {}
    for p in glob.glob(os.path.join(QUEUE, "*.json")):
        base = os.path.basename(p)
        tid = (base[:-len(".result.json")] if base.endswith(".result.json")
               else base[:-len(".json")])
        out.setdefault(tid, []).append(p)
    return out


#: 「正在执行」标记后缀 —— **旁路文件，不写回任务 json** ✗
#: 为什么不在 json 里写 status=running：进程若中途被杀，json 会永远停在 running ✗
#: ⇒ `_load_pending` 再也不认领它 ⇒ 任务永远不执行 ✗（比显示不准严重得多 ✗）。
#: 旁路标记最坏只是看板显示「执行中」到超时 ✓。
RUNNING_SUFFIX = ".running"
#: 标记超过这么久 ⇒ 视为**残留**（进程已死），看板不再显示执行中 ✓
RUNNING_STALE_SEC = 1200


def _running_path(tid):
    return os.path.join(QUEUE, tid + RUNNING_SUFFIX)


def _mark_running(tid):
    try:
        with open(_running_path(tid), "w", encoding="utf-8") as fh:
            json.dump({"started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, fh)
    except OSError:
        pass


def _clear_running(tid):
    try:
        os.remove(_running_path(tid))
    except OSError:
        pass


def _prune_queue(keep=KEEP_TASKS):
    """只留最近 `keep` 个**已完成**任务 ✓，返回被删文件名列表。

    🔴 未完成的任务（没有 `.result.json`）**一律不删** ✗ —— 删了就永远不会执行 ✗。
    id 形如 `t-YYYYmmdd-HHMM-<action>` ⇒ 字典序即时间序 ✓。
    """
    ids = _task_ids()
    pending = {t for t, ps in ids.items()
               if not any(p.endswith(".result.json") for p in ps)}
    done = sorted((t for t in ids if t not in pending), reverse=True)
    dropped = []
    for tid in done[max(0, keep - len(pending)):]:
        for p in ids[tid]:
            try:
                os.remove(p)
                dropped.append(os.path.basename(p))
            except OSError:
                pass
    return dropped


def _collect_reinstall():
    """把「延迟重装」的结果并回任务结果 ✓，返回被更新的任务 id 列表。

    2026-10-29：`install_daily_plist` 对队列作业只能**延迟 8 秒**重装（当场 bootout
    会把自己杀掉 ✗）⇒ 它返回的 `ok:true` 只代表**拷贝成功**，重装成没成无人回收 ✗。
    现在那个游离 shell 把结果写进 `<tid>.reinstall.json` ✓，这里下一轮读回来：
    ① 打印一行到 `/tmp/fg_task_queue.log`；② 回写进 `<tid>.result.json` 的
    `reinstall` 字段（看板可见 ✓）；③ 删掉标记 ✓。
    """
    changed = []
    if not os.path.isdir(QUEUE):
        return changed
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".reinstall.json"):
            continue
        tid = name[:-len(".reinstall.json")]
        mp = os.path.join(QUEUE, name)
        try:
            with open(mp, encoding="utf-8") as fh:
                mark = json.load(fh)
        except (OSError, ValueError):
            mark = {"ok": False, "reason": "标记文件读不出"}
        rp = os.path.join(QUEUE, tid + ".result.json")
        try:
            with open(rp, encoding="utf-8") as fh:
                res = json.load(fh)
            res["reinstall"] = mark
            with open(rp, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=2)
            changed.append(tid)
            print("[reinstall] %s %s（rc=%s）"
                  % (tid, "重装成功 ✓" if mark.get("ok") else "重装**失败** ✗",
                     mark.get("rc")))
        except (OSError, ValueError) as exc:
            print("[warn] 重装结果回写失败（%s）：%s" % (tid, exc))
        try:
            os.remove(mp)
        except OSError:
            pass
    return changed


#: 补推节流：launchd 每 10s 一轮，失败时别把日志刷爆 ✗
_PUSH_RETRY = {"ts": 0.0}


def _try_push_pending(interval=300):
    """有未推送提交就顺手补推一次 ✓ —— 上次推送失败后**自愈** ✓。

    动机（2026-10-29 实测 ✗）：launchd 的 PATH 里没有 `/opt/homebrew/bin` ✗
    ⇒ 凭据助手 `gh auth git-credential` 找不到 gh ✗ ⇒ `git push` rc=128 ✗
    ⇒ 任务结果提交了却推不上去，只能等别的进程捎带 ✗（结果总是「晚到」✗）。
    """
    now = time.time()
    if now - _PUSH_RETRY["ts"] < interval:
        return
    _PUSH_RETRY["ts"] = now
    try:
        r = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return                      # 没有上游 / 不是仓库 ⇒ 静默跳过 ✓
        if int((r.stdout or "0").strip() or 0) <= 0:
            return                      # 没有待推提交 ✓
        p = subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
        if p.returncode == 0:
            print("[push] 补推成功（之前失败的提交已同步）")
        else:
            print("[warn] 补推仍失败（rc=%s）：%s"
                  % (p.returncode, (p.stderr or "").strip()[-200:]))
    except (subprocess.SubprocessError, OSError, ValueError):
        pass


def run_once(commit=True):
    """跑一轮。返回 [(id, status), ...]。"""
    _try_push_pending()
    # 上一轮「延迟重装」的结果在这轮收 ✓（顺带把结果并进任务结果文件 ✓）
    reinstalled = _collect_reinstall()
    auto = _auto_clean()
    if auto and auto.get("moved"):
        print("[auto-clean] 已归档 %d 个插件层文件 -> %s"
              % (auto["moved"], auto.get("dest")))
    done = []
    for spec in _load_pending():
        action = str(spec.get("action") or "")
        fn = ACTIONS.get(action)
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        spec["_t0"] = time.time()
        if fn is None:
            # 未知 action ⇒ 明确失败，不静默跳过 ✓（否则下发方以为在排队）
            _write_result(spec, "failed", -1,
                          "未知 action：%s（白名单：%s）"
                          % (action, ", ".join(sorted(ACTIONS))),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "failed"))
            continue
        # 2026-10-29：执行期打「运行中」旁路标记 ✓ —— 否则 8 分钟的简报任务
        # 在看板上一直显示「排队中」，用户以为卡住了 ✗
        _mark_running(spec["id"])
        try:
            # `_tid` 只给**声明需要**的动作（见 `NEEDS_TID`）✓ —— 全局注入会污染
            # 其它动作的 params（有测试锁着「动作收到的就是下发的那份」✗）
            _params = dict(spec.get("params") or {})
            if action in NEEDS_TID:
                _params.setdefault("_tid", spec["id"])
            r = fn(_params)
            ok = bool(r.get("ok")) if isinstance(r, dict) else True
            _write_result(spec, "done" if ok else "failed",
                          0 if ok else 1,
                          json.dumps(r, ensure_ascii=False),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "done" if ok else "failed"))
        except Exception as exc:      # noqa: BLE001 —— 任何异常都要留痕，不能静默 ✗
            _write_result(spec, "failed", -1,
                          "%s: %s" % (type(exc).__name__, exc),
                          started, time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append((spec["id"], "failed"))
        finally:
            _clear_running(spec["id"])

    # 只有重装结果回写、没有新任务时也要提交 ✓（否则结果永远留在 Mac 本地 ✗）
    if commit and (done or reinstalled):
        if done:
            # 2026-10-29：顺带瘦身 ✓ —— 每个任务两个 json 永不清理会无限涨 ✗
            dropped = _prune_queue()
            if dropped:
                print("[prune] 清理 %d 个旧任务文件（只留最近 %d 个）"
                      % (len(dropped), KEEP_TASKS))
        _git_commit(done or [(t, "reinstall") for t in reinstalled])
    return done


#: 任务会写出的**产物目录** ✓ —— 只提交这些，**绝不用 `git add -A`** ✗
#: （Mac 上常年有测试产物/临时文件 ✗）
#: 2026-10-30 实测教训：`factor_backtest_probe --json evolution/...` 写的裁判
#: 产物**没进 git** ✗ ⇒ Windows 端只能看到被 `output[-2000:]` 截断的 stdout ✗
TASK_OUTPUT_DIRS = ("evolution/experiments/factor-adoption",)

#: 🔴 每日链的 `evolve_*` 会**改写**这些登记表 ✗ —— 队列不提交就会让 Mac 侧
#: 永远留一份「未提交修改」⇒ 之后任何对它们的 patch 都报**冲突中止** ✗
#: （2026-10-30 实测：`sync_1028dn` 因 `evolution/hypotheses.md` 冲突入库失败 ✗）
TASK_OUTPUT_FILES = ("evolution/hypotheses.md",
                     "evolution/factors.md",
                     "evolution/hypothesis_results.md",
                     # 2026-10-30：C2 的三个数据源由任务抓取 ⇒ 必须入库 ✓
                     # （否则数据只躺在 Mac 本地 ✗，Windows 侧既看不到也没法开发因子 ✗）
                     # 体量：PE/CAPE 各 ~1870 行、DGS10 16191 行，都在 200KB 内 ✓
                     "Data/raw/sp500_pe.csv",
                     "Data/raw/sp500_cape.csv",
                     "Data/raw/fred_DGS10.csv")


def _git_commit(done):
    """提交 `docs/task-queue/` + **任务产物目录** ✓ —— 不碰其他脏文件 ✗。"""
    try:
        paths = ["docs/task-queue"] + [
            d for d in TASK_OUTPUT_DIRS
            if os.path.isdir(os.path.join(ROOT, d))] + [
            f for f in TASK_OUTPUT_FILES
            if os.path.isfile(os.path.join(ROOT, f))]
        subprocess.run(["git", "add", *paths], cwd=ROOT,
                       check=True, capture_output=True, timeout=60)
        msg = "task: %s" % "; ".join("%s=%s" % (i, s) for i, s in done)
        r = subprocess.run(["git", "commit", "-m", msg], cwd=ROOT,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:          # 无变更可提交 ⇒ 不是错误 ✓
            return
        p = subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
        # 🔴 推送失败**必须留痕** ✗ —— 原来 `except: pass` 把一切吞掉 ⇒
        # 结果文件只躺在 Mac 本地，Windows 端永远看不到任务结果 ✗
        # （2026-10-28 实测：`t-…-clean_sync_partial.result.json` 至今没进 gitee ✗）
        # 日志落在 plist 的 StandardOutPath `/tmp/fg_task_queue.log` ✓。
        if p.returncode != 0:
            print("[warn] 结果已提交但**推送失败**（rc=%s）：%s"
                  % (p.returncode, (p.stderr or "").strip()[-200:]))
    except (subprocess.SubprocessError, OSError) as exc:
        # 失败不影响任务本身的结果文件 ✓，但必须可查 ✗
        print("[warn] 结果提交/推送失败：%s" % exc)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mac 侧任务队列执行器")
    ap.add_argument("--no-commit", action="store_true", help="只执行不提交（调试）")
    args = ap.parse_args(argv)
    done = run_once(commit=not args.no_commit)
    for i, s in done:
        print("%s -> %s" % (i, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
