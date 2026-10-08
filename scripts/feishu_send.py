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
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402

TEXT_DIR = os.path.join(config.ROOT, "dist", "feishu", "text")
FEISHU_URL = "https://www.feishu.cn/messenger/"
TEXTBOX_RE = re.compile(r"(@e\d+)\s+textbox")
BUTTON_RE = re.compile(r"(@e\d+)\s+button\s+\"([^\"]*)\"")


class Bsk:
    """`bsk` CLI 的薄封装。"""

    def __init__(self, session=None, quiet=True):
        self.session = session
        self.quiet = quiet

    def run(self, *args, check=True):
        cmd = ["bsk"] + list(args)
        if self.session:
            cmd += ["--session", self.session]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if check and proc.returncode != 0:
            raise RuntimeError("bsk %s 失败：%s"
                               % (" ".join(args), (proc.stderr or proc.stdout).strip()))
        return proc.stdout or ""

    def start(self, no_focus=True):
        args = ["session", "start"]
        if no_focus:
            args.append("--no-focus")
        out = self.run(*args)
        self.session = out.strip().splitlines()[-1].strip()
        return self.session

    def stop(self):
        if self.session:
            try:
                self.run("session", "stop", self.session, check=False)
            finally:
                self.session = None

    def observe(self):
        """返回 VOM 文本。"""
        raw = self.run("observe", "--json")
        try:
            return json.loads(raw).get("text", raw)
        except json.JSONDecodeError:
            return raw

    def find_textbox(self, vom):
        m = TEXTBOX_RE.search(vom)
        return m.group(1) if m else None

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


def filter_chunks(chunks, pkg=None):
    """按包名过滤分片（`pkg` 为空 ⇒ **不过滤**，保持历史行为）。

    `chunks` 是 `(文件名, 文本)` 列表，文件名形如 `minimal-t007.txt`。
    ⚠️ `bootstrap-*`（引导脚本）**始终保留** —— 它不带 `###FG:` 标记、不属于任何包，
    但**首次引导必发**（§12.27-③）⇒ 过滤时不能丢。

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
            if c[0].startswith("bootstrap-") or _sort_key(c[0])[0] == pkg]


def _box_has_text(vom, snippet):
    """VOM 里**输入框那一行**是否含 `snippet`。

    ⚠️ **必须只看输入框行**（`textbox`）—— 消息列表里本来就可能有同样的文本
    （**已经发过**的那条），若匹配任意行，**续发时会把「已经发过」误判成「填进去了」**
    （2026-09-28 实测踩到的形态：那条分片其实发过，但列表里也有 ⇒ 判据失效）。
    """
    for line in vom.splitlines():
        if "textbox" in line and snippet in line:
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
                    help="只发指定包的分片（`bootstrap-*` 引导脚本始终保留）。"
                         "例：`--pkg minimal`。默认发全部")
    args = ap.parse_args()

    chunks = sorted(_chunks(), key=lambda kv: _sort_key(kv[0]))
    chunks = filter_chunks(chunks, args.pkg or None)
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

    bsk = Bsk()
    try:
        sid = bsk.start(no_focus=True)
        print("bsk 会话：%s" % sid)

        bsk.run("navigate", FEISHU_URL)

        # ⚠️ 飞书首屏**很慢**（实测 5 秒时连会话列表都还没渲染出来）——
        # 固定 sleep 会误判成"找不到会话"。改成轮询等待。
        ref = label = None
        vom = ""
        for attempt in range(15):              # 最多等 ~45 秒
            time.sleep(3)
            vom = bsk.observe()
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
        print("打开会话：%s" % label[:40])
        bsk.run("click", ref)

        box = None
        for attempt in range(10):              # 等输入框出现
            time.sleep(2)
            vom = bsk.observe()
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
            # 所以每条都要重新观察、重新拿输入框 ref（实测踩到过）。
            vom = bsk.observe()
            box = bsk.find_textbox(vom)
            if not box:
                raise SystemExit("❌ 第 %d 条（%s）前找不到输入框；"
                                 "可能页面被切走或掉登录了" % (i, name))

            # `fill` 有时报 "browser rejected the underlying CDP call"，
            # 但**内容其实已经填进去了**（校验被 placeholder 干扰）。
            # 故不把非零退出当失败，而是**观察一次**确认真填上了。
            bsk.run("fill", box, "--value", text, check=False)
            vom2 = bsk.observe()
            if text[:20] not in vom2:
                box2 = bsk.find_textbox(vom2) or box
                bsk.run("fill", box2, "--value", text, check=False)
                vom2 = bsk.observe()
                if not _box_has_text(vom2, text[:20]):
                    raise SystemExit(
                        "❌ 第 %d 条（%s）没填进去。\n"
                        "   已发 %d 条；用 --start %d 续发。"
                        % (i, name, sent, i))
                box = box2
            bsk.run("press", "Enter", "--ref", box)
            # ⚠️ **必须验证真的发出去了** —— `press Enter` 不报错 ≠ 消息已发送。
            #    实测（2026-09-28）：最后一条 `fill` 成功、`press Enter` 也没报错，但消息
            #    **停在输入框里**没发出去，而脚本照样打印「已发」⇒ 用户无法分辨
            #    「真发出」和「只填进了输入框」（用户当场报告输入框里残留着那串文本）。
            #    判据 = **输入框已被清空**（发送成功的强信号；消息列表里的同文本不算，
            #    见 `_box_has_text`）。
            time.sleep(0.4)
            vom3 = bsk.observe()
            if _box_has_text(vom3, text[:20]):
                raise SystemExit(
                    "❌ 第 %d 条（%s）填进了输入框但**没有发出去**（输入框仍含该文本）。\n"
                    "   已发 %d 条；用 --start %d 续发。"
                    % (i, name, sent, i))
            sent += 1
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
        bsk.stop()
        print("bsk 会话已结束。")


if __name__ == "__main__":
    sys.exit(main())
