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
import contextlib
import os
# 🔴 2026-11-05：`probe_url` 用 `re.findall` 提取 URL/百分比 ✗
#    而模块顶部**一直没导入 `re`** ✗
#    ⇒ 三个 `probe_url` 任务全报 `NameError: name 're' is not defined` ✗
import re
import shutil
import subprocess
import sys
import time

#: 🔴 动作侧基础设施在 `queue_core.py` ✓（2026-11-19 第三轮抽出）
#:   下一步按 8 个包拆 action 时，包与调度器共用这一层，避免互相 import 成环 ✓
#:   这里用**别名导入** ⇒ `q._run` / `q._safe_rel` 等旧名字仍然可用（测试靠它 patch）✓
#: ⚠️ 看板是 `from scripts import run_task_queue` 导入的 ✗ —— 那种方式下
#:   `scripts/` 不一定在 `sys.path` ⇒ `import queue_core` 会 ModuleNotFoundError ✗
#:   ⇒ 先把自己所在目录塞进去，两种 import 方式都成立 ✓
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import queue_core as _qc                                          # noqa: E402
from queue_core import (ROOT, BSK_BIN, READ_ALLOW as _READ_ALLOW,  # noqa: E402
                        run as _run, safe_rel as _safe_rel,
                        allow_json as _allow_json, rel_ok as _rel_ok,
                        script_allowed as _script_allowed,
                        tail_logs as _tail_logs,
                        task_outputs as _task_outputs)
from queue_actions.futu import ACTIONS as _FUTU_ACTIONS          # noqa: E402
#: `agent_status` / `install_agent` **不是 action**（看板调的）✓
#: ⇒ re-export 保持 `from scripts import run_task_queue` 的调用方不变 ✓
from queue_actions.launchd import (ACTIONS as _LAUNCHD_ACTIONS,   # noqa: E402
                                   agent_status, install_agent)
from queue_actions.diag import ACTIONS as _DIAG_ACTIONS          # noqa: E402
from queue_actions.git import ACTIONS as _GIT_ACTIONS            # noqa: E402
from queue_actions.data import ACTIONS as _DATA_ACTIONS          # noqa: E402
from queue_actions.research import ACTIONS as _RESEARCH_ACTIONS  # noqa: E402
from queue_actions.diag2 import ACTIONS as _DIAG2_ACTIONS      # noqa: E402
from queue_actions.files import ACTIONS as _FILES_ACTIONS      # noqa: E402

QUEUE = os.path.join(ROOT, "docs", "task-queue")


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _fg_pos_tendency(pd, root, with_erp):
    """把「6 因子合成」转成**仓位倾向** 0~100（高=该加仓）✓

    🔴 为什么必须转：`fg_index` 是**贪婪度**（高=贪婪=该减仓）✗
       而 `factor_backtest_probe` 的 `positive` 方向是「因子高 ⇒ 仓位高」✗
       ⇒ 直接把 `fg_index` 丢进去会**方向反了** ✗
       ⇒ 统一转成 `100 - fg_index`（恐惧度，高=该加仓）✓

    `with_erp=True` 时：`0.9 × (100-fg_index) + 0.1 × (erp×100)` ✓
       - ERP 是 0~1 分位（高=便宜=该加仓 ✓，与「恐惧度」同向 ✓）
       - 权重 10%：参照 `config.WEIGHTS` 里 putcall 的 0.10 ✓
         其余 6 项按比例缩到 0.90 ✓（不新增权重总量，只做再分配 ✓）
    """
    base = pd.read_csv(os.path.join(root, "Data", "features.csv"))
    base["date"] = base["date"].astype(str).str[:10]
    base["fg_index"] = pd.to_numeric(base["fg_index"], errors="coerce")
    df = base[["date", "fg_index"]].dropna()
    df["fg_base"] = 100.0 - df["fg_index"]
    if not with_erp:
        return df[["date", "fg_base"]]

    erp = _compute_erp(root, pd)
    m = df.merge(erp, on="date", how="inner").dropna()
    m["fg_erp"] = 0.90 * m["fg_base"] + 0.10 * (m["erp"] * 100.0)
    return m[["date", "fg_erp"]]


#: `read_tail` 允许读的路径前缀 ✓ —— 定义已上移 `queue_core.READ_ALLOW`
#: （`data` 包也要用）⇒ 这里只留别名 ✓


#: 需要「从仓库副本装到 LaunchAgents」的 plist ✓
PLISTS = ["com.xingguo.fg-daily.plist", "com.xingguo.fg-task-queue.plist",
          # 2026-11-03 新增：每周一 07:30 跑 `weekly_review.py` ✓
          # （必须在 Mac ✗ Windows 的 Data/raw 只是旧快照 ✗）
          "com.xingguo.fg-weekly-review.plist"]


#: ⚠️ 这个动作**留在调度器**（没进 `queue_actions/launchd.py`）✗ ——
#:    它要往 `QUEUE/<tid>.reinstall.json` 写延迟重装回执 ✗，
#:    而 `QUEUE` 是调度器状态（测试靠 `monkeypatch.setattr(q, "QUEUE", ...)` 重定向）
#:    ⇒ 搬进包会让它读 core 的未 patch 值 ✓
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
            _run(["launchctl", "bootout", "%s/%s" % (domain, label)], 30)
            r = _run(["launchctl", "bootstrap", domain, dst], 60)
            _run(["launchctl", "enable", "%s/%s" % (domain, label)], 30)
            out[name] = "ok" if r.returncode == 0 else (r.stderr or "")[-200:]
        except (subprocess.SubprocessError, OSError) as exc:
            out[name] = "launchctl 失败：%s" % exc
    # 🔴 2026-11-03 用户要求：**装完必须验证** ✗
    #    原来只返回「拷贝成功」✗ 无法证明
    #    ① 代理变量真的进了 `~/Library/LaunchAgents/*.plist` ✗
    #    ② launchd 认了这份配置 ✗
    #    ⇒ 而 `launchctl print` **不显示 EnvironmentVariables** ✗
    #    ⇒ 只能「回读已安装的 plist 文件」+「看 launchd 状态」两条并用 ✓
    verify = {}
    for name in PLISTS:
        dst = os.path.join(agent, name)
        v = {}
        try:
            import plistlib as _pl
            with open(dst, "rb") as f:
                d = _pl.load(f)
            ev = d.get("EnvironmentVariables") or {}
            v["proxy_in_file"] = {
                k: ev.get(k) for k in
                ("FG_LLM_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
                if k in ev
            }
            v["env_keys"] = sorted(ev)
        except Exception as exc:            # noqa: BLE001
            v["file_error"] = str(exc)[:120]
        label = name[:-len(".plist")]
        try:
            r = _run(["launchctl", "print", "%s/%s" % (domain, label)], 60)
            txt = r.stdout or r.stderr or ""
            keep = [ln.strip() for ln in txt.splitlines()
                    if any(k in ln for k in ("state =", "last exit",
                                             "runs =", "path ="))]
            v["launchd"] = " | ".join(keep[:4]) or "(无输出)"
        except Exception as exc:            # noqa: BLE001
            v["launchd"] = "查不到：%s" % exc
        verify[name] = v

    return {"ok": all(v.startswith("ok") or v.startswith("已拷贝")
                      for v in out.values()),
            "result": out,
            "verify": verify,
            "note": "⚠️ `launchctl print` **不显示 EnvironmentVariables** ✗ "
                    "⇒ 代理是否生效看 `verify.*.proxy_in_file` ✓；"
                    "真实生效要等下次链跑（看 fetch 耗时）✓"}


#: 需要 `_tid` 的动作 ✓ —— 只有「结果要延迟回写」的才需要知道自己是哪个任务
#: （`install_daily_plist` 的游离 shell 要把结果写成 `<tid>.reinstall.json` ✓）
NEEDS_TID = {"install_daily_plist"}


#: 🔴 唯一可执行清单。键是**任务名**，值是固定函数 —— 不接受任何命令字符串 ✓
#: 基础环境变量白名单 ✓ —— 动作**只能**看到这些（2026-11-02 用户裁定）
#: 🔴 原来 `subprocess` **继承全部** `os.environ` ✗ ⇒
#:   ① 动作能读到 plist 里所有密钥（`FG_LLM_KEY` / `FEISHU_OPEN_ID` …）✗
#:   ② 而**行为开关**（`FG_SYNC_MODE`）又因为没在 plist 里而丢失 ✗
#:      ⇒ `sync_positions` 跑成 static、什么都没验证 ✗
#: ⇒ 改成「**白名单 + 每动作声明**」✓
#: ⚠️ 只放**无害**的基础项 ✗ —— 绝不放密钥/凭据 ✓
#: （2026-11-02：`HOME` 缺失让富途 SDK 崩过 ✗ ⇒ 一次补全常见项，
#:   避免「报一个补一个」的往返 ✗）
_BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "PYTHONPATH",
             "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE",
             "USER", "LOGNAME", "SHELL", "TERM", "SSH_AUTH_SOCK")

#: 每个动作**额外**可见的环境变量 ✓
#: 值可以是 `set`（按名取 `os.environ`）或 `dict`（显式注入/覆盖）✓
ACTION_ENV = {
    # `sync_positions.py` 默认 static ✗ ⇒ 必须显式 live 才会真调富途/OKX ✓
    "sync_positions": {"FG_SYNC_MODE": "live"},
    # 简报需要：飞书 open_id + LLM 通道配置（plist 里那份）
    "run_invest_research": {
        # ⚠️ **不含 `FG_LLM_KEY`** ✗（2026-11-02 用户裁定）——
        # 简报走**本地 Hermes**（`127.0.0.1:8642`）✓ key 由 Hermes 自己管 ✓
        # ⇒ 脚本不需要拿到明文 key ✗（`_read_llm_key()` 会从 `~/.dsh` 读 ✓）
        "FEISHU_OPEN_ID", "FG_LLM_URL", "FG_LLM_MODEL",
        "FG_LLM_PROXY", "FG_HERMES_URL", "FG_HERMES_MODEL", "FG_PROXY",
    },
    # 日报链里的抓数动作要走代理（`config.PROXY` 读 `FG_PROXY`）
    "fetch_fred": {"FG_PROXY"},
    "fetch_pe_ratio": {"FG_PROXY"},
    "fetch_indices": {"FG_PROXY"},
    "fetch_shoutu_history": {"FG_PROXY"},
}


def _env_for(action):
    """该动作可见的环境变量 ✓（白名单 + 声明）"""
    env = {k: os.environ[k] for k in _BASE_ENV if k in os.environ}
    # 🔴 2026-11-02 实测：launchd 起的队列进程**可能没有 `HOME`** ✗ ——
    # 富途 SDK 硬读 `os.environ['HOME']`（`ft_logger.py:71`）✗
    # ⇒ 直接 `KeyError: 'HOME'` 崩在 import 阶段 ✗
    # （白名单「只拷贝已存在的键」会把这个缺失**放大**成崩溃 ✗）
    # ⇒ 缺失时用 `expanduser("~")` 兜底 ✓
    if "HOME" not in env:
        try:
            env["HOME"] = os.path.expanduser("~")
        except Exception:                   # noqa: BLE001
            pass
    spec = ACTION_ENV.get(action) or ()
    if isinstance(spec, dict):
        env.update({k: str(v) for k, v in spec.items()})
    else:
        for k in spec:
            if k in os.environ:
                env[k] = os.environ[k]
    return env


@contextlib.contextmanager
def _scoped_env(action):
    """执行期间把 `os.environ` **收窄**成该动作的白名单 ✓。

    这样所有 `subprocess.run(...)`（继承 `os.environ`）都自动受限 ✓
    —— 一处改造，26 个调用点全覆盖 ✓（逐个改容易漏 ✗）
    """
    saved = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(_env_for(action))
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


ACTIONS = {
    # 🔴 动作包（2026-11-19 第四轮起按 8 个包拆）✓ —— 注册表仍是**唯一入口** ✗
    #    包只导出 `ACTIONS` 字典，调度器在这里合并 ⇒ 不改装饰器/自动发现 ✓
    **_FUTU_ACTIONS,
    **_LAUNCHD_ACTIONS,
    **_DIAG_ACTIONS,
    **_GIT_ACTIONS,
    **_DATA_ACTIONS,
    **_RESEARCH_ACTIONS,
    **_DIAG2_ACTIONS,
    **_FILES_ACTIONS,
    "install_daily_plist": _act_install_daily_plist,
}


#: **优先执行**的 action（重启类）—— 见 `_load_pending` 的排序说明。
PRIORITY_ACTIONS = ("restart_dashboard", "restart_queue")


#: 待执行任务超过这么久还没回执 ⇒ 视为**失效**，自动归档 ✓（2026-11-10）
#: 🔴 事故：11-09 那批任务（`deepseek_probe` / `git_state` ×3 / `clean_sync_partial`）
#:    的 json 留在队列里、但 `.result.json` 在 `git reset` 时被丢了 ✗
#:    ⇒ `_load_pending` 每一轮都把它们当新任务**重跑** ✗
#:    ⇒ 队列每 10 秒的窗口全被老任务吃掉 ⇒ 新任务看起来「一直排队中」✗
#: ⚠️ 阈值 **6 小时**（曾改 24，已改回）✓
#:    24h 的问题：11-09 那批僵尸任务才 18 小时 ⇒ 逃过归档 ✗ 继续每轮重跑 ✗
#:    6h 当初误伤「刚下发」的原因不是阈值，而是**判据用了 mtime** ✗
#:    ⇒ 判据改成 `created_at`（见 `_archive_stale_pending`）后，6h 是安全的 ✓
STALE_PENDING_HOURS = 6


def _archive_stale_pending(hours=STALE_PENDING_HOURS):
    """把**超时仍无回执**的任务 json 挪进 `_stale/` ✓（不删，可人工恢复）。

    判据：json 的 mtime 早于 `hours` 前，且**没有**同名 `.result.json`。
    ⚠️ 只挪 `docs/task-queue/*.json`，不碰 `.result.json` / `.running` ✓
    """
    import shutil
    dst = os.path.join(QUEUE, "_stale")
    moved = []
    try:
        names = sorted(os.listdir(QUEUE))
    except OSError:
        return moved
    cutoff = time.time() - hours * 3600
    for name in names:
        if not name.endswith(".json") or name.endswith(".result.json"):
            continue
        p = os.path.join(QUEUE, name)
        tid = name[:-len(".json")]
        if os.path.exists(os.path.join(QUEUE, tid + ".result.json")):
            continue
        try:
            # 🔴 2026-11-10 实测事故：**只看 mtime 会把刚到的新任务归档掉** ✗
            #    （13:49 下发的 `test_futu_fed` 在 13:53 就被归档 ✗）
            #    原因：文件是 fg-sync **重新检出**的，mtime 可能被刷新成旧值/不一致 ✗
            #    ⇒ 改用 `created_at`（任务 json 里的权威字段）+ mtime，**取较新者** ✓
            t_created = 0.0
            try:
                with open(p, encoding="utf-8") as _fh:
                    _spec = json.load(_fh)
                _c = str(_spec.get("created_at") or "")
                if _c:
                    t_created = time.mktime(time.strptime(_c, "%Y-%m-%dT%H:%M:%S"))
            except (OSError, ValueError, KeyError):
                t_created = 0.0
            # 🔴 2026-11-10 第二次修正：**只用 `created_at`**（权威）✓
            #    上一版用 `max(created_at, mtime)` ✗ —— 老任务被重新检出后
            #    mtime 变新 ⇒ 看起来像新任务 ⇒ 永远归档不掉 ✗
            #    （实测：11-09 那批 5 个任务在 11-10 15:20 仍 pending ✗）
            #    `created_at` 缺失时才退回 mtime ✓
            _age_base = t_created or os.path.getmtime(p)
            _age_h = (time.time() - _age_base) / 3600.0
            # 🔴 2026-11-11 用户要求：**「有 .running 才归档」** ✓
            #    事故：11-10 17:27 下发的 `autostart_list` 因为队列卡住没跑成 ✗
            #    到 11-11 09:02（15.5 小时 > 6h 阈值）被**静默归档** ✗
            #    ⇒ 用户以为它执行了，其实压根没轮到 ✗
            #    ⇒ 分两档：
            #      ① 有 `.running` 残留 ⇒ 说明**尝试过但卡死** ⇒ 6 小时就归档 ✓
            #      ② 没有 `.running` ⇒ 说明**压根没轮到** ⇒ 要 **24 小时**才归档 ✓
            #    （24h 是为了兜住 11-09 那批 result 丢了的真僵尸 ✓）
            _has_running = os.path.exists(os.path.join(QUEUE, tid + ".running"))
            if _has_running:
                if _age_base > cutoff:            # 6h
                    continue
            elif _age_h < 24:
                continue
            os.makedirs(dst, exist_ok=True)
            shutil.move(p, os.path.join(dst, name))
            moved.append(name)
            print("[stale]   %s（%.1f 小时，%s）"
                  % (name, _age_h,
                     "有 .running 残留" if _has_running else "从未执行过"))
        except OSError:
            continue
    if moved:
        print("[stale] 已归档 %d 个超时无回执的任务 -> _stale/" % len(moved))
        for m in moved:
            print("   %s" % m)
    return moved


def _load_pending():
    """列出待执行任务（status=pending）：**重启类优先**，其余按 id 升序。"""
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
    # 🔴 2026-11-06：**重启类提到队首** ✓ —— 队列是串行的，而 `fetch_prices`
    #    的 timeout 是 1800 秒 ✗ ⇒ 排在它后面的 `restart_dashboard` 白等 16 分钟 ✗
    #    （实测：12:40 下发，13:55 才执行 ✗）。重启只要几秒且决定页面能不能用 ✓
    out.sort(key=lambda s: (0 if str(s.get("action") or "") in PRIORITY_ACTIONS
                            else 1, str(s.get("id") or "")))
    return out


def _write_result(spec, status, rc, output, started, finished):
    rec = {
        "id": spec["id"],
        "action": spec.get("action"),
        "params": spec.get("params") or {},
        "status": status,
        "rc": rc,
        # 🔴 2026-11-03：2000 → **8000** ✗ —— 实测 `audit_data` 的 JSON
        #    在 2000 处被**从中间切断** ⇒ `json.loads` 直接失败 ✗
        #    ⇒ 结果「看得见但解析不了」✗（`ok: None` 就是这个症状 ✗）
        #    ⚠️ 仍有上限 ✗ —— 超长输出请让动作**自己精简** ✓（见 `_act_audit_data`）
        "output": output[-8000:],
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
        r = _run(["git", "rev-list", "--count", "@{u}..HEAD"], 30)
        if r.returncode != 0:
            return                      # 没有上游 / 不是仓库 ⇒ 静默跳过 ✓
        if int((r.stdout or "0").strip() or 0) <= 0:
            return                      # 没有待推提交 ✓
        p = _run(["git", "push", "origin", "HEAD"], 180)
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
    # 🔴 2026-11-10：先把「超时无回执」的失效任务归档 ✓
    #    否则它们每轮都被当新任务重跑，新任务永远排不上 ✗
    _moved = _archive_stale_pending()
    done = []
    for spec in _load_pending():
        action = str(spec.get("action") or "")
        fn = ACTIONS.get(action)
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        spec["_t0"] = time.time()
        if fn is None:
            # 未知 action ⇒ 明确失败，不静默跳过 ✓（否则下发方以为在排队）
            # 🔴 2026-11-02 实测：最常见的原因是**代码还没入库** ✗ ——
            # 任务 json 和代码分两个包发，若任务 id 早于代码包入库时间，
            # 队列会先用**旧版** `ACTIONS` 跑 ⇒ 报「未知 action」✗
            # （`t-20261102-152253-bsk_status` 就是这么失败的 ✗）
            # ⇒ 提示里必须写清这条，否则看起来像「动作名拼错」✗
            _write_result(spec, "failed", -1,
                          "未知 action：%s（白名单：%s）\n"
                          "⚠️ 若该动作**刚加进代码**：多半是**代码包还没入库** ✗ "
                          "—— 任务 json 与代码分两个包发时，"
                          "必须**先确认代码入库**再下发任务 ✓"
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
            # 🔴 2026-11-19：**先无条件清掉**任务 JSON 里的 `_tid` ✗
            #    实测 `test_tid_cannot_be_overridden` 暴露：只在
            #    `if action in NEEDS_TID` 分支里覆盖 ⇒ 其他 action 拿到的
            #    仍是任务 JSON 里的**恶意值**（`"../../evil"`）✗
            #    ⇒ 先 pop 掉，再按需注入 ✓
            _params.pop("_tid", None)
            if action in NEEDS_TID:
                # 🔴 2026-11-19：**必须覆盖，不能用 `setdefault`** ✗
                #    原写法：任务 JSON 里预先塞 `"_tid": "任意值"` ⇒
                #    `setdefault` 不覆盖 ⇒ 攻击者控制 `_tid` ✗
                #    （`_tid` 用于生成文件名/日志路径 ⇒ 可路径穿越）
                _params["_tid"] = spec["id"]
            # 🔴 2026-11-02：**环境变量白名单** ✓ —— 执行期间 `os.environ`
            # 被收窄成该动作声明的集合 ✗ ⇒ 动作读不到无关密钥 ✓
            with _scoped_env(action):
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
    # 🔴 2026-11-10：**归档也要提交** ✗ —— 原来只在 `done or reinstalled` 时提交 ✗
    #    ⇒ 归档只发生在 Mac 本地 ⇒ origin 上任务 json 还在 ⇒ 两边分叉 ✗
    #    （实测：Mac 显示「待执行 0」，origin 上仍有 2 个）
    if commit and (done or reinstalled or _moved):
        if done:
            # 2026-10-29：顺带瘦身 ✓ —— 每个任务两个 json 永不清理会无限涨 ✗
            dropped = _prune_queue()
            if dropped:
                print("[prune] 清理 %d 个旧任务文件（只留最近 %d 个）"
                      % (len(dropped), KEEP_TASKS))
        _git_commit(done
                    or [(t, "reinstall") for t in reinstalled]
                    or [("stale", "archived%d" % len(_moved))])
    return done


#: 🔴 任务产物白名单已外置到 `scripts/queue_allow/task_outputs.json` ✓
#: （`{"dirs": [...], "files": [...]}` —— 加产物路径只改 json ✓）
# 🔴 2026-11-03 移除：`Data/raw/sp500_pe.csv` / `sp500_cape.csv` /
#    `fred_DGS10.csv` 曾在这里 ✗（2026-10-30 为让 Windows 看到 C2 数据 ✗）
#    但 2026-11-03 用户裁定「数据不入库」⇒ `Data/raw/` 已进 `.gitignore` ✗
#    ⇒ 别再把 `Data/raw/*` 加回 `task_outputs.json` ✗ —— 会被 git 拒绝
#       （`_git_commit` 已改为逐个 add，不会整体失败，但会刷一堆 warn ✓）


def _git_commit(done):
    """提交 `docs/task-queue/` + **任务产物目录** ✓ —— 不碰其他脏文件 ✗。"""
    try:
        try:
            out_dirs, out_files = _task_outputs()
        except (OSError, ValueError) as exc:
            # 白名单坏了 ⇒ 只提交任务结果，别把整个提交搞丢 ✗
            print("[warn] 产物白名单读取失败（本轮只提交任务结果）：%s" % exc)
            out_dirs, out_files = [], []
        paths = ["docs/task-queue"] + [
            d for d in out_dirs
            if os.path.isdir(os.path.join(ROOT, d))] + [
            f for f in out_files
            if os.path.isfile(os.path.join(ROOT, f))]
        # 🔴 2026-11-03：**不能 `check=True`** ✗ —— 只要有一个路径被
        #    `.gitignore` 拒绝（如 `Data/raw/*` ✗），git 就**整体失败** ✗
        #    ⇒ 连 `docs/task-queue` 的结果都提交不了 ✗
        #    ⇒ 改为：**逐个 add** ✓ 失败的单独报警但不中断 ✓
        bad = []
        for pth in paths:
            r = _run(["git", "add", "--", pth], 60)
            if r.returncode != 0:
                bad.append((pth, (r.stderr or "").strip()[:120]))
        if bad:
            print("[warn] 以下路径 add 失败（其余照常提交 ✓）：")
            for pth, err in bad:
                print("   %s —— %s" % (pth, err))
        msg = "task: %s" % "; ".join("%s=%s" % (i, s) for i, s in done)
        r = _run(["git", "commit", "-m", msg], 120)
        if r.returncode != 0:          # 无变更可提交 ⇒ 不是错误 ✓
            return
        p = _run(["git", "push", "origin", "HEAD"], 180)
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


def _acquire_lock():
    """`flock` 排他锁 ✓ —— 防止 launchd **每 10 秒起一个实例**并发抢同一任务 ✗。

    🔴 2026-11-10 实测事故（用户反馈「任务一直显示排队中」）：
       plist 是 `StartInterval = 10` ✗ 而 `run_once()` **没有并发保护** ✗
       ⇒ 只要某个任务跑超过 10 秒（`test_futu_fed` 要 90 秒 ✗），
         launchd 就会**再起一个实例** ⇒ 多个进程同时 `_load_pending()` 抢同一个
         task json ⇒ `.running` 标记互相覆盖、结果文件互相覆盖 ✗
       ⇒ 更糟：多个实例**同时调 futu SDK** ⇒ 直接加重 OpenD 重连循环 ✗
    拿不到锁就**直接退出**（本次跳过，10 秒后自然重试 ✓），不阻塞 ✓
    """
    try:
        import fcntl
    except ImportError:                    # 非 POSIX ⇒ 退化为无锁 ✓
        return object()
    p = os.path.join(QUEUE, ".queue.lock")
    try:
        fh = open(p, "w")
    except OSError:
        return object()
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mac 侧任务队列执行器")
    ap.add_argument("--no-commit", action="store_true", help="只执行不提交（调试）")
    args = ap.parse_args(argv)
    # 🔴 2026-11-12 用户告警「fg-task-queue 日志 39280 秒没动静 ⇒ 疑似卡死」是**误报** ✗
    #    本脚本是 `StartInterval` **定时一次性**任务，不是常驻 ✗
    #    没任务可做时什么都不打印 ⇒ `/tmp/fg_task_queue.log` 的 mtime 不动 ✗
    #    ⇒ 每次运行都 **touch 一个心跳文件**（只改 mtime，不写内容，不涨体积）✓
    #    放在 `_acquire_lock` **之前**：上一轮还在跑也算「活着」✓
    try:
        os.makedirs(QUEUE, exist_ok=True)
        _hb = os.path.join(QUEUE, ".heartbeat")
        with open(_hb, "a"):
            os.utime(_hb, None)
    except OSError:
        pass
    lock = _acquire_lock()
    if lock is None:
        print("[skip] 上一轮仍在执行（flock 未释放）⇒ 本轮跳过")
        return 0
    done = run_once(commit=not args.no_commit)
    for i, s in done:
        print("%s -> %s" % (i, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
