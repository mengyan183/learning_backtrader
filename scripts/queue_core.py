# -*- coding: utf-8 -*-
"""任务队列的**动作侧基础设施** ✓ —— 从 `run_task_queue.py`（6400 行）抽出的第一批。

【为什么单独一个模块】
  ① 77 个 action 都要用这些（跑子进程 / 路径校验 / 白名单加载）✗
  ② 下一步要把 action 按 8 个包切开 ⇒ 包和调度器必须有共同底座，
     否则互相 import 成环 ✗
  ③ 本模块**不持有队列状态** ✓ —— `QUEUE` / `ACTIONS` / `run_once` / flock
     全部留在调度器里 ✓（2026-11-19 用户裁定：串行模型与注册表不动）

⚠️ 本模块**不吞异常** ✗ —— 超时/失败的语义由调用点决定 ✓
"""
import contextlib
import json
import os
import subprocess



ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 🔴 外置白名单目录 ✓（2026-11-19 用户裁定：加脚本 = 加文件，零改 py）
#   · `*.py`               ⇒ `run_script` 可跑的脚本名（**文件名即白名单**）
#   · `tail_logs.json`     ⇒ `daily_log_tail` 可读的日志（每轮重读，不用重启 ✓）
#   · `task_outputs.json`  ⇒ `_git_commit` 会提交的产物目录/文件
#   ⚠️ 加载器**只读**且**拒绝 `..`** ✗ —— 否则等于把 2026-11-19 刚堵的
#      路径逃逸洞（见 `safe_rel`）重新开一遍 ✗


ALLOW_DIR = os.path.join(ROOT, "scripts", "queue_allow")

#: `read_tail` / `inspect_csv` 允许读的路径前缀 ✓（**禁 `Data/accounts.csv`
#: 和 `Data/positions.csv`** —— 那两个含账户/持仓明细，不该进任务回执 ✗✗）
#: 🔴 2026-11-19：放 core 是因为 `data` 包和调度器（`read_tail`）都要用 ✓


READ_ALLOW = ("Data/raw/", "Data/features.csv", "evolution/",
              "docs/task-queue/")




def run(cmd, timeout, cwd=ROOT, env=None):
    """跑子进程并**统一捕获/解码** ✓ —— 原来散落 87 处的 `subprocess.run(...)` 收敛到这里。

    · `cwd` 默认 `ROOT` ✓（plist 的 `WorkingDirectory` 就是仓库根 ⇒ 与手动跑一致）
    · `encoding="utf-8", errors="replace"` ⇒ launchd 的 locale 可能是 C/POSIX ✗，
      不加会因中文输出 `UnicodeDecodeError` 崩掉 ✓
    · 🔴 **不吞异常** ✗ —— `TimeoutExpired` / `SubprocessError` / `OSError` 的
      处理每个调用点都不一样，必须留在原地 ✓
    """
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=timeout, env=env)




def safe_rel(rel, allow):
    """把任务参数里的相对路径**锁死在白名单目录内** ✓。

    🔴 2026-11-19 安全评审发现（**唯一「出事不可回滚」的问题**）✗
      原来的检查是 `rel.startswith(_READ_ALLOW)` ✗
      但 `"Data/raw/../../.env".startswith("Data/raw/")` 是 **True** ✗
      ⇒ `git_commit` 的 `files` 参数传 `"evolution/../.env"` 就能让
        `.env`（含 API key）被 `git add` + `push` 到 **gitee** ✗
      ⇒ 而飞书群里**任何人**都能发起任务（只要知道格式）✗
      ⇒ 事后只能改密钥，git 历史无法撤回 ✗

    ✅ 三重校验：
      ① 显式拒绝 `..` 路径段（`split` 后逐段比对，不靠字符串匹配）
      ② `realpath` 解析后再比前缀（防符号链接绕过）
      ③ 必须落在某个白名单目录**之内**（`+ os.sep` 防止 `Data/raw-evil`）

    返回**绝对路径**；不合法抛 `ValueError`（调用方转成 `{"ok": False}`）✓
    """
    rel = str(rel or "").strip().lstrip("/").replace("\\", "/")
    if not rel:
        raise ValueError("路径为空")
    if ".." in rel.split("/"):
        raise ValueError("路径含 `..`：%s" % rel)
    full = os.path.realpath(os.path.join(ROOT, rel.replace("/", os.sep)))
    for a in allow:
        base = os.path.realpath(os.path.join(ROOT, a))
        if full == base or full.startswith(base + os.sep):
            return full
    raise ValueError("路径不在白名单 %s 内：%s" % (list(allow), rel))




def allow_json(name):
    """读 `scripts/queue_allow/<name>` ✓ —— 每轮重读 ⇒ 改白名单不用重启队列 ✓。"""
    with open(os.path.join(ALLOW_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)




def rel_ok(rel):
    """白名单条目必须是**仓库内相对路径** ✓ —— 绝对路径 / `..` / 空 一律拒绝 ✗。"""
    rel = str(rel or "").strip()
    if (not rel or os.path.isabs(rel) or rel.startswith(("/", "\\"))
            or ".." in rel.replace("\\", "/").split("/")):
        raise ValueError("白名单条目非法：%r" % rel)
    return rel




def script_allowed():
    """扫 `scripts/queue_allow/*.py` 得到可跑脚本名集合 ✓（文件名即白名单）。"""
    try:
        return {e.name for e in os.scandir(ALLOW_DIR)
                if e.is_file() and e.name.endswith(".py")}
    except OSError:
        return set()




def tail_logs():
    """读 `tail_logs.json` ⇒ {名字: 绝对路径} ✓ —— 每轮重读 ✓。

    ⚠️ 只接受**非空、不含 `..`** 的路径 ✗（绝对路径必须支持：`/tmp/fg_daily.log`）
    """
    out = {}
    for name, rel in allow_json("tail_logs.json").items():
        rel = str(rel or "").strip()
        if not rel or ".." in rel.replace("\\", "/").split("/"):
            raise ValueError("tail_logs.json 条目非法：%s=%r" % (name, rel))
        # 以 `/` 开头即绝对路径 ✓（Windows 的 `os.path.isabs("/tmp/x")` 是 False ✗）
        abs_ = rel.startswith("/") or os.path.isabs(rel)
        out[str(name)] = rel if abs_ else os.path.join(ROOT, rel)
    return out




def task_outputs():
    """读 `task_outputs.json` ⇒ `(dirs, files)` ✓。

    ⚠️ 只接受**仓库内相对路径** ✗ —— `_git_commit` 拿它做 `git add`，
       绝对路径 / `..` 会越出仓库（同 2026-11-19 `safe_rel` 那类洞）
    """
    data = allow_json("task_outputs.json")
    return ([rel_ok(d) for d in data.get("dirs") or []],
            [rel_ok(f) for f in data.get("files") or []])




def _find_bsk_bin():
    """**自动探测 `bsk` 路径** ✓（2026-11-05）。

    🔴 为什么不能直接用 `"bsk"` ✗：
       launchd 的 `PATH` **不含 `~/.local/bin`** ✗
       实测 `fetch_fedwatch_bsk.py` 在 Mac 上报
         `session_start rc=-1  **找不到 bsk** ✗`
       而 bsk 确实装着 ✓
    """
    env = os.environ.get("FG_BSK")
    if env and os.path.exists(env):
        return env
    import shutil
    w = shutil.which("bsk")
    if w:
        return w
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, ".local", "bin", "bsk"),
        "/opt/homebrew/bin/bsk",
        "/usr/local/bin/bsk",
        os.path.join(home, ".npm-global", "bin", "bsk"),
    ]
    import glob as _g
    cands += sorted(_g.glob(os.path.join(
        home, "Library", "Python", "*", "bin", "bsk")), reverse=True)
    # 🔴 2026-11-11：补 `~/opt/node*/bin/bsk` ✓ ——
    #    `dsh_web_diag` 回执显示 dsh 在 `/Users/xingguo/opt/node24/bin/dsh` ✗
    #    ⇒ 用户用 `~/opt/nodeXX/` 管 node ⇒ **npm 全局包也装在那** ✓
    #    （之前 5 个候选路径全不中，就是漏了这一处 ✗）
    cands += sorted(_g.glob(os.path.join(home, "opt", "node*", "bin", "bsk")),
                    reverse=True)
    # 🔴 2026-11-11：`zsh -lc` 是**非交互登录 shell，不 source `.zshrc`** ✗
    #    （只 source `.zshenv` / `.zprofile` / `.zlogin`）
    #    而 bsk 常挂在 `.zshrc` 配的 PATH 上 ✗ ⇒ 必须**显式 source** ✓
    try:
        r = run(["/bin/zsh", "-lc",
                  "source ~/.zshrc 2>/dev/null; command -v bsk"], 20)
        for ln in (r.stdout or "").splitlines():
            ln = ln.strip()
            if ln and os.path.isfile(ln) and os.access(ln, os.X_OK):
                cands.insert(0, ln)
                break
    except Exception:                     # noqa: BLE001
        pass
    for c in cands:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return "bsk"




BSK_BIN = _find_bsk_bin()


# ---------------------------------------------------------
# 环境变量作用域（2026-11-19 第十二轮从调度器上移）
# ---------------------------------------------------------
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


BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "PYTHONPATH",
             "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE",
             "USER", "LOGNAME", "SHELL", "TERM", "SSH_AUTH_SOCK")




def env_for(action):
    """该动作可见的环境变量 ✓（白名单 + 声明）"""
    env = {k: os.environ[k] for k in BASE_ENV if k in os.environ}
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


def scoped_env(action):
    """执行期间把 `os.environ` **收窄**成该动作的白名单 ✓。

    这样所有 `subprocess.run(...)`（继承 `os.environ`）都自动受限 ✓
    —— 一处改造，26 个调用点全覆盖 ✓（逐个改容易漏 ✗）
    """
    saved = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(env_for(action))
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


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
