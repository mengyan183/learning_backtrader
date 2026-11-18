# -*- coding: utf-8 -*-
"""用 `bsk` 把投递包**自动**逐条发进飞书 —— 代替手工发 58 条。

【为什么需要】
公司网络只放行飞书**消息**（文件被 DLP 拦、云文档同步离线），
而消息上限 **1700 字符/条** ⇒ 最小可运行集要 **58 条**。
手工发 58 次 + 复制 58 次不现实，且中间错一条就得重来。

【它做什么】
    1. `bsk session start`（用 --no-focus，不打断你）
    2. 打开飞书网页版
    3. 点开你与**自己**的会话（`--chat` 指定名字）
    4. 找到输入框，逐条 `fill` + `Enter`
    5. 发完 `bsk session stop`

【⚠️ 发之前先看这个】
    --dry-run   只打印将要发的内容，不碰浏览器（**建议先跑一次**）
    每条消息都是 `###FG:包名:序号/总数###<base64>###FG:end###` 单行格式 ——
    飞书**按回车就发送**，所以格式里绝不能有换行（带了只会发出第一行）。

【用法】
    python scripts/feishu_send.py --dry-run              # 先看
    python scripts/feishu_send.py --chat 郭星            # 真发
    python scripts/feishu_send.py --chat 郭星 --start 30 # 从第 30 条续发（断了重来用）

【发完之后】
    在 Mac 上打开同一个会话 → 全选复制 → 存成一个文件 →
    python3 scripts/restore_from_base64.py <那个目录>
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402

TEXT_DIR = os.path.join(config.ROOT, "dist", "feishu", "text")

# Windows 控制台默认 GBK ⇒ 打印中文/`✓` 会崩 ✓；
# 且 stdout 重定向到文件时是**块缓冲** ✗ ⇒ 进程被中断就一个字都不留 ✗
# （2026-10-28 实测：`--limit 2` 那几次日志全空，只能靠台账反推 ✗）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


# ---------------------------------------------------- 已发台账（WT-46 / WT-48）
def _pkg_of(name):
    """从分片文件名取包名：`sync_1019s-t003.txt` → `sync_1019s` ✓。"""
    m = re.match(r"^(.+?)-t\d+\.txt$", name or "")
    return m.group(1) if m else ""


def _ledger_path(pkg):
    return os.path.join(TEXT_DIR, "%s.sent" % pkg)


def _ledger_add(name, index, total, ok=True):
    """**发送成功即落台账** ✓ —— 与 stdout 无关。

    🔴 2026-10-31 加 `ok` 参数 ✗：原来**只在成功时写** ✗ ⇒
    失败时台账里**一片空白** ⇒ `--sent-status` 只报「无记录」✗，
    看不出「试过但失败」还是「从没试过」✗ —— 这就是
    `sync_1028er` 连试 4 次都像「无记录」的原因 ✓。
    ⇒ 失败也写一行 `FAIL` ✓，让重试历史可见 ✓。

    动机（2026-10-19，WT-46）：本机 hook 会在 5s 截断 stdout ✗ ⇒ 只能从日志数
    「已发」行 ✗ ⇒ 数不到就误判「缺片」✗ ⇒ 盲补（当晚 5 次 ✗）。
    台账落盘 ⇒ 补发前 `--sent-status` 一查即可 ✓，不再靠猜 ✗。
    """
    pkg = _pkg_of(name)
    if not pkg:
        return
    try:
        with open(_ledger_path(pkg), "a", encoding="utf-8") as fh:
            fh.write("%d/%d\t%s\t%s\t%s\n"
                     % (index, total, name,
                        time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "OK" if ok else "FAIL"))
    except OSError as exc:          # 台账失败**不得**影响发送 ✓
        print("  [warn] 台账写入失败：%s" % exc)


def sent_status(pkg):
    """打印某包已发/缺片（补发前必查 ✓）。返回缺片序号列表。"""
    path = _ledger_path(pkg)
    done, fails = {}, {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                parts = ln.rstrip("\n").split("\t")
                if len(parts) >= 2 and "/" in parts[0]:
                    idx, tot = parts[0].split("/", 1)
                    try:
                        i, t = int(idx), int(tot)
                    except ValueError:
                        continue
                    # 旧格式没有第 4 列 ⇒ 视为 OK ✓（向后兼容）
                    st = parts[3] if len(parts) >= 4 else "OK"
                    if st == "OK":
                        done[i] = t
                    else:
                        fails[i] = fails.get(i, 0) + 1
    if not done:
        if fails:
            # 🔴 2026-10-31：失败也要看得见 ✗ —— 原来失败不写台账 ⇒
            # 连试 4 次都显示「无记录」，看不出「试过但失败」✗
            print("%s：**全部失败** ✗（试过 %d 次：%s）"
                  "⇒ 建议**换个包名重新打包**再发 ✓（同一包名重试常常无效 ✗）"
                  % (pkg, sum(fails.values()),
                     "、".join("第%d片×%d" % (k, v)
                               for k, v in sorted(fails.items()))))
        else:
            print("%s：台账**无记录** ✗ ⇒ 一片都未确认发出"
                  "（不要盲目补发 ✓，先看发送日志）" % pkg)
        return list(range(1, 1000))
    total = max(done.values())
    missing = [i for i in range(1, total + 1) if i not in done]
    extra = ""
    if fails:
        extra = "；另有失败记录 %s" % "、".join(
            "第%d片×%d" % (k, v) for k, v in sorted(fails.items()))
    print("%s：已发 **%d/%d** 片；缺片 %s%s"
          % (pkg, len(done), total,
             missing if missing else "**无** ✓", extra))
    return missing
def _lock_path():
    return os.path.join(TEXT_DIR, ".feishu_send.lock")


def _acquire_lock():
    """拿**发送锁**；已有进程在发 ⇒ SystemExit（**不抢** ✗）。返回 fd。

    🔴 根因（2026-10-28 实测）：两个发送进程并发时，后启动的那个在 `main()` 里
    先跑 `bsk.reap()`（清残留会话）✗ ⇒ 把前一个进程正在用的 bsk 会话**踢掉** ✗
    ⇒ 前一批发到第 2 片时 `observe()` 失败/挂死 ⇒ 只发出 1 片就中止 ✗
    （`--limit 2` 连续四次都只发 1 片，日志还全空 ✗）。
    ⇒ 串行化：拿不到锁就明确报错，绝不并发 ✓。
    """
    os.makedirs(TEXT_DIR, exist_ok=True)
    fd = os.open(_lock_path(), os.O_CREAT | os.O_RDWR)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise SystemExit(
            "❌ 另一个 `feishu_send.py` 正在发送 ⇒ 本次退出 ✓\n"
            "   并发发送会让后启动的进程 reap 掉前一个的 bsk 会话 ✗\n"
            "   ⇒ 前一批只发出前几片就中止（2026-10-28 实测 `--limit 2` 只发 1 片 ✗）。\n"
            "   等它跑完再发；查进度用 `--sent-status <包>` ✓")
    return fd


def _release_lock(fd):
    """关 fd 即释放锁 ✓（失败不影响发送结果 ✓）。"""
    try:
        os.close(fd)
    except OSError:
        pass


FEISHU_URL = "https://www.feishu.cn/messenger/"

#: 🔴 2026-11-13：上次用的 bsk 会话 id（用于**复用常驻会话** ✓）
#:    放临时目录 ⇒ 重启电脑自动失效 ✓（失效后走新建分支，安全）
_SID_FILE = Path(tempfile.gettempdir()) / "fg_bsk_session.txt"
TEXTBOX_RE = re.compile(r"(@e\d+)\s+textbox")
#: 飞书富文本编辑器的 CSS 选择器 ✓（bsk 0.4.2 的 VOM 不暴露 textbox ⇒ 只能按选择器填）
EDITOR_SELECTOR = 'div[contenteditable="true"]'
BUTTON_RE = re.compile(r"(@e\d+)\s+button\s+\"([^\"]*)\"")


class Bsk:
    """`bsk` CLI 的薄封装。"""

    #: 需要 `--context` 的 DOM 动作 ✓（2026-11-11 bsk 0.2.0 → 0.4.2 引入
    #: `cooperate` 机制后，这些动作**必须**带 context，否则报
    #: `shared page control or observation changed` ✗）
    _CTX_ACTIONS = ("click", "fill", "press", "type", "extract",
                    "reload", "snapshot", "get-html", "screenshot",
                    # 🔴 2026-11-17：0.5.0 下**复用会话**时 `navigate` 报
                    #   `error: this action needs an explicit current observation`
                    #   ⇒ 触发「复用会话失效」重建 ⇒ 新 tab ⇒ 又要人工点开会话 ✗
                    #   ⇒ navigate 也必须带 context ✓（新会话首次 navigate 有
                    #     初始 observation，带 context 同样可用 ✓）
                    "navigate",
                    # 🔴 2026-11-17：`evaluate --unverified` **仍要控制权 context** ✗
                    #   （`--unverified` 只跳过页面比对，控制权/tab 归属照查）
                    #   ⇒ 报 `This action requires a valid control context`
                    "evaluate")

    def __init__(self, session=None, quiet=True):
        self.session = session
        self.quiet = quiet
        self.ctx = None

    def run(self, *args, check=True, with_session=True):
        """跑一条 `bsk` 子命令 ✓。

        `with_session=False` ⇒ **不追加** `--session` ✗ ——
        会话生命周期类命令（`session start/stop`）自己带位置参数，
        再叠 `--session` 会非法 ✗。
        """
        cmd = ["bsk"] + list(args)
        if with_session and self.session:
            cmd += ["--session", self.session]
        # 🔴 2026-11-11：DOM 动作要带 `--context` ✓（见 `sync()`）
        if (with_session and self.ctx and args
                and args[0] in self._CTX_ACTIONS):
            cmd += ["--context", self.ctx]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if check and proc.returncode != 0:
            raise RuntimeError("bsk %s 失败：%s"
                               % (" ".join(args), (proc.stderr or proc.stdout).strip()))
        return proc.stdout or ""

    # 🔴 2026-11-17：**bsk 0.5.0 的 click 在这台机器上不可用** ✗
    #    现象：`error: the browser's native input clock could not be calibrated`
    #          `details: Native input clock calibration failed: Cannot attach to this target`
    #    已排除（实测）：协议（doctor 全绿 / EXT 0.5.0 / protocol 1.9）、
    #      `--no-focus`（改抢焦点无效）、daemon 重启（无效）、
    #      扩展重连 + 重配对（无效）、`open --focus` 前台窗口（无效）
    #    ⇒ 但 `evaluate` 可用 ✓（需一次性 `--observation`）
    #    ⇒ 用 JS 派发**完整事件序列**才能触发飞书 React 合成事件 ✓
    #      （只调 `el.click()` 实测无效：会话点不开、输入框不出现 ✗）
    def click_js(self, text, selector="[draggable]"):
        """按可见文本用 JS 点击（绕过 native input ✓）。

        取**文本最短**的匹配项 ✓ —— 飞书列表项是嵌套的，
        外层容器 textContent 会带上整条消息摘要，最短的才是列表项本身。

        🔴 必须 `--unverified` ✗（2026-11-17 实测）：
          用 `--observation <sync 返回的 id>` 会报
            `error: this action needs an explicit current observation`
            `details: The strict observation changed before this action`
          —— 飞书消息列表**一直在变**（新消息/滚动），sync 与 evaluate
          之间页面就变了 ⇒ 严格观测永远不通过 ✗
          `--unverified` 不比对页面，但控制权/文档/tab 归属仍校验 ✓
        """
        expr = (
            "(()=>{"
            "const m=[...document.querySelectorAll(%r)]"
            ".filter(n=>n.textContent.includes(%r));"
            "if(m.length===0)return 'nf';"
            "const el=m.sort((a,b)=>a.textContent.length-b.textContent.length)[0];"
            "const o={bubbles:true,cancelable:true,view:window};"
            "['pointerdown','mousedown','pointerup','mouseup','click']"
            ".forEach(t=>el.dispatchEvent(t.startsWith('pointer')"
            "?new PointerEvent(t,o):new MouseEvent(t,o)));"
            "return 'ok'})()" % (selector, text)
        )
        return self.run("evaluate", expr, "--unverified").strip()

    def reap(self):
        """清掉**所有残留会话** ✓（`bsk session stop --all` ✓）。

        🔴 为什么必须有 ✗（2026-10-27 实测）：泄漏的会话会让
        `bsk observe` **挂起不返回** ✗ —— 残留 10+ 个之后，每次发送都卡到
        被外部中断 ✗，表现为「发送环节不稳」✗。每次发之前先收割 ✓。
        """
        self.run("session", "stop", "--all", check=False, with_session=False)

    # 🔴 2026-11-17：**默认改成抢焦点** ✗（原来 `no_focus=True`）
    #    bsk 0.5.0 起 `click` 走**原生输入时钟校准** ⇒ 要求窗口在前台 ✓
    #    `--no-focus` 把窗口留在后台 ⇒ 实测报
    #      `the browser's native input clock could not be calibrated`
    #      `Native input clock calibration failed: Cannot attach to this target`
    #    ⇒ 这不是协议问题（`bsk doctor` 全绿、EXT 0.5.0 / protocol 1.9 ✓）
    def _pick_browser(self, name):
        """从 `bsk browsers` 里挑 BROWSER 列匹配 `name` 的 instance id ✓。

        输出形如：
            INSTANCE  BROWSER           EXT    LABEL  SESSIONS
            f155f0b7  chrome 157.0.0.0  0.5.0  -      0
        ⇒ 取第 1 列；找不到返回 None（让 bsk 自己选）✓
        """
        try:
            out = self.run("browsers", check=False, with_session=False)
        except RuntimeError:
            return None
        for line in (out or "").splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 2 and cols[1].lower().startswith(name.lower()):
                return cols[0]
        return None

    def start(self, no_focus=False):
        args = ["session", "start"]
        # 🔴 2026-11-18：**必须指定 Chrome** ✗（默认会挑 Edge）
        #    Edge 157 的 `chrome.debugger.attach` 坏了 ⇒ `click`/`press` 报
        #      `native input clock could not be calibrated`
        #    Chrome 157 完全正常（实测 `click ok` / `fill ok` / `press ok`）✓
        #    ⚠️ `--browser chrome` **不行** ✗ —— 报
        #      `no online browser matches the requested selector`
        #      它要的是 **instance id**（`f155f0b7`），且重连后会变 ✗
        #    ⇒ 自动从 `bsk browsers` 解析 chrome 的 instance id ✓
        browser = os.environ.get("BSK_BROWSER") or self._pick_browser("chrome")
        if browser:
            args += ["--browser", browser]
        if no_focus:
            args.append("--no-focus")
        # 会话创建命令不叠加 `--session` ✗（此时还没有会话 ✓）
        out = self.run(*args, with_session=False)
        self.session = out.strip().splitlines()[-1].strip()
        return self.session

    # ── 🔴 2026-11-13 用户要求：**复用常驻会话，不要每次重新探索** ──
    #    问题：`main()` 每次都 `reap()` + `start()` + `navigate()`
    #      ⇒ 新标签页 + 飞书 SPA **冷加载** ✗
    #      ⇒ 今天 15+ 个包失败 5 次（33%）✗
    #    方案：把上次的 sid 存到临时文件，下次先 `session list` 查它还活着吗
    #      ⇒ 活着就**直接复用**（跳过 reap/start/navigate）✓
    #      ⇒ 死了才新建（此时才 reap）✓
    #    为什么不是「常驻服务」：`bsk` 本身是**CLI + daemon** 架构 ✗
    #      浏览器会话本来就活在 daemon 里 ✓ 只是我们每次都把它杀了 ✗
    #      ⇒ 复用 sid 就等价于「常驻」✓ 不需要额外写服务 ✓
    def reuse_or_start(self):
        """优先复用上次的会话 ⇒ 返回 `(sid, reused)` ✓"""
        old = ""
        try:
            old = _SID_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        if old:
            out = self.run("session", "list",
                           with_session=False, check=False)
            if old in (out or ""):
                self.session = old
                return old, True
        # 没有可复用的 ⇒ 先收割残留，再新建 ✓
        self.reap()
        sid = self.start()
        try:
            _SID_FILE.write_text(sid, encoding="utf-8")
        except OSError:
            pass
        return sid, False

    def stop(self):
        """停掉本会话 ✓。

        🔴 **曾经的 bug** ✗：这里调 `self.run("session", "stop", sid)`，
        而 `run()` 会再追加 `--session sid` ✗ ⇒ 命令变成
        `bsk session stop <sid> --session <sid>` ✗ ⇒ 非法 ⇒
        `check=False` 把错误吞掉 ✗ ⇒ **会话永远停不掉** ✗ ⇒
        每次发送泄漏一个会话 ✗ ⇒ 累积后 `observe` 全面挂起 ✗。
        （2026-10-27 实测残留 10+ 会话后发送彻底不动 ✗）
        """
        if self.session:
            sid = self.session
            try:
                self.run("session", "stop", sid, check=False, with_session=False)
            finally:
                self.session = None

    def sync(self):
        """`cooperate sync` → `(context_id, vom_text)` ✓（bsk ≥0.4.2 必需）。

        🔴 2026-11-11 升级 bsk `0.2.0` → `0.4.2` 后实测：
           `bsk click @e8` 报
             `error: shared page control or observation changed`
             `details: This action requires the context returned by the latest cooperate sync`
           ⇒ DOM 动作必须带 `--context` ✓；
           **且 ref 必须来自同一次 sync** ✗ ——
           拿 `observe` 的 ref 配新 context 会报
             `The action target was removed from its document` ✗
           ⇒ 所以**统一用 `sync()` 取代 `observe()`**：它同时给 context 和 refs ✓
        """
        raw = self.run("cooperate", "sync", check=False)
        ctx = None
        m = re.search(r'"context_id"\s*:\s*"([^"]+)"', raw or "")
        if m:
            ctx = m.group(1)
        self.ctx = ctx
        txt = ""
        try:
            d = json.loads(raw)
            txt = ((d.get("observation") or {}).get("text") or "")
        except (json.JSONDecodeError, AttributeError, TypeError):
            mt = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw or "")
            if mt:
                try:
                    txt = json.loads('"%s"' % mt.group(1))
                except json.JSONDecodeError:
                    txt = mt.group(1)
        return ctx, txt

    def observe(self):
        """返回 VOM 文本（**只读** ✓ 不能拿它的 ref 去 click ✗，见 `sync()`）。"""
        raw = self.run("observe", "--json")
        try:
            return json.loads(raw).get("text", raw)
        except json.JSONDecodeError:
            return raw

    def find_textbox(self, vom):
        """找输入框 ✓ —— 返回 `@eN` ref 或 **CSS 选择器**。

        🔴 2026-11-11 升级 bsk 0.4.2 后实测（用户要求「把飞书发送走通」）：
           ① 新版 VOM **不再把飞书编辑器标成 `textbox`** ✗
              它标成 `button "发送给 海外投资助手"`（placeholder 当文案）✗
           ② 真正的编辑器是 `div[contenteditable="true"]`
              （class `zone-container editor-kit-container innerdocbody`）✓
           ③ `fill @eN` 报 `element DIV not fillable` ✗
              但 `fill --selector 'div[contenteditable="true"]'` **能填进去** ✓
              （`rc=3 could not be confirmed` 只是确认失败，实际成功 ✗）
           ④ 必须**先点会话打开聊天** ✗ —— 只看欢迎页时编辑器不存在 ✗
              （判据：VOM 里出现 `发送给` 或 `Shift + Enter 换行` ✓）
        """
        m = TEXTBOX_RE.search(vom)
        if m:
            return m.group(1)
        # 新版：聊天已打开（有输入框的 placeholder / 换行提示）⇒ 用选择器 ✓
        if "发送给" in vom or "Shift + Enter" in vom:
            return EDITOR_SELECTOR
        # 🔴 2026-11-17：**`发送给` 会消失** ✗ —— 发完一条消息后 VOM 里
        #    那行不再出现（实测），但编辑器**仍在**
        #    （`div.zone-container.editor-kit-container.innerdocbody` ✓）
        #    ⇒ 只用 VOM 判断会误报「找不到输入框」✗
        #    ⇒ 兜底直接问 DOM：`evaluate` 可用（`--unverified` ✓）
        try:
            out = self.run("evaluate",
                           "document.querySelectorAll("
                           "'div[contenteditable=true]').length", "--unverified")
            if out.strip().isdigit() and int(out.strip()) > 0:
                return EDITOR_SELECTOR
        except RuntimeError:
            pass
        return None

    def fill(self, target, text):
        """填文本 ✓。

        🔴 2026-11-17：**0.5.0 的 `fill` 对飞书无效** ✗（用户实测：一条都没收到）
          `fill` 返回 `fill ok length=14 actual_value="..."`，
          VOM 里也能看到内容 ⇒ 但飞书是 **React 受控组件** ✗
          ⇒ 它只改了 DOM，React state 仍是空 ⇒ `press Enter` 不发消息 ✗
          ⇒ 随后页面重渲染把 DOM 内容也清掉 ⇒ 我的「输入框已清空」判据
            误判成「发送成功」✗（教训：清空 ≠ 发出）
          0.5.0 还移除了 `type` 子命令（`error: unrecognized subcommand`）✗

        ✅ 2026-11-18：**换 Chrome 后原生 fill 恢复正常** ✓
          实测 `fill --selector 'div[contenteditable=true]' --value 'X'`
            → `fill ok ... actual_value="X"` ✓ 且 `press Enter` 真发出 ✓
          ⇒ 恢复原生实现；`execCommand` 只在 evaluate 可用时作为备用
        """
        if str(target).startswith("@"):
            return self.run("fill", target, "--value", text, check=False)
        return self.run("fill", "--selector", target, "--value", text,
                        check=False)

    def press(self, key, target=None):
        """按键 ✓ —— `target` 同上（`@eN` → `--ref`；否则 → `--selector`）"""
        args = ["press", key]
        if target:
            if str(target).startswith("@"):
                args += ["--ref", target]
            else:
                args += ["--selector", target]
        return self.run(*args, check=False)

    def find_chat(self, vom, name):
        """找会话列表里匹配 `name` 的那个条目。"""
        for ref, label in BUTTON_RE.findall(vom):
            if name in label:
                return ref, label
        return None, None


def _chunks():
    """按包名、序号排好的分片（`-tNNN.txt`）。"""
    files = sorted(glob.glob(os.path.join(TEXT_DIR, "*-t*.txt")))
    return [(os.path.basename(f), open(f, encoding="ascii").read().strip())
            for f in files]


def _sort_key(name):
    """`minimal-t007.txt` -> `("minimal", 7)`，保证按数字序发。"""
    stem = name[:-4]
    pkg, _, num = stem.rpartition("-t")
    return pkg, int(num) if num.isdigit() else 0


def filter_chunks(chunks, pkg=None, with_bootstrap=False):
    """按包名过滤分片（`pkg` 为空 ⇒ **不过滤**，保持历史行为）。

    `chunks` 是 `(文件名, 文本)` 列表，文件名形如 `minimal-t007.txt`。
    ⚠️ `bootstrap-*`（引导脚本）只在 **`with_bootstrap=True`** 时才带上 ——
    它**首次引导必发**（§12.27-③），但每次发包都附 5 片纯噪音 ✗
    （2026-11-06 用户实测：每包必带 `###FGB:1/5`~`5/5`，Mac 侧还得再解一遍 ✗）

    背景（2026-09-29 §12.29-②）：原来 `_chunks()` 用 `glob("*-t*.txt")` 收**所有**包，
    目录里一旦混了上一轮构建留下的 keep/tests，就会**一起发出去** ✗
    —— 这正是 §12.27-⑦ 记录的待修项。
    """
    if not pkg:
        return list(chunks)
    # M6（评审）：包名写错必须**报错**，不能静默降级成「只发引导脚本」✗
    # —— 那是「静默发不全」，比报错危险；且与 `--only` 对未知包报错**不一致**。
    names = {c[0].rsplit("-t", 1)[0] for c in chunks}
    names.discard("bootstrap")
    if pkg not in names:
        raise SystemExit(
            "未知包 %r —— 目录里没有它的分片。可选：%s"
            % (pkg, ", ".join(sorted(names)) or "（目录里没有任何包）"))
    return [c for c in chunks
            if (with_bootstrap and c[0].startswith("bootstrap-"))
            or _sort_key(c[0])[0] == pkg]


def _box_has_text(vom, snippet):
    """VOM 里**输入框那一行**是否含 `snippet`。

    ⚠️ **必须只看输入框行**（`textbox`）—— 消息列表里本来就可能有同样的文本
    （**已经发过**的那条），若匹配任意行，**续发时会把「已经发过」误判成「填进去了」**
    （2026-09-28 实测踩到的形态：那条分片其实发过，但列表里也有 ⇒ 判据失效）。
    """
    for line in vom.splitlines():
        # 旧版 bsk：`@eN textbox "..."`
        # 新版 bsk：`@eN button "发送给 XXX <已输入内容>"`
        if ("textbox" in line or "发送给" in line) and snippet in line:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", default="郭星",
                    help="发给谁（会话列表里的名字；默认你自己的名字）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不碰浏览器")
    ap.add_argument("--start", type=int, default=1, help="从第几条开始（断了续发）")
    ap.add_argument("--limit", type=int, default=0,
                    help="最多发几条（0=全部）；**第一次建议 --limit 2 试跑**")
    ap.add_argument("--pause", type=float, default=0.6,
                    help="每条之间停多久（秒）；太快可能触发风控")
    ap.add_argument("--pkg", default="", metavar="PKG",
                    help="只发指定包的分片。例：`--pkg minimal`。默认发全部")
    ap.add_argument("--with-bootstrap", action="store_true",
                    help="额外带上 `bootstrap-*` 引导脚本（**只有新 Mac 首次引导才需要**；"
                         "平时发会多 5 片纯噪音）")
    ap.add_argument("--sent-status", default="", metavar="PKG",
                    help="只查该包的**已发台账**（已发/缺片），不碰浏览器。"
                         "补发前先跑这个 ✓（台账 = 每片成功即落盘 ✓，不受 stdout 截断影响）")
    args = ap.parse_args()

    if args.sent_status:
        sent_status(args.sent_status)
        return 0

    chunks = sorted(_chunks(), key=lambda kv: _sort_key(kv[0]))
    chunks = filter_chunks(chunks, args.pkg or None, args.with_bootstrap)
    if not chunks:
        raise SystemExit("❌ %s 里没有分片；先跑：\n"
                         "   python scripts/make_feishu_bundle.py --minimal --strip --text"
                         % TEXT_DIR)

    todo = chunks[args.start - 1:]
    if args.limit:
        todo = todo[:args.limit]
    print("共 %d 条，本次发第 %d~%d 条" % (len(chunks), args.start,
                                           args.start + len(todo) - 1))
    for name, text in todo[:3]:
        print("    %-22s %4d 字符  %s…" % (name, len(text), text[:48]))
    if len(todo) > 3:
        print("    …")
    print()

    over = [(n, len(t)) for n, t in chunks if len(t) > 1700]
    if over:
        raise SystemExit("❌ 有 %d 条超过飞书 1700 字符上限：%s"
                         % (len(over), over[:3]))

    if args.dry_run:
        print("（--dry-run：未碰浏览器）")
        return 0

    lock_fd = _acquire_lock()
    bsk = Bsk()
    try:
        # 🔴 2026-11-13 用户要求：**优先复用常驻会话** ✓（见 `reuse_or_start`）
        #    原来这里无条件 `reap()` + `start()` ⇒ 每次冷启动 ✗
        sid, reused = bsk.reuse_or_start()
        print("bsk 会话：%s%s" % (sid, "（复用 ✓ 跳过 navigate）" if reused else ""))

        # 🔴 2026-11-04：**必须显式给 `--timeout 90s`** ✗
        #    实测 `bsk navigate` 的 **默认超时是 30 秒** ✗
        #      （`bsk navigate --help`：`--timeout <TIMEOUT>  Hard timeout
        #        (default 30s)` ✗）
        #    而飞书首屏**很慢** ✗ 30 秒不够 ✗ ⇒ 报：
        #      `error: operation timed out / details: tool RPC timed out
        #       after 30s` ✗
        #    2026-11-04 实测：连发 2 次都超时 ✗ 第 3 次（缓存热了）才成功 ✗
        #    ⇒ 提到 **90 秒** ✓ 一次到位 ✓
        # 🔴 2026-11-13 用户反馈「发送 task 失败频率变高」⇒ 加**重试** ✓
        #    实测失败模式（今天 10+ 次）：
        #      ① 「找不到输入框；可能未登录或页面结构变了」 ← 最多
        #      ② `navigate` 90s 超时（只到 DOMContentLoaded，没到 load）← 新增
        #      ③ 「页面被切走 / 掉登录」
        #    共同点：**都是「页面没准备好」** ✗
        #    根因：`bsk.start(no_focus=True)` 每次开**新会话**（新标签页）
        #          ⇒ 飞书是重 SPA ⇒ 每次都是**冷加载** ✗
        #    历史证据（本文件 2026-11-04 注释）：
        #      「连发 2 次都超时，**第 3 次（缓存热了）才成功**」
        #      ⇒ 说明**重试有效**（第二次时资源已缓存）✓
        #    ⇒ navigate 失败后等 5 秒重试 1 次（共 2 次，上限 185s）✓
        # 复用的会话里飞书页面**已经在** ⇒ 跳过 navigate ✓
        # （若复用的会话被切到别的页面，下面的 `find_textbox` 会失败 ⇒
        #   下一轮 `session list` 查不到该 sid 或用户手动处理 ⇒ 自然回退 ✓）
        # 🔴 2026-11-16 用户要求：**复用会话时也强制 navigate** ✓
        #    实测 `fix_1122z`：复用成功（跳过 navigate）但**循环里拿不到编辑器** ✗
        #    原因：飞书闲置一段时间后会**卸载编辑器**（省内存）✗
        #    ⇒ 复用的会话页面看似还在聊天页，实际 DOM 已空 ✗
        #    ⇒ 无条件 navigate 一次，保证页面是新鲜的 ✓
        #    代价：失去「跳过 navigate」的 30~45 秒加速 ✗
        #      但仍保留「跳过 `start`」的收益（创建会话更慢）✓
        if True:                              # noqa: SIM103 —— 保留缩进便于回退
            # 🔴 2026-11-18：navigate **必须**先有 context ✗（0.5.0 严格模式）
            #    `navigate` 已加入 `_CTX_ACTIONS` ⇒ `run()` 会追加 `--context` ✓
            #    但**复用会话**路径里 `self.ctx` 还是 `None` ✗（没调过 `sync()`）
            #    ⇒ 实测报
            #      `error: this action needs an explicit current observation` ✗
            #    ⇒ 触发下面的「复用会话失效」误判 ⇒ 白重建一个会话 ✗
            #    ⇒ 先 sync 一次拿 ctx；失败也继续（新会话有初始 observation）✓
            try:
                bsk.sync()
            except Exception as _e:          # noqa: BLE001
                print("[navigate] 预 sync 失败（不影响后续）：%s" % str(_e)[:80])
            _nav_err = None
            for _i in range(2):
                try:
                    bsk.run("navigate", FEISHU_URL, "--timeout", "90s")
                    _nav_err = None
                    break
                except Exception as _e:      # noqa: BLE001
                    _nav_err = _e
                    print("[navigate] 第 %d/2 次失败：%s"
                          % (_i + 1, str(_e)[:120]))
                    if _i == 0:
                        time.sleep(5)        # 给缓存/连接一点时间
            if _nav_err is not None:
                # 🔴 2026-11-16 实测（`fix_1130b`）：复用的会话 navigate 报
                #    `the control context no longer belongs to the current tab` ✗
                #    ⇒ 说明该会话的 tab 已经失效（飞书页面崩过）✗
                #    ⇒ **复用坏会话比新建更糟**（navigate 都做不到）✗
                #    ⇒ 回退：销毁会话 + 重建 + 再 navigate 一次 ✓
                print("[navigate] 复用会话失效 ⇒ 重建会话重试")
                try:
                    bsk.stop()
                except Exception:             # noqa: BLE001
                    pass
                sid = bsk.start()
                try:
                    bsk.run("navigate", FEISHU_URL, "--timeout", "90s")
                    _nav_err = None
                    print("  重建后 navigate 成功 ✓")
                except Exception as _e2:      # noqa: BLE001
                    raise _e2

        # ⚠️ 飞书首屏**很慢**（实测 5 秒时连会话列表都还没渲染出来）——
        # 固定 sleep 会误判成"找不到会话"。改成轮询等待。
        ref = label = None
        vom = ""
        for attempt in range(15):              # 最多等 ~45 秒
            time.sleep(3)
            # 🔴 用 `sync()` 而非 `observe()`：click 的 ref 必须来自同一次 sync ✓
            _ctx, vom = bsk.sync()
            ref, label = bsk.find_chat(vom, args.chat)
            if ref:
                break
            # 飞书**间歇性**卡在首屏（实测：`main` 渲染不出来，只有几个按钮）。
            # 等一半时间还没出来就**重载一次** —— 比重试等待有效得多。
            if attempt == 6:
                print("  …会话列表没出来，重载页面")
                bsk.run("reload", check=False)
            else:
                print("  …等待会话列表（%d/15）" % (attempt + 1))
        if not ref:
            print("⚠️ 会话列表里没找到「%s」，现有条目：" % args.chat)
            for r, l in BUTTON_RE.findall(vom)[:25]:
                print("    %s  %s" % (r, l[:50]))
            raise SystemExit("请用 --chat 指定正确的会话名")
        print("会话项：%s" % label[:40])
        # 🔴 2026-11-17：bsk 0.5.0 的 `click` 报
        #      `native input clock could not be calibrated`
        #      `Cannot attach to this target`
        #    实测判据：连**同域**元素（`@e2 button "消息"`）也失败
        #      ⇒ `chrome.debugger.attach` 整体不可用 ✗
        #      （`edge://policy` 无 debugger/ExtensionSettings 限制；
        #        bsk doctor 全绿；0.4.2 的 click 走 JS 合成所以能用）
        #    ✅ 但 `fill` / `press` / `evaluate` / `request-help` **都可用** ✓
        #    ⇒ 对策：
        #      ① 输入框已在（复用会话 tab 常驻）⇒ **跳过点击** ✓
        #      ② 未打开且 click 不可用 ⇒ `request-help` 请人工点一次 ✓
        _already = bsk.find_textbox(bsk.sync()[1])
        if _already:
            print("  会话已打开，跳过点击")
        else:
            try:
                bsk.run("click", ref)
            except RuntimeError as _ce:
                _msg = str(_ce)
                if ("native input" not in _msg
                        and "attach to this target" not in _msg):
                    raise
                print("  …native input 不可用，请人工点开会话")
                bsk.run("request-help", "--prompt",
                        "请点击左侧「%s」打开聊天窗口，然后点确认"
                        % args.chat,
                        "--title", "点开会话", check=False)

        box = None
        # 🔴 2026-11-11：提到 **20 次（40 秒）** ✗ —— 新版下聊天窗口渲染更慢，
        #    而且「点会话」后要先出现 `发送给` 才算编辑器就绪 ✓
        for attempt in range(20):              # 等输入框出现
            time.sleep(2)
            # 点开会话后**主文档变了** ⇒ 必须重新 sync ✓
            _ctx, vom = bsk.sync()
            box = bsk.find_textbox(vom)
            if box:
                break
        if not box:
            raise SystemExit("❌ 没找到输入框；可能未登录或页面结构变了")
        print("输入框：%s" % box)
        print()

        sent = 0
        for i, (name, text) in enumerate(todo, args.start):
            # ⚠️ **每发一条，ref 就失效一次** —— 发完消息后消息列表变了，
            # 旧 ref 会报 "snapshot ref was not found for this tab"。
            # 所以每条都要重新 sync、重新拿输入框 ref（实测踩到过）。
            # 🔴 2026-11-11 实测：**第一次能拿到输入框，循环里再 sync 就没了** ✗
            #    （`fix_1111w` 连续 2 次卡在这里：日志先打印
            #     `输入框：div[contenteditable="true"]`，然后报「找不到输入框」✗）
            #    原因：`click` 打开会话后主文档还在变，紧接着的 sync 可能
            #    抓到**过渡态**（VOM 里还没有 `发送给` 那行）✗
            #    ⇒ 加**重试**：最多 6 次 × 2 秒 ✓，别一次抓空就退出 ✓
            box = None
            # 🔴 2026-11-12 实测：6 次（12 秒）**不够** ✗ ——
            #    日志显示首次等待（20 次 / 40 秒）拿到了输入框，
            #    但进循环后 12 秒内 `find_textbox` 一直返回 None ✗
            #    （`fix_1120u` / `task_1112r` 连续 4 次同一位置失败）
            #    ⇒ 提到 **20 次（40 秒）**，与首次等待一致 ✓
            # 🔴 2026-11-13 用户要求：**20 → 30 次（40s → 60s）** ✓
            #    实测（今天 15+ 个包）：20 次（40 秒）**仍会失败** ✗
            #    典型日志：`❌ 第 1 条（xxx）前找不到输入框`
            #    ⇒ 飞书冷加载比之前更慢（可能前端变重了）✗
            #    ⇒ 提到 **30 次（60 秒）**；失败时多等 20 秒可接受 ✓
            #      （成功时通常在 1~3 次内 break，不影响正常速度 ✓）
            # 🔴 2026-11-16 用户反馈：**「进入页面后需要先点击会话才会出来编辑框」** ✓
            #    实测：首次等待（20×2s）能拿到 box，但进循环后 30×2s 全 None ✗
            #    原因：`click` 后消息列表继续加载 ⇒ **页面重渲染** ⇒ 编辑器被
            #      卸载重建 ⇒ 只靠 `sync()` 重试抓不到（旧 ref 也失效）✗
            #    ⇒ 每 5 次（10 秒）**重新点一次会话**，强制触发一次渲染 ✓
            #      （此时还没 `fill`，重新点击不会丢内容 ✓）
            for _try in range(30):
                _ctx, vom = bsk.sync()
                box = bsk.find_textbox(vom)
                if box:
                    break
                if _try and _try % 5 == 0:
                    # 🔴 2026-11-16 用户要求：**加打印** ✓
                    #    之前 `except: pass` 吞掉一切 ⇒ 日志里看不到「重点」发生
                    #    实测 `fix_1122z` 失败时**完全没有**这一行 ✗
                    #    ⇒ 分不清是「find_chat 返回 None」还是「click 抛异常」✗
                    # 🔴 2026-11-16 实测（`fix_1130a`）：打印后发现
                    #    **`vom_len=0` 连续 5 次** ✗ —— 页面整个是空的
                    #    （不是「找不到编辑器」，是**飞书 SPA 崩了/被卸载**）✗
                    #    ⇒ 空页面**不会自己恢复**，只 sync 永远拿不到 ✓
                    #    ⇒ `vom_len < 500` 就**重新 navigate** 一次 ✓
                    if len(vom) < 500:
                        # 🔴 2026-11-16 实测（`fix_1130c`）：**不能在这里 navigate** ✗
                        #    VOM 为空说明 context 已失效 ⇒ `bsk navigate` 报
                        #    `the control context no longer belongs to the
                        #    current tab` ✗ ⇒ 而且 `continue` 会**跳过一次 sync**
                        #    机会 ⇒ 反而更慢 ✗
                        #    对照：`fix_1130a` 什么都不做，5 次 `vom_len=0` 后
                        #    **第 6 次页面自己恢复了** ✓（约 60 秒）
                        #    ⇒ 这里**只打印**，靠 sync 重试等待自愈 ✓
                        print("  …VOM 为空(%d)，继续等（第 %d 次）"
                              % (len(vom), _try // 5))
                        time.sleep(2)
                        continue
                    _r, _l = bsk.find_chat(vom, args.chat)
                    if _r:
                        try:
                            bsk.run("click", _r)
                            print("  …重新点会话（第 %d 次，ref=%s）"
                                  % (_try // 5, _r))
                        except Exception as _ce:   # noqa: BLE001
                            print("  …重点失败（第 %d 次）：%s"
                                  % (_try // 5, str(_ce)[:100]))
                    else:
                        print("  …VOM 里找不到会话（第 %d 次，vom_len=%d）"
                              % (_try // 5, len(vom)))
                time.sleep(2)
            if not box:
                # 🔴 2026-11-13：**清掉复用的 sid** ✓ —— 找不到输入框说明
                #    这个会话里的飞书页面已经不可用（被切走/掉登录）✗
                #    ⇒ 删掉 sid 文件 ⇒ **下次自动走新建流程**（含 navigate）✓
                #    否则会一直复用一个坏会话，每次都失败 ✗
                try:
                    _SID_FILE.unlink()
                except OSError:
                    pass
                raise SystemExit("❌ 第 %d 条（%s）前找不到输入框；"
                                 "可能页面被切走或掉登录了"
                                 "（已清掉复用 sid，下次会新建会话）" % (i, name))

            # `fill` 有时报 "browser rejected the underlying CDP call"，
            # 但**内容其实已经填进去了**（校验被 placeholder 干扰）。
            # 故不把非零退出当失败，而是**观察一次**确认真填上了。
            bsk.fill(box, text)
            vom2 = bsk.observe()
            if text[:20] not in vom2:
                # 🔴 重填也要重新 sync（`observe` 的 ref 不能用于 `fill` ✗）
                _c2, vom2 = bsk.sync()
                box2 = bsk.find_textbox(vom2) or box
                bsk.fill(box2, text)
                vom2 = bsk.observe()
                if not _box_has_text(vom2, text[:20]):
                    raise SystemExit(
                        "❌ 第 %d 条（%s）没填进去。\n"
                        "   已发 %d 条；用 --start %d 续发。"
                        % (i, name, sent, i))
                box = box2
            # 🔴 `fill` 改了 DOM ⇒ 旧 context 可能失效 ⇒ press 前再 sync 一次 ✓
            _c3, _v3 = bsk.sync()
            bsk.press("Enter", bsk.find_textbox(_v3) or box)
            # ⚠️ **必须验证真的发出去了** —— `press Enter` 不报错 ≠ 消息已发送。
            #    实测（2026-09-28）：最后一条 `fill` 成功、`press Enter` 也没报错，但消息
            #    **停在输入框里**没发出去，而脚本照样打印「已发」⇒ 用户无法分辨
            #    「真发出」和「只填进了输入框」（用户当场报告输入框里残留着那串文本）。
            #    判据 = **输入框已被清空**（发送成功的强信号；消息列表里的同文本不算，
            #    见 `_box_has_text`）。
            # 🔴 2026-10-31 实测：固定 `sleep(0.4)` 太短 ✗ ——
            # 飞书清空输入框有延迟，早判会误报「填进了但没发出去」✗
            # （`sync_1028er` 连试 4 次都卡在这一步，换包名就成功 ✗
            #   ⇒ 说明是**时序抖动**而不是内容问题 ✓）
            # ⇒ 轮询最多 3 秒等清空 ✓；仍不清空才判失败并写 FAIL 台账 ✓
            cleared = False
            vom3 = ""
            for _ in range(10):
                time.sleep(0.3)
                vom3 = bsk.observe()
                if not _box_has_text(vom3, text[:20]):
                    cleared = True
                    break
            if not cleared:
                _ledger_add(name, i, len(chunks), ok=False)
                raise SystemExit(
                    "❌ 第 %d 条（%s）填进了输入框但**没有发出去**"
                    "（等了 3 秒输入框仍含该文本）。\n"
                    "   已发 %d 条；用 --start %d 续发 ✓\n"
                    "   ⚠️ 若连续多次失败 ⇒ **换个包名重新打包**再发"
                    "（同一包名重试常常无效 ✗）"
                    % (i, name, sent, i))
            sent += 1
            _ledger_add(name, i, len(chunks))   # 台账先落盘 ✓ 再打印（stdout 可能被截断 ✗）
            print("  [%3d/%3d] %s  已发" % (i, len(chunks), name))
            time.sleep(args.pause)

        print()
        print("[OK] 发出 %d 条。" % sent)
        # ⚠️ **必须提引导脚本**（2026-09-28 补）：`keep`/`minimal`/`tests` 包里
        #    没有解包工具，而解包工具本身就在包里 ⇒ Mac 上必须先跑引导脚本。
        #    只提示 `restore_from_base64.py` 是错的 —— 那个文件 Mac 上**还没有**。
        if any(n.startswith("bootstrap-") for n, _t in chunks):
            print("     ⚠️ 首次引导必发 `bootstrap-t*.txt`（纯 base64，不带 ###FG: 标记）。")
            print("     Mac 上：选中那几条 → 复制 → 粘进 ~/Downloads/fg/b64.txt →")
            print("             cd ~/Downloads/fg")
            print("             base64 -d b64.txt > /tmp/mac_bootstrap.sh  # 老版 macOS 用 -D")
            print("             bash /tmp/mac_bootstrap.sh")
            print("     其余分片：打开同一个会话 → 全选复制 → 存成 .txt 放进同一个目录。")
        else:
            print("     接着在 Mac 上：打开同一个会话 → 全选复制 → 存成一个文件 →")
            print("     bash scripts/mac_bootstrap.sh")
        return 0
    finally:
        # 🔴 2026-11-16 用户要求：**改成 daemon 常驻会话** ✓
        #    原来**无条件** `stop()` ⇒ 每个进程结束都销毁会话 ✗
        #    ⇒ 下一个包必须 `reap()` + `start()` + `navigate()` 冷启动 ✗
        #      实测要 30~45 秒（飞书首屏很慢）⇒ `find_textbox` 常在 DOM
        #      就绪前返回 None ⇒ 报「找不到输入框」✗
        #    实测对照（同一天）：
        #      `stop --all` 后发 ⇒ **连续 2 次失败** ✗
        #      不 stop（复用刚打开的会话）⇒ **一次成功** ✓
        #    ⇒ **成功时保留会话**（下次 `reuse_or_start` 直接复用，跳过冷启动）✓
        #       **失败时仍 stop**（会话可能已坏，留着会拖累下次）✓
        #    自愈：保留的会话若真坏了（掉登录/被切走）⇒ 下次 `find_textbox`
        #      返回 None ⇒ 兜底 `_SID_FILE.unlink()` ⇒ 再下次重建 ✓
        if sys.exc_info()[0] is not None:
            bsk.stop()
            print("bsk 会话已结束（失败，已清理）。")
        else:
            print("bsk 会话保留（下次复用，跳过冷启动）。")
        _release_lock(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
