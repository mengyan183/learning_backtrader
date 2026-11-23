# -*- coding: utf-8 -*-
"""launchd / dsh web 相关 action ✓ —— 从 `run_task_queue.py` 拆出的第二个动作包。

【边界】
  · 只依赖 `queue_core`（`ROOT` / `run` / `BSK_BIN`）+ 标准库 ✓
  · **不碰队列状态** ✗ —— `QUEUE` / `run_once` / flock 在调度器里
  · `agent_status` / `install_agent` 不是 action（看板调的），
    调度器 re-export 它们 ⇒ `from scripts import run_task_queue` 的调用方不受影响 ✓
"""
import os
import re
import shutil
import subprocess
import sys
import time

from queue_core import BSK_BIN, ROOT, run as _run
from queue_store import QUEUE

#: launchd 定时器（本脚本每 10s 被调一次）—— 看板可一键安装 ✓


LABEL = "com.xingguo.fg-task-queue"


PLIST_SRC = os.path.join(ROOT, "scripts", LABEL + ".plist")


PLIST_DST = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                         LABEL + ".plist")

#: 🔴 允许操作的 launchd 服务 label ✓（2026-11-19 合并）
#: 原来 `plist_path_append` / `service_bootstrap` / `restart_queue` **各抄一份** ✗
#: ⇒ 加一个服务要改 3 处，漏一处就报「不允许的 label」✗


LAUNCHD_LABELS = ("com.xingguo.fg-task-queue",
                  "com.xingguo.fg-realtime",
                  "com.xingguo.fg-dashboard",
                  "com.xingguo.fg-sync-watcher",
                  # `evolve_verify.py` 由它定时跑 ⇒ 要能远程重启触发一次验证 ✓
                  "com.xingguo.fg-evolve-verify",
                  # 🔴 2026-11-20：`shoutu_fng.csv` 停更 36 天（10-14 之后没再写）✗
                  #   实测 out 日志只有 1 次成功、err 日志只有 2 个 DNS traceback
                  #   ⇒ job 大概率**没被 launchd 加载**（plist 文件在 ≠ 已 bootstrap）✗
                  #   ⇒ 加白名单，好让 `restart_queue` 能对它走 bootout+bootstrap ✓
                  "com.xingguo.fg-shoutu-refresh",
                  # 🔴 2026-11-23：补 `fg-daily` ✓
                  #   改 plist 后必须 bootout+bootstrap 才重读文件 ✗
                  #   实测 `t-20261123-190045` 报「不允许的 label」✗
                  #   而它是 `StartCalendarInterval`（无 RunAtLoad）⇒ 重载**不会**
                  #   立刻触发全链，只在下一个 05:30 生效 ✓
                  #   ⚠️ 若要**立即**验证全链，用 `kickstart`（见 `restart_queue` 实现）
                  "com.xingguo.fg-daily",
                  "com.xingguo.dsh.web")


def agent_status():
    """定时器是否已安装 / 已加载（看板据此决定要不要显示安装按钮）。"""
    installed = os.path.isfile(PLIST_DST)
    loaded = False
    try:
        r = _run(["launchctl", "list"], 15)
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
        _run(["launchctl", "bootout", dom + "/" + LABEL], 30)
        r = _run(["launchctl", "bootstrap", dom, PLIST_DST], 60)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "launchctl 执行失败：%s" % exc}
    st = agent_status()
    out = {"ok": bool(st["loaded"]) or r.returncode == 0,
           "stdout": (r.stdout or "")[-300:], "stderr": (r.stderr or "")[-300:]}
    out.update(st)
    return out


def _act_dsh_web_diag(params):
    """查 `com.xingguo.dsh.web` 为什么起不来 ✓（2026-11-11 用户要求看日志）。

    🔴 背景（`autostart_list` 回执）：
       `com.xingguo.dsh.web` 的 `RunAtLoad=true` + `KeepAlive=true` ✓
       但 `running: []` ⇒ **进程没在跑** ✗
       ⇒ 这就是 `dsh web authentication required` 的根因 ✓

    查六件事：
      ① plist 全文（ProgramArguments / StandardOutPath / ThrottleInterval）
      ② `launchctl list` 里它的状态（PID + 最后退出码）
      ③ StandardOutPath / StandardErrorPath 的日志尾巴
      ④ `~/.dsh/logs/` 里最新的 startup 日志
      ⑤ 当前有没有 dsh 相关进程
      ⑥ `launchctl print` 的 last exit status（能看出崩溃原因）
    """
    import glob as _g
    home = os.path.expanduser("~")
    plist = os.path.join(home, "Library", "LaunchAgents",
                         "com.xingguo.dsh.web.plist")
    out = {"steps": {}}

    # ① plist
    try:
        out["steps"]["plist"] = open(plist, encoding="utf-8").read()[:3000]
    except OSError as exc:
        out["steps"]["plist"] = "ERR %s" % str(exc)[:120]

    # ② launchctl list
    try:
        r = _run(["launchctl", "list"], 20)
        out["steps"]["launchctl"] = [ln for ln in (r.stdout or "").splitlines()
                                     if "dsh" in ln.lower()] or ["(没有 dsh 相关项)"]
    except Exception as exc:              # noqa: BLE001
        out["steps"]["launchctl"] = "ERR %s" % str(exc)[:120]

    # ③ 日志（从 plist 里抠 StandardOutPath / StandardErrorPath）
    logs = {}
    for key in ("StandardOutPath", "StandardErrorPath"):
        try:
            txt = out["steps"]["plist"]
            import re as _re
            m = _re.search(r"<key>%s</key>\s*<string>([^<]+)</string>" % key, txt)
            if not m:
                continue
            lp = m.group(1).strip()
            if not os.path.exists(lp):
                logs[key] = {"path": lp, "exists": False}
                continue
            with open(lp, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            logs[key] = {"path": lp, "exists": True,
                         "age_sec": int(time.time() - os.path.getmtime(lp)),
                         "size": len(lines),
                         "tail": "".join(lines[-40:])[-2500:]}
        except Exception as exc:          # noqa: BLE001
            logs[key] = "ERR %s" % str(exc)[:120]
    out["steps"]["logs"] = logs or "(plist 里没写 StandardOutPath)"

    # ④ ~/.dsh/logs 最新 startup 日志
    try:
        files = sorted(_g.glob(os.path.join(home, ".dsh", "logs", "*.log")),
                       key=os.path.getmtime, reverse=True)[:2]
        recent = []
        for fp in files:
            with open(fp, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            recent.append({"file": os.path.basename(fp),
                           "age_min": int((time.time() - os.path.getmtime(fp)) / 60),
                           "tail": "".join(lines[-30:])[-2000:]})
        out["steps"]["dsh_startup_logs"] = recent or "(无)"
    except Exception as exc:              # noqa: BLE001
        out["steps"]["dsh_startup_logs"] = "ERR %s" % str(exc)[:120]

    # ⑤ 进程
    try:
        r = _run(["/bin/sh", "-c",
                  "ps ax -o pid,etime,comm | grep -i dsh "
                  "| grep -v grep | head -10"], 20)
        out["steps"]["processes"] = [ln.strip() for ln in
                                     (r.stdout or "").splitlines() if ln.strip()] or ["(无)"]
    except Exception as exc:              # noqa: BLE001
        out["steps"]["processes"] = "ERR %s" % str(exc)[:120]

    # ⑥ launchctl print（含 last exit status）
    try:
        uid = os.getuid() if hasattr(os, "getuid") else 501
        r = _run(["launchctl", "print",
                  "gui/%s/com.xingguo.dsh.web" % uid], 20)
        txt = (r.stdout or "") + (r.stderr or "")
        keep = [ln.strip() for ln in txt.splitlines()
                if any(k in ln for k in ("state", "last exit", "runs",
                                         "pid", "program", "path"))]
        out["steps"]["launchctl_print"] = keep[:15] or txt[:600]
    except Exception as exc:              # noqa: BLE001
        out["steps"]["launchctl_print"] = "ERR %s" % str(exc)[:120]

    out["ok"] = True
    return out


def _act_autostart_list(params):
    """列出 Mac 上**所有开机自启项** ✓（2026-11-10 用户问「有没有自动拉起 dsh 的程序」）。

    🔴 为什么需要：仓库里 15 个 plist 全是贪恐系统的 ✓
       但 **Mac 上还可能有 dsh 自己装的 LaunchAgent**（`~/.dsh/` 那套 ✗）
       ⇒ 只看仓库会漏 ✗ ⇒ 必须看 `~/Library/LaunchAgents/` 实际内容 ✓

    查四处：
      ① `~/Library/LaunchAgents/*.plist` —— 逐个数 Label + 程序路径
      ② `/Library/LaunchAgents/*.plist`（系统级）
      ③ 登录项（`osascript` 读 `login item`）
      ④ 当前跑着的 dsh / harness 进程
    """
    import glob as _g
    home = os.path.expanduser("~")
    out = {"user_agents": [], "system_agents": [], "login_items": [],
           "running": [], "dsh_related": []}

    def _read_plist(p):
        """读 Label 与 ProgramArguments（用 plutil -p，纯文本输出好解析）。"""
        info = {"path": os.path.relpath(p, home)}
        try:
            r = _run(["/usr/bin/plutil", "-p", p], 15)
            txt = r.stdout or ""
        except Exception as exc:              # noqa: BLE001
            info["error"] = str(exc)[:100]
            return info
        import re as _re
        m = _re.search(r'"Label"\s*=>\s*"([^"]+)"', txt)
        if m:
            info["label"] = m.group(1)
        # ProgramArguments 是个数组，取其中含 / 的前 3 项
        args = _re.findall(r'^\s*"\s*([^"]*\/[^"]*)"\s*$', txt, _re.M)
        if args:
            info["args"] = args[:3]
        m2 = _re.search(r'"Program"\s*=>\s*"([^"]+)"', txt)
        if m2:
            info["program"] = m2.group(1)
        m3 = _re.search(r'"RunAtLoad"\s*=>\s*(true|TRUE|1)', txt)
        info["run_at_load"] = bool(m3)
        m4 = _re.search(r'"KeepAlive"\s*=>\s*(true|TRUE|1)', txt)
        info["keep_alive"] = bool(m4)
        return info

    for base, key in ((os.path.join(home, "Library", "LaunchAgents"), "user_agents"),
                      ("/Library/LaunchAgents", "system_agents")):
        for p in sorted(_g.glob(os.path.join(base, "*.plist"))):
            out[key].append(_read_plist(p))

    # ③ 登录项
    try:
        r = _run(
            ["osascript", "-e",
             'tell application "System Events" to get the name of every login item'],
            20)
        out["login_items"] = [x.strip() for x in (r.stdout or "").split(",")
                              if x.strip()]
    except Exception as exc:                  # noqa: BLE001
        out["login_items"] = ["ERR %s" % str(exc)[:100]]

    # ④ 正在跑的进程（dsh / harness / deepseek）
    try:
        r = _run(["/bin/sh", "-c",
                  "ps ax -o pid,comm | grep -i -E "
                  "'dsh|harness|deepseek' | grep -v grep | head -15"], 20)
        out["running"] = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    except Exception as exc:                  # noqa: BLE001
        out["running"] = ["ERR %s" % str(exc)[:100]]

    # ⑤ 汇总：哪些自启项跟 dsh 有关
    _kw = ("dsh", "harness", "deepseek")
    for item in out["user_agents"] + out["system_agents"]:
        blob = " ".join(str(item.get(k) or "") for k in ("label", "program", "args"))
        if any(k in blob.lower() for k in _kw):
            out["dsh_related"].append(item)

    out["ok"] = True
    out["summary"] = {
        "user_agent_count": len(out["user_agents"]),
        "system_agent_count": len(out["system_agents"]),
        "dsh_related_count": len(out["dsh_related"]),
        "running_count": len(out["running"]),
    }
    out["hint"] = ("`dsh_related` 非空 ⇒ 有 dsh 自启项 ✓；"
                   "为空 ⇒ **没有任何程序自动拉起 dsh** ✗")
    return out


def _act_plist_path_append(params):
    """把 LaunchAgent plist 里的 `export PATH="..."` 改成**追加式** ✓（2026-11-11 用户要求）。

    🔴 问题（`dsh_web_diag` 回执里的 plist 原文）：
       `source ~/.zshrc; export PATH="/usr/local/bin:$HOME/opt/node24/bin:
        /usr/bin:/bin:/usr/sbin:/sbin"; ...; exec dsh web --no-open`
       ⇒ `source ~/.zshrc` 先把用户的 PATH 配好 ✗
       ⇒ 紧接着 `export PATH="..."` **整个覆盖掉** ✗
       ⇒ 且写死 `node24` ✗ —— node 升到 26 后 `~/opt/node24/bin` 不存在
         ⇒ `exec dsh web` 报 `command not found` ✗

    ✅ 改法（追加 + 版本通配兜底）：
       `export PATH="$PATH:/usr/local/bin:$HOME/opt/node24/bin:$(ls -d
        $HOME/opt/node*/bin | sort -V | tail -1)"`
       - `$PATH` 保留 `.zshrc` 的配置 ✓
       - 保留已知可用的 `node24`（不倒退）✓
       - 用 `sort -V | tail -1` 取**最新**的 `node*/bin` ✓ ⇒ 升级后自动跟随 ✓
       ⚠️ 只能用 XML 安全字符（不能出现 `&` / `<` / `>`）✗

    步骤：
      ① 读 plist，备份为 `<plist>.bak-<时间戳>`
      ② 正则替换**第一处** `export PATH="..."`（没有就报错，不乱改）
      ③ `plutil -lint` 校验 XML ✓（不通过就回滚 ✓）
      ④ bootout + bootstrap
      ⑤ 回报新 PATH 行 + 进程状态 + 日志尾巴
    """
    import re as _re

    label = str(params.get("label") or "").strip()
    if label not in LAUNCHD_LABELS:
        return {"ok": False,
                "error": "不允许的 label：`%s` ✗（白名单：%s）"
                         % (label, ", ".join(LAUNCHD_LABELS))}

    home = os.path.expanduser("~")
    plist = os.path.join(home, "Library", "LaunchAgents", label + ".plist")
    uid = os.getuid() if hasattr(os, "getuid") else 501
    target = "gui/%s/%s" % (uid, label)
    out = {"label": label, "plist": plist, "steps": {}}

    if not os.path.exists(plist):
        out["ok"] = False
        out["error"] = "plist 不存在：%s ✗" % plist
        return out

    try:
        with open(plist, encoding="utf-8") as fh:
            src = fh.read()
    except OSError as exc:
        out["ok"] = False
        out["error"] = "读 plist 失败：%s" % str(exc)[:150]
        return out

    # ① 备份
    import datetime as _dt
    bak = plist + ".bak-" + _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        with open(bak, "w", encoding="utf-8") as fh:
            fh.write(src)
        out["steps"]["backup"] = bak
    except OSError as exc:
        out["ok"] = False
        out["error"] = "备份失败，**不动原文件** ✗：%s" % str(exc)[:150]
        return out

    # ② 替换
    _NEW = ('export PATH="$PATH:/usr/local/bin:$HOME/opt/node24/bin:'
            '$(ls -d $HOME/opt/node*/bin | sort -V | tail -1)"')
    m = _re.search(r'export PATH="[^"]*"', src)
    if not m:
        out["ok"] = False
        out["error"] = ("plist 里找不到 `export PATH=\"...\"` ✗ ⇒ "
                        "结构可能不同，不改（备份已留）")
        out["steps"]["old_path"] = "(未找到)"
        return out
    out["steps"]["old_path"] = m.group(0)
    out["steps"]["new_path"] = _NEW
    if m.group(0) == _NEW:
        out["steps"]["changed"] = False
        out["steps"]["note"] = "已经是追加式，无需修改 ✓"
        return {"ok": True, **out}

    new_src = src[:m.start()] + _NEW + src[m.end():]
    try:
        with open(plist, "w", encoding="utf-8") as fh:
            fh.write(new_src)
    except OSError as exc:
        out["ok"] = False
        out["error"] = "写 plist 失败：%s" % str(exc)[:150]
        return out
    out["steps"]["changed"] = True

    # ③ plutil -lint 校验（不通过就回滚）
    try:
        r = _run(["/usr/bin/plutil", "-lint", plist], 20)
        lint_ok = (r.returncode == 0)
        out["steps"]["lint"] = {"rc": r.returncode,
                                "out": ((r.stdout or "") + (r.stderr or "")).strip()[:200]}
    except Exception as exc:              # noqa: BLE001
        lint_ok = False
        out["steps"]["lint"] = {"rc": -1, "out": str(exc)[:150]}
    if not lint_ok:
        try:
            with open(plist, "w", encoding="utf-8") as fh:
                fh.write(src)
            out["steps"]["rolled_back"] = True
        except OSError:
            out["steps"]["rolled_back"] = "回滚失败 ✗"
        out["ok"] = False
        out["error"] = "plutil -lint 不通过 ⇒ 已回滚原文件 ✗"
        return out

    # ④ bootout + bootstrap
    def _sh(cmd, t=30):
        try:
            r = _run(cmd, t)
            return {"rc": r.returncode,
                    "out": ((r.stdout or "") + (r.stderr or "")).strip()[:300]}
        except Exception as exc:          # noqa: BLE001
            return {"rc": -1, "out": str(exc)[:150]}

    out["steps"]["bootout"] = _sh(["launchctl", "bootout", target])
    time.sleep(2)
    out["steps"]["bootstrap"] = _sh(["launchctl", "bootstrap",
                                     "gui/%s" % uid, plist])
    time.sleep(4)

    # ⑤ 状态
    try:
        r = _run(["launchctl", "list"], 20)
        lst = [ln for ln in (r.stdout or "").splitlines() if label in ln]
        out["steps"]["launchctl_list"] = lst or ["(列表里没有它)"]
    except Exception as exc:              # noqa: BLE001
        out["steps"]["launchctl_list"] = "ERR %s" % str(exc)[:100]

    _pid = None
    _lst = out["steps"].get("launchctl_list") or []
    if isinstance(_lst, list) and _lst:
        _f = str(_lst[0]).split()
        if _f and _f[0].isdigit():
            _pid = _f[0]
    if _pid:
        out["steps"]["processes"] = _sh(
            ["ps", "-p", _pid, "-o", "pid,etime,command"])["out"][:300]
    else:
        out["steps"]["processes"] = "(无数字 PID ⇒ 进程未运行)"

    # 日志尾巴（token 打码）
    try:
        r = _run(["/usr/bin/plutil", "-p", plist], 15)
        mm = _re.search(r'"StandardOutPath"\s*=>\s*"([^"]+)"', r.stdout or "")
        if mm and os.path.exists(mm.group(1)):
            with open(mm.group(1), encoding="utf-8", errors="replace") as fh:
                tail = "".join(fh.readlines()[-10:])
            tail = _re.sub(r"(token=)([A-Za-z0-9_\-]{8})([A-Za-z0-9_\-]*)",
                           lambda x: x.group(1) + x.group(2) + "…(%d)"
                           % (len(x.group(2)) + len(x.group(3))), tail)
            out["steps"]["log_tail"] = tail[-800:]
    except Exception as exc:              # noqa: BLE001
        out["steps"]["log_tail"] = "ERR %s" % str(exc)[:150]

    out["ok"] = bool(_pid)
    if not out["ok"]:
        out["hint"] = ("改完 PATH 后服务没起来 ✗ ⇒ 看 log_tail；"
                       "必要时用备份 %s 还原" % os.path.basename(bak))
    return out


def _act_dsh_web_launch(params):
    """**读取 dsh web 的 token URL 并用浏览器打开** ✓（2026-11-11 用户要求）。

    🔴 为什么不用 `dsh_web_open`（跑 `dsh web` 抓 stdout）✗：
       dsh web 是**常驻 launchd 服务**（`com.xingguo.dsh.web`）✓
       再手动跑一个实例会抢 3080 端口 ✗
       ⇒ 正确做法是**从它的日志里读现成 URL** ✓
       （`/tmp/dsh-web-launchd.log` 里 `dsh web: http://127.0.0.1:3080/?token=...`）

    步骤：
      ① 读日志最后一条 `http://127.0.0.1:3080/?token=...`
      ② 探 3080 端口（不通 ⇒ 先提示用 `service_bootstrap`）
      ③ `open <url>` 用**默认浏览器**打开 ✓（人能看到）
      ④ 用 **bsk** 独立验证一次页面能加载 ✓（证据，失败不影响 ③）
    ⚠️ 回执里的 token **打码** ✗（进 git ✓）

    📌 node 版本问题（用户提问）：
       当前 `dsh` 在 `~/opt/node24/bin/dsh` ✗ —— 这是**版本化目录** ✗
       node 升到 26 后该路径失效 ✗（plist 里也硬编码了 node24 ✗）
       ⇒ 本动作**不写死路径**，用 `zsh -lc 'command -v dsh'` 让 shell 自己解析 ✓
         （`source ~/.zshrc` 后的 PATH 才准 ✓）
    """
    import re as _re
    import socket

    out = {"steps": {}}

    # ① 读日志里的 URL
    log_path = "/tmp/dsh-web-launchd.log"
    url = None
    try:
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as fh:
                txt = fh.read()
            hits = _re.findall(r"http://127\.0\.0\.1:3080/\?token=([A-Za-z0-9_\-]+)",
                               txt)
            if hits:
                url = "http://127.0.0.1:3080/?token=" + hits[-1]
                out["steps"]["token_len"] = len(hits[-1])
                out["steps"]["token_head"] = hits[-1][:8] + "…"
        else:
            out["steps"]["log"] = "日志不存在：%s ✗" % log_path
    except OSError as exc:
        out["steps"]["log"] = "读日志失败：%s" % str(exc)[:120]

    if not url:
        out["ok"] = False
        out["error"] = ("日志里没找到 dsh web 的 token URL ✗ ⇒ "
                        "先跑 `service_bootstrap(label=com.xingguo.dsh.web)`")
        return out

    out["url_masked"] = _re.sub(
        r"(token=)([A-Za-z0-9_\-]{8})([A-Za-z0-9_\-]*)",
        lambda m: m.group(1) + m.group(2) + "…(%d)"
        % (len(m.group(2)) + len(m.group(3))), url)

    # ② 探端口
    port_ok = False
    try:
        s = socket.create_connection(("127.0.0.1", 3080), 3.0)
        s.close()
        port_ok = True
    except OSError as exc:
        out["steps"]["port"] = "不通：%s" % str(exc)[:100]
    out["steps"]["port_3080"] = port_ok
    if not port_ok:
        out["ok"] = False
        out["error"] = ("3080 端口不通 ✗ ⇒ dsh web 没在跑，"
                        "先跑 `service_bootstrap(label=com.xingguo.dsh.web)`")
        return out

    # ③ 找 bsk ✓
    # 🔴 2026-11-11 第二次修正：原来用 `zsh -lc 'command -v bsk'` ✗ 找不到 ✗
    #    根因：**`zsh -lc` 是非交互登录 shell，不 source `.zshrc`** ✗
    #    （只 source `.zshenv` / `.zprofile` / `.zlogin`）
    #    而 bsk 通常在 `.zshrc` 配的 PATH 里（npm 全局 / nvm）✗
    #    ⇒ 必须**显式 `source ~/.zshrc`** ✓（和 dsh.web plist 里一个套路）
    #    ⇒ 另加 `~/opt/node*/bin` 通配（node 版本目录）✓
    def _find_bsk():
        # 🔴 2026-11-11：**复用模块级 `BSK_BIN`** ✓ —— 原来这里又写了一份 ✗
        #    重复实现的结果是「两处不一致」：模块级那份我补了 `~/opt/node*/bin`
        #    和 `source .zshrc`，这份没有 ⇒ 修了一处另一处还是找不到 ✗
        if BSK_BIN and BSK_BIN != "bsk" and os.path.isfile(BSK_BIN):
            return BSK_BIN, "BSK_BIN"
        return None, "not_found"

    exe, how = _find_bsk()
    out["steps"]["bsk_exe"] = exe or "(未找到)"
    out["steps"]["bsk_found_by"] = how

    # ④ 按 mode 执行 ✓（`bsk` 默认 / `open` / `both`）
    #    🔴 2026-11-11 用户要求「open 改成 bsk 内部导航」✗
    #    原因：`open` 会**在系统浏览器开新标签** ⇒ 干扰 bsk 的 Agent Window
    #    （实测：`open` 之后连续 3 次发包都卡在「会话列表没出来」✗）
    mode = str(params.get("mode") or "bsk").strip().lower()
    if mode not in ("bsk", "open", "both"):
        mode = "bsk"
    out["mode"] = mode
    ok_any = False

    # ---- bsk 内部导航 ----
    if mode in ("bsk", "both"):
        if not exe:
            out["steps"]["bsk_navigate"] = "跳过（bsk 未找到）✗"
        else:
            sid = ""
            try:
                r1 = _run([exe, "session", "start", "--no-focus"], 60)
                _s1 = (r1.stdout or "").strip().splitlines()
                sid = _s1[-1].strip() if _s1 else ""
                out["steps"]["bsk_session"] = sid or "(start 失败)"
            except Exception as exc:      # noqa: BLE001
                out["steps"]["bsk_session"] = "ERR %s" % str(exc)[:120]
            if sid:
                try:
                    r2 = _run([exe, "navigate", url, "--session", sid,
                               "--timeout", "60s"], 90)
                    _o = ((r2.stdout or "") + (r2.stderr or "")).strip()
                    _o = _re.sub(r"(token=)([A-Za-z0-9_\-]{8})([A-Za-z0-9_\-]*)",
                                 lambda m: m.group(1) + m.group(2) + "…(%d)"
                                 % (len(m.group(2)) + len(m.group(3))), _o)
                    out["steps"]["bsk_navigate"] = {"rc": r2.returncode,
                                                    "out": _o[:400]}
                    # 🔴 验证：最终 url 是否被重定向（token 错会跳登录页）✗
                    _m = _re.search(r"^url=(\S+)", _o, re.M)
                    _final = _m.group(1) if _m else ""
                    if _final:
                        _masked = _re.sub(
                            r"(token=)([A-Za-z0-9_\-]{8})([A-Za-z0-9_\-]*)",
                            lambda m: m.group(1) + m.group(2) + "…(%d)"
                            % (len(m.group(2)) + len(m.group(3))), _final)
                        out["steps"]["final_url"] = _masked
                        _same = (_final.split("?")[0]
                                 == url.split("?")[0])
                        out["steps"]["same_page"] = _same
                        if not _same:
                            out["steps"]["warning"] = (
                                "**被重定向** ✗ —— token 可能失效或未登录")
                    ok_any = ok_any or (r2.returncode == 0
                                        and out["steps"].get("same_page", True))
                except Exception as exc:  # noqa: BLE001
                    out["steps"]["bsk_navigate"] = "ERR %s" % str(exc)[:150]
                try:
                    _run([exe, "session", "stop", sid], 30)
                except Exception:         # noqa: BLE001
                    pass

    # ---- 系统浏览器（兜底 / both 时并用）----
    if mode in ("open", "both"):
        try:
            r = _run(["open", url], 20)
            out["steps"]["open"] = {"rc": r.returncode,
                                    "err": (r.stderr or "").strip()[:150]}
            ok_any = ok_any or (r.returncode == 0)
        except Exception as exc:          # noqa: BLE001
            out["steps"]["open"] = {"rc": -1,
                                    "err": "%s: %s" % (type(exc).__name__,
                                                       str(exc)[:120])}

    out["ok"] = ok_any
    if not out["ok"]:
        out["hint"] = ("两种方式都没成功 ✗ ⇒ 手动打开 `url_masked` 里的地址"
                       "（完整 token 在 Mac 的 %s 里）" % log_path)
    return out


def _act_service_bootstrap(params):
    """**硬重启** launchd 服务：`bootout` + `bootstrap` ✓（2026-11-11 用户要求修 dsh web）。

    🔴 为什么 `kickstart` 不够 ✗（`dsh_web_diag` 回执实测）：
       `launchctl list`       → `16490  -9  com.xingguo.dsh.web`（退出码 -9 = SIGKILL）
       `ps ax | grep dsh`     → **空**（进程真的没了 ✗）
       `launchctl print`      → `state = running, pid = 16490`（**状态卡住** ✗）
       ⇒ launchd 认为它在跑，所以 `kickstart` 不生效 ✗
       ⇒ 必须 `bootout`（清掉注册）再 `bootstrap`（重新加载）✓

    步骤：
      ① `launchctl bootout gui/<uid>/<label>`（失败也继续 ✓）
      ② 等 2 秒
      ③ `launchctl bootstrap gui/<uid> ~/Library/LaunchAgents/<label>.plist`
      ④ 等 3 秒，回报 `launchctl list` 那一行 + `ps` + 日志尾巴
    ⚠️ 日志尾巴里的 **token 段会打码** ✗（回执进 git ✓）
    """
    import re as _re

    label = str(params.get("label") or "").strip()
    if label not in LAUNCHD_LABELS:
        return {"ok": False,
                "error": "不允许的 label：`%s` ✗（白名单：%s）"
                         % (label, ", ".join(LAUNCHD_LABELS))}

    home = os.path.expanduser("~")
    plist = os.path.join(home, "Library", "LaunchAgents", label + ".plist")
    uid = os.getuid() if hasattr(os, "getuid") else 501
    target = "gui/%s/%s" % (uid, label)
    out = {"label": label, "plist": plist, "target": target, "steps": {}}

    if not os.path.exists(plist):
        out["ok"] = False
        out["error"] = "plist 不存在：%s ✗" % plist
        return out

    def _sh(cmd, t=30):
        try:
            r = _run(cmd, t)
            return {"rc": r.returncode,
                    "out": ((r.stdout or "") + (r.stderr or "")).strip()[:400]}
        except Exception as exc:              # noqa: BLE001
            return {"rc": -1, "out": "%s: %s" % (type(exc).__name__,
                                                str(exc)[:150])}

    # ① bootout（服务没注册时 rc!=0 是正常的 ✓ 继续走）
    out["steps"]["bootout"] = _sh(["launchctl", "bootout", target])
    time.sleep(2)

    # ② bootstrap
    # 🔴 2026-11-11 实测踩坑：`bootstrap` 的 domain **只到 `gui/<uid>`** ✗
    #    我第一版写成 `bootstrap gui/501/com.xingguo.dsh.web <plist>` ✗
    #    ⇒ rc=64 `Usage: launchctl bootstrap <domain-target> [service-path...]` ✗
    #    ⇒ 而 bootout 已经成功 ⇒ 服务变成**未注册**（比之前更糟 ✗）
    #    ⇒ 正确：`launchctl bootstrap gui/501 <plist-path>` ✓
    _domain = "gui/%s" % uid
    out["steps"]["bootstrap"] = _sh(["launchctl", "bootstrap", _domain, plist])
    time.sleep(3)

    # ②b 兜底：`bootstrap` 失败时退回老的 `load -w` ✓（兼容性更好）
    _bs_rc = (out["steps"].get("bootstrap") or {}).get("rc")
    if _bs_rc != 0:
        out["steps"]["load_fallback"] = _sh(
            ["launchctl", "load", "-w", plist])
        time.sleep(3)

    # ③ 状态
    try:
        r = _run(["launchctl", "list"], 20)
        out["steps"]["launchctl_list"] = [
            ln for ln in (r.stdout or "").splitlines() if label in ln
        ] or ["(列表里没有它)"]
    except Exception as exc:                  # noqa: BLE001
        out["steps"]["launchctl_list"] = "ERR %s" % str(exc)[:100]

    # 🔴 2026-11-11 实测踩坑：原来用 `grep -i '<label最后一段>'` ✗
    #    ⇒ `com.xingguo.dsh.web` 的最后一段是 **`web`** ✗
    #    ⇒ 把所有 **WebKit 进程**都匹配进来了（webprivacyd / WebKit.GPU …）✗
    #    ⇒ 改成：先拿 `launchctl list` 里的 PID，再用 `ps -p <pid>` 精确验证 ✓
    _pid = None
    try:
        _lst = out["steps"].get("launchctl_list") or []
        if isinstance(_lst, list) and _lst:
            _f = str(_lst[0]).split()
            if _f and _f[0].isdigit():
                _pid = _f[0]
    except Exception:                         # noqa: BLE001
        _pid = None
    if _pid:
        try:
            r = _run(["ps", "-p", _pid, "-o", "pid,etime,command"], 20)
            _lns = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
            out["steps"]["processes"] = _lns[1:] or ["(ps 无输出)"]
        except Exception as exc:              # noqa: BLE001
            out["steps"]["processes"] = "ERR %s" % str(exc)[:100]
    else:
        out["steps"]["processes"] = ["(launchctl list 里没有数字 PID ⇒ 进程未运行)"]

    # ④ 日志尾巴（dsh.web 的 token 会在这里 ✓ 打码后回）
    try:
        r = _run(["/usr/bin/plutil", "-p", plist], 15)
        m = _re.search(r'"StandardOutPath"\s*=>\s*"([^"]+)"', r.stdout or "")
        if m:
            lp = m.group(1)
            out["steps"]["log_path"] = lp
            if os.path.exists(lp):
                with open(lp, encoding="utf-8", errors="replace") as fh:
                    tail = "".join(fh.readlines()[-20:])
                # token 打码 ✓
                tail = _re.sub(r"(token=)([A-Za-z0-9_\-\.]{8})([A-Za-z0-9_\-\.]*)",
                               lambda mm: mm.group(1) + mm.group(2)
                               + "…(%d)" % (len(mm.group(2)) + len(mm.group(3))),
                               tail)
                out["steps"]["log_tail"] = tail[-1200:]
            else:
                out["steps"]["log_tail"] = "(日志文件不存在)"
    except Exception as exc:                  # noqa: BLE001
        out["steps"]["log_tail"] = "ERR %s" % str(exc)[:150]

    # 判定：两种服务都算「起来了」✓
    #   ① **常驻服务**（`KeepAlive=true`）⇒ `launchctl list` 有数字 PID ✓
    #   ② **定时任务**（`StartCalendarInterval`）⇒ 跑完立刻退出 ✓
    #      此时 `launchctl list` 是 `-\t0\t<label>`（PID 无 + 上次退出码 0）✗
    #      🔴 2026-11-18 实测踩坑：`com.xingguo.fg-evolve-verify` 是定时任务 ✗
    #         bootstrap rc=0、日志显示正常跑完（`[hypotheses.md] 状态已更新`）✓
    #         但被判 `ok:false` ⇒ 误报「服务没起来」✗
    #      ⇒ 判据补：`-` + 退出码 0 + 日志非空 ⇒ 视为成功 ✓
    _listed = out["steps"].get("launchctl_list") or []
    _pid_ok = False
    _oneshot_ok = False
    if isinstance(_listed, list) and _listed:
        _first = str(_listed[0]).split()
        if _first and _first[0].isdigit():
            _pid_ok = True
        elif (len(_first) >= 2 and _first[0] == "-" and _first[1] == "0"
              and (out["steps"].get("log_tail") or "").strip()):
            # 定时任务：跑完正常退出，且日志有内容 ⇒ 真的执行过 ✓
            _oneshot_ok = True
    out["ok"] = _pid_ok or _oneshot_ok
    if _oneshot_ok:
        out["note"] = "定时任务（StartCalendarInterval）跑完正常退出 ⇒ 视为成功"
    if not out["ok"]:
        out["hint"] = ("服务没起来 ✗ ⇒ 看 `log_tail` 的真实报错；"
                       "若日志为空，说明进程启动后立刻退出")
    return out


def _act_dsh_webauth_find(params):
    """找 dsh（DeepSeek Harness GUI）**最新生成的 web token** ✓（2026-11-10 用户要求）。

    🔴 背景：`dsh web authentication required; reopen the URL printed by dsh web.`
       而 `dsh` 是 **GUI app**（无 CLI ✗）⇒ 拿不到 stdout ✗
       ⇒ 只能从它的**数据目录**里找：`~/.dsh/sessions/`、`profiles/`、`logs/`
       ⇒ 扫最近修改的文件，grep `token` / `http://127.0.0.1` 关键字 ✓

    ⚠️ **token 值脱敏** ✓（只回前 8 位 + 长度），绝不回明文 ✗
    """
    import re as _re

    home = os.path.expanduser("~")
    base = os.path.join(home, ".dsh")
    out = {"dirs": {}, "recent_files": [], "hits": []}

    # ① 目录清单
    for sub in ("", "sessions", "profiles", "logs", "storages"):
        p = os.path.join(base, sub) if sub else base
        try:
            out["dirs"][sub or "(root)"] = sorted(os.listdir(p))[:15]
        except OSError:
            out["dirs"][sub or "(root)"] = "(不可读)"

    # ② 最近 2 小时修改的文件（最多 25 个）
    cutoff = time.time() - 7200
    files = []
    for root, _dirs, names in os.walk(base):
        for n in names:
            fp = os.path.join(root, n)
            try:
                mt = os.path.getmtime(fp)
                if mt < cutoff:
                    continue
                files.append((mt, fp, os.path.getsize(fp)))
            except OSError:
                continue
    files.sort(reverse=True)
    for mt, fp, sz in files[:25]:
        out["recent_files"].append({
            "path": os.path.relpath(fp, home),
            "age_min": int((time.time() - mt) / 60),
            "size": sz,
        })

    # ③ 在这些文件里 grep token / 本地 URL（脱敏）
    _pat_tok = _re.compile(r"(token|secret|key|auth)[\"'\s:=]+([A-Za-z0-9_\-\.]{12,})",
                           _re.I)
    _pat_url = _re.compile(r"https?://(?:127\.0\.0\.1|localhost)[:\d]*[^\s\"'<>]*")
    for mt, fp, sz in files[:25]:
        if sz > 2_000_000:                # 跳过超大文件
            continue
        try:
            txt = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        rel = os.path.relpath(fp, home)
        for m in _pat_url.finditer(txt):
            u = m.group(0)
            # 打码 query 里的敏感段
            _b, _, _q = u.partition("?")
            if _q:
                _parts = []
                for kv in _q.split("&"):
                    _k, _, _v = kv.partition("=")
                    if any(t in _k.lower() for t in
                           ("token", "key", "secret", "auth")):
                        _parts.append("%s=%s…(%d)" % (_k, _v[:8], len(_v)))
                    else:
                        _parts.append(kv)
                u = _b + "?" + "&".join(_parts)
            out["hits"].append({"file": rel, "type": "url", "value": u[:220]})
        for m in _pat_tok.finditer(txt):
            v = m.group(2)
            out["hits"].append({"file": rel, "type": m.group(1).lower(),
                                "value": "%s…(%d)" % (v[:8], len(v))})
        if len(out["hits"]) >= 40:
            break

    # ④ 找 **app 本体** ✓（2026-11-10 用户要求「更新 deepseek harness 应用」）
    #    回执里 `sessions/--Users-xingguo-Documents-deepseek-harness-default-workspace--`
    #    ⇒ 工作区在 `~/Documents/deepseek-harness/` ⇒ app 可能也在那附近 ✓
    out["app_search"] = {}
    for rel in ("Documents/deepseek-harness", "Applications",
                "Applications/Utilities", "Downloads"):
        d = os.path.join(home, rel)
        try:
            names = sorted(os.listdir(d))[:25]
            out["app_search"][rel] = [n for n in names
                                      if n.lower().endswith(".app")
                                      or "harness" in n.lower()
                                      or "deepseek" in n.lower()
                                      or "dsh" in n.lower()] or names[:12]
        except OSError:
            out["app_search"][rel] = "(不可读)"
    # 读 app 版本（Info.plist）
    for rel, names in list(out["app_search"].items()):
        if not isinstance(names, list):
            continue
        for n in names:
            if not n.lower().endswith(".app"):
                continue
            pl = os.path.join(home, rel, n, "Contents", "Info.plist")
            if not os.path.exists(pl):
                continue
            try:
                r = _run(["/usr/bin/plutil", "-p", pl], 20)
                out["app_search"]["%s 版本" % n] = (r.stdout or "")[:600]
            except Exception:             # noqa: BLE001
                pass

    out["ok"] = True
    out["hint"] = ("`hits` 里形如 `url` 的那条就是 dsh web 的鉴权地址 ✓ "
                   "（token 已脱敏）；`app_search` 里是 app 位置与版本 ✓")
    return out


def _act_dsh_web_open(params):
    """**自动打开 dsh web 的鉴权 URL** ✓（2026-11-10 用户要求「提供自动化方案」）。

    🔴 现象：`dsh web authentication required; reopen the URL printed by dsh web.`
       ⇒ 手工做法是「跑 `dsh web`，把打印的 URL 复制到浏览器」✗
       ⇒ 这里自动做：跑 → 抓 stdout 里的 URL → `open <url>` ✓

    步骤：
      ① 找 `dsh` 可执行文件（PATH / `~/.local/bin` / `/usr/local/bin` / `/opt/homebrew/bin`）
      ② `Popen(["dsh","web"])`，读前 40 行 stdout（最多 20 秒）
      ③ 正则抓第一个 `http://…` / `https://…`
      ④ `open <url>`（macOS 默认浏览器）
      ⑤ 杀掉子进程（避免它前台常驻）
    ⚠️ 回执里的 URL **token 段已脱敏** ✓（只回 host+port+前 8 位）
    """
    import re as _re
    import shutil

    exe = shutil.which("dsh")
    if not exe:
        for cand in (os.path.expanduser("~/.local/bin/dsh"),
                     "/usr/local/bin/dsh", "/opt/homebrew/bin/dsh",
                     os.path.expanduser("~/.dsh/bin/dsh")):
            if os.path.exists(cand):
                exe = cand
                break
    out = {"exe": exe, "url": None, "opened": False, "lines": []}
    if not exe:
        # 🔴 2026-11-10 第一次跑就「找不到 dsh」✗ —— 只查了 5 个固定路径 ✗
        #    ⇒ 改做**广谱搜索** ✓（不猜，靠系统自己说它在哪）
        #    ① `mdfind`（Spotlight 索引）② `~/.dsh` 下找可执行文件
        #    ③ npm 全局 bin ④ /Applications 里的 app ⑤ `which -a` 多个别名
        out["search"] = {}
        _cmds = {
            "mdfind": ["/usr/bin/mdfind", "-name", "dsh"],
            "which_all": ["/usr/bin/which", "-a", "dsh", "dsh-cli", "dshweb"],
            "npm_global": ["/bin/sh", "-c",
                           "npm root -g 2>/dev/null; npm bin -g 2>/dev/null"],
            "find_dot_dsh": ["/bin/sh", "-c",
                             "find \"$HOME/.dsh\" -maxdepth 3 -type f "
                             "-perm -u+x 2>/dev/null | head -20"],
            "apps": ["/bin/sh", "-c",
                     "ls /Applications 2>/dev/null | grep -i -E 'dsh|deepseek'"],
            "brew": ["/bin/sh", "-c",
                     "ls /opt/homebrew/bin /usr/local/bin 2>/dev/null "
                     "| grep -i dsh | head -10"],
        }
        for k, c in _cmds.items():
            try:
                r = _run(c, 25)
                out["search"][k] = ((r.stdout or "").strip()[:800] or "(空)")
            except Exception as exc:      # noqa: BLE001
                out["search"][k] = "ERR %s" % str(exc)[:100]
        # `~/.dsh` 目录结构（键名探针里已知它存在）
        try:
            d = os.path.expanduser("~/.dsh")
            out["search"]["dot_dsh_tree"] = sorted(os.listdir(d))[:20] \
                if os.path.isdir(d) else "(不存在)"
        except OSError as exc:
            out["search"]["dot_dsh_tree"] = "ERR %s" % str(exc)[:80]
        out["error"] = ("找不到 `dsh` 可执行文件 ✗ —— 已做广谱搜索，"
                        "结果见 `search` 字段；把其中非空的那几项贴给我")
        return out

    def _mask_url(u):
        """把 query 里的 token 打码 ✓（回执会进 git ✗）。"""
        try:
            base, _, q = u.partition("?")
            if not q:
                return base
            parts = []
            for kv in q.split("&"):
                k, _, v = kv.partition("=")
                if any(t in k.lower() for t in ("token", "key", "secret", "auth")):
                    parts.append("%s=%s…(%d)" % (k, v[:8], len(v)))
                else:
                    parts.append(kv)
            return base + "?" + "&".join(parts)
        except Exception:                     # noqa: BLE001
            return u[:120]

    proc = None
    try:
        proc = subprocess.Popen([exe, "web"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", cwd=ROOT)
        deadline = time.time() + 20
        url = None
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
                continue
            line = line.rstrip()
            out["lines"].append(line[:200])
            if len(out["lines"]) >= 40:
                break
            m = _re.search(r"https?://[^\s\"'<>]+", line)
            if m:
                url = m.group(0)
                break
        if url:
            out["url"] = _mask_url(url)
            try:
                r = _run(["open", url], 20)
                out["opened"] = r.returncode == 0
                if r.returncode != 0:
                    out["open_err"] = (r.stderr or "").strip()[:150]
            except Exception as exc:          # noqa: BLE001
                out["open_err"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
        else:
            out["error"] = ("`dsh web` 20 秒内没打印出 URL ✗ ⇒ "
                            "看 lines 里的原始输出定位")
    except Exception as exc:                  # noqa: BLE001
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:                 # noqa: BLE001
                try:
                    proc.kill()
                except Exception:             # noqa: BLE001
                    pass
    out["ok"] = bool(out.get("opened"))
    return out


def _act_restart_queue(params):
    """**重启任务队列** ✓（2026-11-05 用户要求）。

    🔴 为什么必须重启 ✗：
       `install_daily_plist` 只**拷贝 plist 文件** ✗ **不重启进程** ✗
       而任务队列是**常驻进程**（`state = running` ✗）
       ⇒ **新补的代理（`FG_LLM_PROXY` 等）不会生效** ✗
       ⇒ 实测：plist 里已有 `http://127.0.0.1:7890` ✓
         但进程环境里没有 ✗

    🔴 **不能直接重启** ✗：那会**立即杀掉**本进程 ⇒ 本动作**自己的结果
       写不进去** ✗ ⇒ 用 `nohup` 起一个**延迟**脚本 ✓，等 result 写完再动 ✓

    🔴 2026-11-20：**`kickstart` 不够** ✗ ——
       `kickstart -k` 重启的是**当前已加载的 job**，而那个 job 是登录时按
       **旧 plist** bootstrap 进去的 ⇒ **不会重读文件** ✗
       实测：plist 里明明写了 `PATH`，进程环境里却没有 ✗
       ⇒ 改成 `bootout` + `bootstrap`（+ enable + kickstart）✓
       · plist 不存在时**拒绝 bootout**（否则服务再也起不来 ✗）
       · bootstrap 重试 3 次，全失败退回 `load -w` ✓
       · 每步 rc 都写日志 ⇒ 下次能直接看出卡在哪 ✓

    ⚠️ 若队列里有**正在执行**的任务 ⇒ 会被杀 ✗（`delay` 参数可调 ✗）
    """
    # 🔴 2026-11-10：支持 `label` 参数 ✓ —— 原来写死 `fg-task-queue` ✗
    #    实测 `fg-realtime` 从 **10-12** 起就在无限重连（日志里 `conn=0(7475)` ✗）
    #    进程还活着（PID 707）但数据 29 天没更新 ✗ ⇒ 需要能重启它 ✓
    #    ⚠️ 白名单，不接受任意 label ✗
    # 🔴 2026-11-11：`autostart_list` 回执发现 `com.xingguo.dsh.web` 这个
    #    LaunchAgent **存在**（RunAtLoad + KeepAlive 都 true ✗）
    #    但 `running: []` ⇒ 进程没在跑 ✗
    #    ⇒ 这就是 `dsh web authentication required` 的根因 ✓
    #    ⇒ 加进白名单，可以用同一个动作把它拉起来 ✓
    label = str(params.get("label") or "com.xingguo.fg-task-queue").strip()
    if label not in LAUNCHD_LABELS:
        return {"ok": False,
                "error": "不允许的 label：`%s` ✗（白名单：%s）"
                         % (label, ", ".join(LAUNCHD_LABELS))}
    delay = int(params.get("delay") or 5)
    uid = os.getuid() if hasattr(os, "getuid") else 501
    target = "gui/%s/%s" % (uid, label)

    # 写一个延迟脚本 ✓（避免杀自己 ✗）
    # 🔴 2026-11-10：日志路径按 label 推导 ✓ —— 原来写死 `fg_task_queue.log` ✗
    #    重启 `fg-realtime` 时也写进队列日志 ⇒ 两边的日志混在一起 ✗
    _short = label.replace("com.xingguo.", "").replace("com.fg.", "")
    # ⚠️ 原来写的是 `/tmp/fg_%s.log` ✗ —— `_short` 本身已含 `fg-` 前缀，
    #    拼出来是 `/tmp/fg_fg_task_queue.log`（**永远没人看** ✗）
    #    ⇒ 直接用 `_short`，与 plist 的 `StandardOutPath` 对齐 ✓
    _log = "/tmp/%s.log" % _short.replace("-", "_").replace(".", "_")
    sh = os.path.join(ROOT, "dist", "_restart_%s.sh" % _short.replace("-", "_"))
    os.makedirs(os.path.dirname(sh), exist_ok=True)
    #: plist 真身（`install_daily_plist` 拷过去的那份）✓
    dst = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                       label + ".plist")
    domain = "gui/%s" % uid
    with open(sh, "w", encoding="utf-8") as f:
        f.write(
            "#!/bin/bash\n"
            "# 🔴 2026-11-20：`kickstart` **不重读 plist** ✗ —— job 是登录时按旧\n"
            "#   plist bootstrap 进去的，改了文件再 kickstart 还是旧环境 ✗\n"
            "#   （实测：plist 里明明有 PATH，进程环境里却没有 ✗）\n"
            "#   ⇒ 必须 bootout + bootstrap 才会重新读 plist ✓\n"
            "LOG=%s\n"
            "DST=%s\n"
            "echo \"[restart] $(date '+%%F %%T') start %s\" >> \"$LOG\"\n"
            "if [ ! -f \"$DST\" ]; then\n"
            "  echo \"[restart] 放弃：plist 不存在 $DST ✗\" >> \"$LOG\"\n"
            "  exit 1\n"
            "fi\n"
            "sleep %d\n"
            "launchctl bootout %s >> \"$LOG\" 2>&1\n"
            "echo \"[restart] bootout rc=$?\" >> \"$LOG\"\n"
            "for i in 1 2 3; do\n"
            "  launchctl bootstrap %s \"$DST\" >> \"$LOG\" 2>&1\n"
            "  rc=$?\n"
            "  echo \"[restart] bootstrap try $i rc=$rc\" >> \"$LOG\"\n"
            "  [ $rc -eq 0 ] && break\n"
            "  sleep 2\n"
            "done\n"
            "if [ $rc -ne 0 ]; then\n"
            "  echo \"[restart] bootstrap 三次都失败 ⇒ 退回 load -w ✗\" >> \"$LOG\"\n"
            "  launchctl load -w \"$DST\" >> \"$LOG\" 2>&1\n"
            "fi\n"
            "launchctl enable %s >> \"$LOG\" 2>&1\n"
            "launchctl kickstart -k %s >> \"$LOG\" 2>&1\n"
            "echo \"[restart] kickstart rc=$?\" >> \"$LOG\"\n"
            "launchctl print %s 2>/dev/null | head -3 >> \"$LOG\"\n"
            % (_log, dst, label, delay, target, domain, target, target, target))
    os.chmod(sh, 0o755)

    # 记录重启前的环境 ✓
    before = {k: (os.environ.get(k) or "")
              for k in ("FG_LLM_PROXY", "HTTP_PROXY", "HTTPS_PROXY")}

    try:
        subprocess.Popen(["nohup", "bash", sh],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
        ok, err = True, ""
    except Exception as exc:                # noqa: BLE001
        ok, err = False, "%s: %s" % (type(exc).__name__, str(exc)[:150])

    return {"ok": ok, "error": err, "label": label, "target": target,
            "delay_seconds": delay, "script": os.path.relpath(sh, ROOT),
            "env_before_restart": before,
            "note": "⚠️ %d 秒后 bootout+bootstrap 重启 ✓ —— **只有这条路"
                    "会重读 plist** ✓（`kickstart` 用的是已加载的旧 job ✗）；"
                    "每步 rc 见日志尾部；"
                    "⚠️ 队列里正在跑的任务会被杀 ✗" % delay}


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
        r = _run(["bash", script], 180)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-900:], "stderr": (r.stderr or "")[-400:]}


def _act_restart_dashboard(params):
    """重启仪表盘 launchd 服务并自检首页 ✓（2026-11-06）。

    🔴 为什么必须重启：**刷新页面不会重载 Python 模块** ✗ ——
    代码入库后不重启，进程里还是旧模块（实测：修完 complex 仍报同一个错 ✗）。
    重启后**再探一次首页** ✓ 才算验证通过（只 `kickstart` 不看结果等于没验 ✗）。
    """
    import subprocess as _sp
    import time as _t
    import urllib.error as _ue
    import urllib.request as _u

    label = str(params.get("label") or "com.xingguo.fg-dashboard")
    url = str(params.get("url") or "http://127.0.0.1:8000/")
    uid = os.getuid() if hasattr(os, "getuid") else 501
    try:
        r = _run(["launchctl", "kickstart", "-k", "gui/%s/%s" % (uid, label)], 30)
    except (OSError, _sp.SubprocessError) as exc:
        return {"ok": False, "reason": "launchctl 失败：%s" % exc}
    out = {"ok": r.returncode == 0, "rc": r.returncode,
           "stderr": (r.stderr or "").strip()[-300:]}

    # 冷启动要跑一次全量渲染（实测近 1 分钟）⇒ 最多等 90 秒
    for _ in range(45):
        _t.sleep(2)
        try:
            with _u.urlopen(url, timeout=15) as resp:
                body = resp.read(4000).decode("utf-8", "replace")
                out.update(http=resp.status, render_error="渲染失败" in body,
                           html_len=len(body))
                return out
        except _ue.HTTPError as exc:          # 500 也算「起来了」，要拿错误正文
            body = exc.read(4000).decode("utf-8", "replace")
            out.update(http=exc.code, render_error="渲染失败" in body,
                       body=body[:1200])
            return out
        except Exception as exc:              # noqa: BLE001 —— 还没起来，继续等
            out["last_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    out["ok"] = False
    return out


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

ACTIONS = {
    "plist_path_append": _act_plist_path_append,
    "autostart_list": _act_autostart_list,
    "dsh_web_diag": _act_dsh_web_diag,
    "dsh_web_launch": _act_dsh_web_launch,
    "dsh_web_open": _act_dsh_web_open,
    "dsh_webauth_find": _act_dsh_webauth_find,
    "service_bootstrap": _act_service_bootstrap,
    "restart_queue": _act_restart_queue,
    "restart_dashboard": _act_restart_dashboard,
    "install_evolve_tasks": _act_install_evolve_tasks,
    "install_daily_plist": _act_install_daily_plist,
}
