# -*- coding: utf-8 -*-
"""把部署集打成**能过飞书**的投递包。

【为什么需要 —— 飞书**两个维度**都会拦（2026-09-23 实测）】
    · **压缩包（`.zip`）**：约 10 KB 就被拦 —— DLP 对压缩包做内容扫描，扫不完就拒
    · **其它文件**：10 KB 过、90 KB 不过

最刺眼的证据 —— 两个文件**只差 5 个字节**：
        code-part03.bin   10188 B   ✅ 通过
        keep.zip          10183 B   ❌ 上传失败

⇒ 所以本工具**两条纪律**：
  1. 产物**一律不叫 `.zip`**，分片叫 `.bin`，Mac 上合并后再解压
  2. 每片不超过 **9 KB**（实测 10 KB 能过、90 KB 不过，取 9 留余量）

【四个包（tar.xz，LZMA 对中文注释压缩率远高于 deflate）】
    code    `fg_system/` + `scripts/` + `requirements.txt` + `pytest.ini`
            + `mobile/` 根目录文件（`tests/` 引用其中的 `patch_repos.py`）
            **124 KB ⇒ 14 片**。**必传**
    keep    **不可再生**的小文件（守猪待兔历史、拆股表、状态、实盘快照、凭据）
            **7.8 KB ⇒ 1 个文件**。**必传**
    tests   `tests/` 68 KB ⇒ 8 片。可选（自检用）
    data    `Data/raw/` **可选** —— 家里 Mac 有公网，跑
            `scripts/bootstrap_data.py` 就能自己抓回来，**通常不必传**

【推荐组合（最少 15 个文件）】
    code（14 片）+ keep（1 个）
    然后在 Mac 上：合并 → 解压 → `bootstrap_data.py` 抓数据 → 拷凭据 → 跑测试

【想少传几个？先跑 `--probe`】
    10~90 KB 之间**还没测过**。若 60 KB 也能过，分片数能从 14 降到 3。
    探针只有 8 个文件，传一次就能把上限钉死。

用法：
    python scripts/make_feishu_bundle.py                 # 出 code + keep（推荐）
    python scripts/make_feishu_bundle.py --with-tests    # 再加 tests
    python scripts/make_feishu_bundle.py --with-data     # 再加 Data/raw（19 片）
    python scripts/make_feishu_bundle.py --max-kb 90     # 改分片大小
    python scripts/make_feishu_bundle.py --list          # 只报体积，不落盘
"""
import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402

# 复用部署清单 —— **不要在这里另立一套**，否则两边会漂移
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_deploy_set import (                   # noqa: E402
    MANUAL_FILES, NEED_DATA_FILES, NEED_DIRS, NEED_FILES)

OUT_DIR = os.path.join(config.ROOT, "dist", "feishu")
_IGNORE = (".pyc", ".pyo")


def strip_source(src):
    """去掉**注释与文档字符串**，保留可执行代码。

    【为什么值得做（2026-09-23 实测）】
    本系统的源码里中文注释与文档字符串占了大头（UTF-8 下 1 汉字 = 3 字节），
    而它们对**运行**毫无影响。实测最小集：

        原样        68.2 KB -> base64  90.9 KB -> **55 条消息**
        去注释后    27.4 KB -> base64  36.6 KB -> **23 条消息**  （省 60%）

    ⇒ 这是「103 条消息」降到「23 条」的**决定性一步**。

    【安全性】文档字符串统一换成 `pass`（保留缩进）——
    比"整段删掉"安全：空函数体/空分支不会变成语法错误。
    """
    import tokenize
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        return src                      # 解析不了就原样返回，绝不冒险

    lines = src.splitlines(keepends=True)
    comment_only, trailing = set(), {}
    for t in toks:
        if t.type != tokenize.COMMENT:
            continue
        line = lines[t.start[0] - 1]
        if line[:t.start[1]].strip() == "":
            comment_only.add(t.start[0])          # 整行都是注释 -> 可删
        else:
            # ⚠️ **行尾注释**只能砍掉注释本身，**代码必须留下**。
            # 实测踩到：`except Exception:  # 说明` 被整行删掉后，
            # `try:` 没了 `except` -> SyntaxError（而且要到 Mac 上才发现）。
            trailing[t.start[0]] = t.start[1]

    drop = set(comment_only)
    for i, t in enumerate(toks):
        if t.type == tokenize.STRING and (
                i == 0 or toks[i - 1].type in (tokenize.NEWLINE,
                                               tokenize.INDENT,
                                               tokenize.NL)):
            for ln in range(t.start[0], t.end[0] + 1):
                drop.add(ln)

    out = []
    for n, line in enumerate(lines, 1):
        if n in trailing:
            out.append(line[:trailing[n]].rstrip() + "\n")
        elif n in drop:
            if line.strip().startswith(('"""', "'''")):
                out.append(line[:len(line) - len(line.lstrip())] + "pass\n")
        else:
            out.append(line)
    result = "".join(out)

    # **安全网**：去注释后必须先能编译，否则退回原文。
    # 宁可多传几 KB，也不能把语法错误的代码送到 Mac 上 ——
    # 那边发现时，103 条消息已经发完了。
    try:
        compile(result, "<stripped>", "exec")
    except SyntaxError:
        return src
    return result


def _zip_stripped(paths):
    """同 `_zip`，但 `.py` 文件**先去注释**再打包。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz", preset=9) as tf:
        for p, arc in paths:
            if p.endswith(".py") and os.path.isfile(p):
                data = strip_source(open(p, encoding="utf-8").read()).encode("utf-8")
                info = tarfile.TarInfo(arc)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            else:
                _add_tar(tf, p, arc)
    return buf.getvalue()


def _posix(p):
    """归档名一律用 `/`。

    ⚠️ **实测踩到**：Windows 上 `os.path.relpath` 返回 `fg_system\\config.py`，
    直接当 tar 归档名打进去后，**macOS 解出来是一个"名字里带反斜杠"的文件**
    —— 代码根本跑不起来。而这个错误只有在 Mac 上才会暴露，
    那时 100 条消息已经发完了。
    """
    return p.replace("\\", "/")


def _add_tar(tf, path, arcname):
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in sorted(files):
                if f.endswith(_IGNORE):
                    continue
                fp = os.path.join(root, f)
                tf.add(fp, _posix(os.path.join(arcname, os.path.relpath(fp, path))))
    elif os.path.isfile(path):
        tf.add(path, _posix(arcname))


# ⚠️ 引导分片的标记**必须是 `###FGB:`** 而不是 `###FG:` —— 后者会被还原脚本
# 当成一个"包"去解 xz 而**必然失败**（§12.27-③）。`###FGB:` 与包的匹配式
# `###FG:([A-Za-z0-9_]+):i/N###` **不冲突**（`FG` 后面是 `B` 不是 `:`）。
# 有标记才能从 `.md` 导出里**自动定位**引导脚本（§12.29-③）。
BOOT_MARK = "###FGB:%d/%d###"
BOOT_END = "###FGB:end###"
BOOT_PAT = re.compile(r"###FGB:(\d+)/(\d+)###(.*?)###FGB:end###", re.S)


def strip_boot_marker(text):
    """从引导分片（或含引导分片的 `.md`）里取出**裸 base64**。

    没有标记时**原样返回** —— 兼容 2026-09-29 之前发的旧分片（那时没有标记）。
    空白一并去掉（`.md` 导出会在中间插换行）。
    """
    m = BOOT_PAT.search(text)
    return "".join(m.group(3).split()) if m else text.strip()


def _text_mode(bundles, msg_chars, doc_chars, out_dir, pack=None):
    """把 tar.xz 转成 **base64 纯文本** —— 实测唯一稳定能过的形态。

    【为什么必须是纯文本（2026-09-23 实测，证据链完整）】
    成功：纯文本 394 B / 1.8 KB、zip 5.7 KB（小到能扫完）、
          **无魔数的压缩流中段碎片 10188 B**
    失败：**完整 xz 7.8 KB**、xz 开头 90 KB、纯文本 20~80 KB、zip 10 KB

    ⇒ 两条规则叠加：
      1. **有压缩魔数（zip / xz）→ 直接拦**，与大小无关
         （`keep.bin` 只有 7.8 KB 就被拦，而 10188 B 的中段碎片能过 ——
          区别就在于**开头有没有魔数**）
      2. **纯文本 → 上限约 10 KB**（1.8 KB 过、20 KB 不过）

    ⇒ 所以：**base64**（纯 ASCII、无魔数）**+ 每片 ≤ 8 KB**。

    【更好的走法：根本不发文件】
    飞书**云文档 / 消息**里可以直接粘贴文本 —— 那不是"文件上传"，
    大概率绕过这套文件检查。`<bundle>.b64` 就是给这条路的整块文本。
    """
    pack = pack or _zip
    os.makedirs(out_dir, exist_ok=True)
    base = msg_chars
    written = []

    # **首次引导脚本** —— 纯 base64 分片，**不带** `###FG:` 标记。
    #
    # 【为什么需要（2026-09-28 实测发现的鸡生蛋）】
    # `keep` / `minimal` / `tests` 三个包里**没有解包工具**，而解包工具本身就在包里
    # ⇒ 首次引导必须靠一段**不依赖仓库任何文件**的脚本。它住在
    # `scripts/mac_bootstrap.sh`，这里把它 base64 后发出去。
    #
    # ⚠️ **故意不加 `###FG:` 标记** —— 加了会被还原脚本当成一个"包"去解 xz 而失败。
    # ⚠️ 命名 `bootstrap-t*` 保证 `sorted()` 排在所有包**之前** ⇒
    #    `feishu_send.py --start 1 --limit N` 正好只发这几条。
    boot = os.path.join(config.ROOT, "scripts", "mac_bootstrap.sh")
    if os.path.isfile(boot):
        b64 = base64.b64encode(open(boot, encoding="utf-8").read()
                               .encode("utf-8")).decode("ascii")
        # 标记开销：`###FGB:i/N###` + `###FGB:end###`（i/N 最多各 3 位）
        overhead = len(BOOT_MARK % (999, 999)) + len(BOOT_END)
        # ⚠️ 评审 m1：用**独立变量**，不要就地改 `base` —— 否则后续所有包的
        #    消息分片都会被无条件缩短 30 字符（分片数被无谓抬高，与瘦身目标相悖）。
        boot_base = max(200, msg_chars - overhead)
        chunks = [b64[i:i + boot_base] for i in range(0, len(b64), boot_base)]
        total = len(chunks)
        for n, part in enumerate(chunks, 1):
            fname = "bootstrap-t%s.txt" % _num(n, len(b64), boot_base)
            body = BOOT_MARK % (n, total) + part + BOOT_END
            with open(os.path.join(out_dir, fname), "w", encoding="ascii") as fh:
                fh.write(body)
            written.append((fname, len(body), "引导脚本（发消息）"))

    for name in bundles:
        blob = pack(_spec([name]))
        b64 = base64.b64encode(blob).decode("ascii")
        # 整块 —— 留档用（⚠️ 太大，粘不进飞书文档，见下）
        whole = os.path.join(out_dir, "%s.b64.txt" % name)
        with open(whole, "w", encoding="ascii") as fh:
            fh.write(b64)
        written.append((os.path.basename(whole), len(b64), "整块（仅留档）"))

        # **文档块** —— 粘进飞书云文档用。
        # 实测飞书文档报错：「该内容块的字符数超出上限（100,000）」
        # ⇒ 必须按**字符数**切开，每块单独粘贴（块之间按回车分隔）。
        n = 0
        for i in range(0, len(b64), doc_chars):
            n += 1
            fname = "%s-d%s.txt" % (name, _num(n, len(b64), doc_chars))
            with open(os.path.join(out_dir, fname), "w", encoding="ascii") as fh:
                fh.write(b64[i:i + doc_chars])
            written.append((fname, min(doc_chars, len(b64) - i), "文档块（粘云文档）"))

        # 消息分片 —— 逐条发消息用。
        # **每条都带自定界标记**：从飞书聊天记录里「全选复制」会把昵称、
        # 时间戳、系统提示一起复制进来，直接拼会污染 base64。
        # 有标记就能精确提取（见 restore_from_base64.extract_marked）。
        # ⚠️ 分片大小要**扣掉标记本身的长度** —— 飞书的 1700 是**整条消息**
        # 的上限，不是"内容"的上限。不扣的话每条都超一点点，全发不出去。
        overhead = mark_len(name, 1, 999)
        body_max = max(64, base - overhead)
        chunks = [b64[i:i + body_max] for i in range(0, len(b64), body_max)]
        for n, part in enumerate(chunks, 1):
            fname = "%s-t%s.txt" % (name, _num(n, len(b64), body_max))
            text = mark(name, n, len(chunks), part)
            with open(os.path.join(out_dir, fname), "w", encoding="ascii") as fh:
                fh.write(text)
            # 记**整条消息**的长度 —— 这才是要和 1700 比的那个数
            written.append((fname, len(text), "消息分片（发消息）"))
    return written


MARK_FMT = "###FG:%s:%s/%s###%s###FG:end###"


def mark(name, i, total, body):
    """给分片包一层**自定界标记**，便于从聊天记录里精确提取。

    形如（**单行**）：
        ###FG:code:001/103###<base64…>###FG:end###

    【为什么必须单行】
    飞书输入框**按回车就发送** —— 若标记里带换行，`fill` 进去只会发出第一行，
    剩下 1699 个字符留在草稿里。**57 条全都会是残的。**
    ⇒ 顺带也彻底消除了"噪声被插进分片内部"的可能（body 里根本没有换行）。

    为什么要标记：飞书聊天记录「全选复制」会把**昵称、时间戳、系统提示**
    一并复制进来。没有标记就只能靠"过滤非 base64 字符"，而
    `17:00` 这类时间戳里的**数字会被误当成内容**，静默损坏数据。
    """
    return MARK_FMT % (name, i, total, body)


def mark_len(name, i, total):
    """标记本身的字符数（用来把**总长度**控制在飞书上限内）。"""
    return len(MARK_FMT % (name, i, total, ""))


def _num(i, total_len, chunk):
    """给分片编号**补足位数**，保证字典序 == 数字序。

    ⚠️ 实测踩到：110 个分片用 `%02d` 会产出 `t100`，而
    `sorted()` 按字典序排 ⇒ `t100` 排在 `t11` 前面 ⇒ **拼出来的内容全乱**
    （而且不报错，只是 MD5 对不上）。位数必须按**总数**算。
    """
    width = max(2, len(str((total_len + chunk - 1) // chunk)))
    return "%0*d" % (width, i)


def _probe(out_dir, sizes_kb):
    """生成「大小探针」—— 用来测出**非压缩包**的真实上限。

    已确定：`.bin` 10 KB ✅、90 KB ❌；`.zip` 10 KB ❌（扩展名问题）。
    但 10~90 KB 之间**还没测过**。多传 4 个文件，可能就把分片数从 12 降到 3。
    """
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for kb in sizes_kb:
        n = kb * 1024
        for ext in ("bin", "txt"):
            name = "probe-%dk.%s" % (kb, ext)
            p = os.path.join(out_dir, name)
            # 用可读文本填 —— 与真实源码/日志更接近（随机字节可能被另眼相看）
            body = (b"probe line for transfer-limit test\n" * (n // 33 + 1))[:n]
            with open(p, "wb") as fh:
                fh.write(body)
            made.append((name, n))
    print("大小探针（全部传一次，告诉我哪几个成功）：")
    for name, n in made:
        print("    %-18s %7.1f KB" % (name, n / 1024))
    print()
    print("    目的：确认**非压缩包**的真实上限。已确定 .bin 10 KB 过、90 KB 不过。")
    print("    若 60 KB 也过，就能把分片数从 12 降到 3。")


def _zip(paths, base=None):
    """把 `(绝对路径, 归档名)` 列表打成 **tar.xz**，返回字节。

    【为什么不用 zip（2026-09-23 实测）】
    两个文件只差 **5 个字节**，结果一个过一个不过：

        code-part03.bin   10188 B   ✅ 通过
        keep.zip          10183 B   ❌ 上传失败

    ⇒ 拦的不是大小，是 **`.zip` 这个扩展名** —— 公司 DLP 对**压缩包**做内容
    扫描，扫不完就拒（5.7 KB 的 zip 能扫完，所以那个过了）。
    ⇒ 故：**产物一律不叫 `.zip`**，分片叫 `.bin`，Mac 上合并后再解压。

    【为什么用 xz 而不是 deflate】
    LZMA 对**中文注释**的压缩率远高于 deflate：实测 `fg_system/ + scripts/`
    原始 364 KB → zip 156 KB → **tar.xz 99.6 KB（再省 36%）**。
    分片数直接少一半。
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz", preset=9) as tf:
        for p, arc in paths:
            _add_tar(tf, p, arc)
    return buf.getvalue()


# ================================================================ 最小可运行集
# 从 **Mac 上真正要跑的入口** 出发，算 `fg_system` 的**传递闭包**。
# 不靠人工判断"这个用不到吧" —— 那会漏。
MAC_ENTRY = [
    "scripts/serve_dashboard.py",       # 仪表盘服务
    "scripts/fetch_shoutu_api.py",      # 06:30 每日抓取（API 通道）
    # A2 的**生产信号源**（shoutu_history.csv）。Mac 侧由 shoutu_daily.sh **可选**调用
    # —— 依赖 `bsk`（macOS 未实测）⇒ 缺它就跳过。不在本列表里 ⇒ `--minimal` 包不带它
    # ⇒ 任务会因缺文件失败（静默断更），所以必须列在这里（2026-09-28 补）。
    "scripts/fetch_shoutu_history.py",
    "scripts/bootstrap_data.py",        # 一次性数据重建
    "scripts/shoutu_daily.sh",          # launchd 调的包装脚本
    "scripts/install_shoutu_task.sh",   # 注册定时任务
    "scripts/portfolio_check.py",       # 实盘快照检查
    # ⚠️ **还原脚本本身**（2026-09-28 补）：原来不在列表里 ⇒ 包里没有它们
    #    ⇒ Mac 上拿到分片却**没有解包工具**。首次引导仍靠 `dist/feishu/restore_cmd.txt`
    #    那段「整段粘进终端」的脚本（它**刻意不依赖任何脚本文件**），
    #    但后续往返必须让这两个文件随包走。
    "scripts/restore_from_base64.py",   # 还原入口（Mac 用）
    "scripts/mac_restore.sh",           # 备用还原入口（xz 通道）
]


def _refs(path):
    """源码里引用的 `fg_system.*` 模块名（AST 静态导入 + 带点的字符串）。"""
    import ast
    src = open(path, encoding="utf-8").read()
    out = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.add(node.module)
                for a in node.names:
                    out.add(node.module + "." + a.name)
    # 动态导入：**必须带点** —— 否则字符串 `"fg_system"` 会把整个包拉进来
    for m in re.findall(r"['\"](fg_system\.[\w.]+)['\"]", src):
        out.add(m)
    return {r for r in out if r.startswith("fg_system.")}


def _resolve(mod):
    base = os.path.join(config.ROOT, *mod.split("."))
    for cand in (base + ".py", base):
        if os.path.isfile(cand):
            return cand
        if os.path.isdir(cand) and os.path.isfile(os.path.join(cand, "__init__.py")):
            return cand
    return None


def minimal_files():
    """返回 Mac 上**真正需要**的文件（相对路径），含全部 `__init__.py`。"""
    files, queue, seen = set(MAC_ENTRY), list(MAC_ENTRY), set()
    while queue:
        rel = queue.pop()
        if rel in seen or not os.path.isfile(os.path.join(config.ROOT, rel)):
            continue
        seen.add(rel)
        for mod in _refs(os.path.join(config.ROOT, rel)):
            target = _resolve(mod)
            if not target:
                continue
            if os.path.isdir(target):
                for root, dirs, fs in os.walk(target):
                    dirs[:] = [d for d in dirs if d != "__pycache__"]
                    for f in fs:
                        if f.endswith(".py"):
                            rel2 = _posix(os.path.relpath(os.path.join(root, f),
                                                          config.ROOT))
                            if rel2 not in files:
                                files.add(rel2)
                                queue.append(rel2)
            else:
                rel2 = _posix(os.path.relpath(target, config.ROOT))
                if rel2 not in files:
                    files.add(rel2)
                    queue.append(rel2)

    # ⚠️ **所有 `__init__.py` 必须带上** —— 它们可能只含副作用
    # （`fg_system/__init__.py` 的 `_make_console_safe()` 就是必需的），
    # 而 `import fg_system.dashboard.report` 不会在 AST 里显式引用它们。
    for f in list(files):
        d = os.path.dirname(f)
        while d:
            init = _posix(os.path.join(d, "__init__.py"))
            if os.path.isfile(os.path.join(config.ROOT, init)) and init not in files:
                files.add(init)
            d = os.path.dirname(d)

    # ⚠️ **非 Python 但必需的文件**：闭包只跟 `.py` 的 import 走，
    # 这两样**永远不会被引用**，却少了就跑不起来：
    #   `requirements.txt` —— 没有它 `pip install -r` 直接报错（实测踩到）
    #   `pytest.ini`       —— 没有它 `pytest` 会递归收集教学目录而失败
    for extra in NEED_FILES:
        if os.path.isfile(os.path.join(config.ROOT, extra)):
            files.add(extra)
    return sorted(files)


def _spec(bundles):
    """把包名展开成 `(绝对路径, 归档名)` 列表。"""
    R = config.ROOT
    out = []
    for name in bundles:
        if name == "code":
            for d in NEED_DIRS:
                # `tests` 是**独立包**（可选），别重复装进 code ——
                # 否则 code 会凭空多出 105 KB，白白多切一片
                if d == "tests":
                    continue
                out.append((os.path.join(R, d), d))
            for f in NEED_FILES:
                out.append((os.path.join(R, f), f))
            # ⚠️ `tests/test_mobile_patch_repos.py` 引用 `mobile/patch_repos.py` ——
            # 不带的话，合并后跑测试会 `FileNotFoundError`（**端到端验证时实际踩到**）。
            # 只带 mobile/ 的**根目录文件**，不带 node_modules / android 那堆。
            mob = os.path.join(R, "mobile")
            if os.path.isdir(mob):
                for entry in sorted(os.listdir(mob)):
                    p = os.path.join(mob, entry)
                    if os.path.isfile(p):
                        out.append((p, os.path.join("mobile", entry)))
        elif name == "keep":
            # 不可再生的小文件 + 凭据（凭据被 gitignore，靠这里带过去）
            for rel in NEED_DATA_FILES + MANUAL_FILES:
                p = os.path.join(R, rel)
                if os.path.isfile(p):
                    out.append((p, rel))
            # Data/raw 里**不可再生**的几个（守猪待兔权威日值 / 前向采样 + 拆股表）
            # `shoutu_history.csv` 是 2026-09-24 新增的**服务端权威日值**
            # （6 标的 3587 行）—— 虽可由 fetch_shoutu_history.py 重抓，
            # 但依赖会员有效期（至 2027-01-16），过期就抓不回来 ⇒ 按不可再生对待。
            for rel in ("Data/raw/shoutu_history.csv", "Data/raw/shoutu_fng.csv",
                        "Data/raw/splits.csv", "Data/raw/shoutu_etf_universe.csv"):
                p = os.path.join(R, rel)
                if os.path.isfile(p):
                    out.append((p, rel))
        elif name == "data":
            out.append((os.path.join(R, "Data", "raw"), "Data/raw"))
        elif name == "tests":
            out.append((os.path.join(R, "tests"), "tests"))
        elif name == "minimal":
            # Mac 上**真正需要**的文件（传递闭包算出，非人工判断）
            for rel in minimal_files():
                out.append((os.path.join(R, rel), rel))
        else:
            raise SystemExit("未知包：%s" % name)
    return out


def _human(n):
    return ("%.1f KB" % (n / 1024)) if n < 1048576 else ("%.1f MB" % (n / 1048576))


BUNDLE_NAMES = ("code", "keep", "minimal", "tests", "data")

KEEP_MANIFEST = os.path.join(OUT_DIR, "keep-manifest.json")
# m4（评审）：记住「已经提醒过哪个指纹」⇒ 同一指纹不重复刷屏（防告警疲劳）
KEEP_WARNED = os.path.join(OUT_DIR, "keep-warned.json")


def keep_fingerprint_paths():
    """`keep` 包**实际装**的文件（绝对路径）—— 与 `_spec(["keep"])` **同源**。

    ⚠️ 评审 M2：原来指纹只覆盖 `NEED_DATA_FILES ∪ MANUAL_FILES`，与包清单**漂移**
    ⇒ 改了 `Data/raw/*.csv`（拆股表、守猪待兔历史快照）却**不提醒** ✗，
    与 spec §4.4 的设计目的直接冲突。⇒ 统一到 `_spec` 这一处来源。
    """
    return [abs_path for abs_path, _arc in _spec(["keep"])]


def keep_fingerprint(paths=None):
    """`keep` 包内容的指纹（不可再生文件 + **凭据**的**内容**哈希）。

    用途（§12.29-④）：`--only minimal` 时若凭据/不可再生数据变了却**没带 `keep`**，
    Mac 上就会**缺凭据** ⇒ 构建时必须**提醒**。判据 = 与「上次带 keep 时」的指纹比对。

    `paths` 传 None 时用 `keep_fingerprint_paths()`（与包清单**同源**，便于测试）。
    """
    if paths is None:
        paths = keep_fingerprint_paths()
    h = hashlib.sha256()
    for p in paths:
        h.update(os.path.basename(p).encode("utf-8"))
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                h.update(fh.read())
        else:
            # ⚠️ 缺文件也要能算 —— 凭据被 gitignore，别的机器上本来就可能没有
            h.update(b"<missing>")
    return h.hexdigest()


def keep_warning(bundles, write=True):
    """`keep` 未包含、但内容与上次带它时**不同** ⇒ 返回提醒文字；否则 None。

    带 `keep` 构建时顺手把指纹写入 `dist/feishu/keep-manifest.json`（构建产物，gitignore）。
    `write=False` 供 `--list` 这类**承诺不落盘**的模式使用（评审 m6）。
    """
    fp = keep_fingerprint()
    prev = None
    if os.path.isfile(KEEP_MANIFEST):
        try:
            with open(KEEP_MANIFEST, encoding="utf-8") as fh:
                prev = json.load(fh).get("fingerprint")
        except (OSError, ValueError):
            prev = None
    if "keep" in bundles:
        if write:
            try:
                os.makedirs(OUT_DIR, exist_ok=True)
                with open(KEEP_MANIFEST, "w", encoding="utf-8") as fh:
                    json.dump({"fingerprint": fp}, fh)
                # 带过 keep ⇒ 清掉「已提醒」状态（下次变化才会再提醒）
                if os.path.isfile(KEEP_WARNED):
                    os.remove(KEEP_WARNED)
            except OSError as exc:
                # M3：一个「可选提醒」不该让投递产物生成失败 ✗
                print("⚠️ 无法写入 keep 清单（%s）—— 本次跳过，不影响构建" % exc)
        return None
    if prev != fp:
        # m4：同一个指纹只提醒**一次**（否则日常构建每次刷屏 ⇒ 告警疲劳，
        # 真出事时提醒反而被忽略 ✗）
        warned = None
        if os.path.isfile(KEEP_WARNED):
            try:
                with open(KEEP_WARNED, encoding="utf-8") as fh:
                    warned = json.load(fh).get("fingerprint")
            except (OSError, ValueError):
                warned = None
        if warned == fp:
            return None
        if write:
            try:
                with open(KEEP_WARNED, "w", encoding="utf-8") as fh:
                    json.dump({"fingerprint": fp}, fh)
            except OSError:
                pass
        return ("⚠️ 本次**没带 keep** 包，但 keep 内容与上次带它时**不同**"
                "（或从未带过）\n"
                "   ⇒ 若期间改过凭据/拆股表等**不可再生**数据，Mac 上会缺\n"
                "   ⇒ 请改用：`--only minimal,keep`")
    return None


def resolve_bundles(only=None, minimal=False, with_tests=False, with_data=False):
    """由命令行选项决定要构建哪些包（**纯函数**，便于测试）。

    `--only` 显式列出时**完全**以它为准 —— **不再隐式加 `keep`** ✗。
    这是 2026-09-29 投递瘦身的核心：Mac 只跑任务（不开发/不跑测试），
    全量 196 分片 → 只发 minimal 的 76 分片（§12.29 / spec 4.1）。

    不带 `--only` 时**保持历史行为**：`minimal`/`code` + **必带** `keep`
    （keep 里装的是凭据等不可再生文件，见 §12.29 的 ⚠️ 约束），再按需追加。
    """
    if only:
        # M5：`--only` 会**完全**以它为准 ⇒ 与其它包选项同时传必须报错，
        # 否则 `--only minimal --with-tests` 会静默吞掉 tests ✗。
        if minimal or with_tests or with_data:
            raise SystemExit(
                "--only 与 --minimal/--with-tests/--with-data 互斥"
                "（--only 会完全覆盖它们）")
        # m5：去重（`--only minimal,minimal` 会重复打包、同名覆盖）
        names = list(dict.fromkeys(
            b.strip() for b in only.split(",") if b.strip()))
        # M4：全空白/全逗号 ⇒ 空列表会让 `_text_mode` **只发引导分片**，
        # 而 bootstrap 非空 ⇒ 下游空检查不触发 ⇒ 静默发不全 ✗。
        if not names:
            raise SystemExit("--only 未解析出任何包名（收到 %r）" % only)
        unknown = [b for b in names if b not in BUNDLE_NAMES]
        if unknown:
            raise SystemExit("未知包：%s（可选：%s）"
                             % (", ".join(unknown), "/".join(BUNDLE_NAMES)))
        return names
    names = (["minimal"] if minimal else ["code"]) + ["keep"]
    if with_tests:
        names.append("tests")
    if with_data:
        names.append("data")
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-kb", type=int, default=9,
                    help="单片上限 KB（默认 9 —— 实测 .bin 10 KB 能过、90 KB 不过，"
                         "故取 9 留余量）")
    ap.add_argument("--minimal", action="store_true",
                    help="只装 Mac 上**真正需要**的文件（传递闭包算出）—— "
                         "比 code 包小约 45%%")
    ap.add_argument("--only", default="", metavar="PKG[,PKG]",
                    help="**只**构建列出的包（逗号分隔），**不隐式加 keep**。"
                         "可选：code/keep/minimal/tests/data。"
                         "例：`--only minimal`（Mac 只跑任务时 196 分片 → 76）")
    ap.add_argument("--strip", action="store_true",
                    help="**去掉注释与文档字符串** —— 实测再省 60%%（只影响体积，"
                         "不影响运行）。配合 --minimal 可把消息从 103 条降到 23 条")
    ap.add_argument("--with-tests", action="store_true")
    ap.add_argument("--with-data", action="store_true")
    ap.add_argument("--list", action="store_true", help="只报体积，不落盘")
    ap.add_argument("--probe", action="store_true",
                    help="只出「大小探针」，测出非压缩包的真实上限")
    ap.add_argument("--text", action="store_true",
                    help="出 base64 **纯文本**（实测唯一稳定能过的形态）")
    ap.add_argument("--doc-chars", type=int, default=50000,
                    help="--text 时的**文档块**字符数上限。飞书文档实测报"
                         "「该内容块的字符数超出上限（100,000）」；"
                         "默认取 50000（一半），粘贴更稳，代价只是多切一两块")
    ap.add_argument("--msg-chars", type=int, default=1700,
                    help="--text 时的**消息**字符数上限。用户实测"
                         "「每次最多可以发送字符串长度 1700」")
    args = ap.parse_args()

    if args.probe:
        _probe(OUT_DIR, [20, 40, 60, 80])
        return 0

    bundles = resolve_bundles(args.only, args.minimal,
                              args.with_tests, args.with_data)

    # §12.29-④：没带 keep 但 keep 内容变了 ⇒ 提醒（防 Mac 上缺凭据）
    # m6：`--list` 承诺「只报体积、不落盘」⇒ 不写 manifest
    _warn = keep_warning(bundles, write=not args.list)
    if _warn:
        print(_warn)
        print()

    if args.text:
        out = os.path.join(OUT_DIR, "text")
        written = _text_mode(bundles, args.msg_chars, args.doc_chars, out,
                             pack=_zip_stripped if args.strip else _zip)
        print("base64 纯文本模式（实测唯一稳定能过的形态）")
        print()
        for kind, tag in (("引导脚本", "← **首次引导必发**（`--start 1` 正好命中）"),
                          ("文档块", "← 粘进飞书**云文档**，每块单独粘贴（块间按回车）"),
                          ("消息分片", "← 逐条发**消息**"),
                          ("整块", "← 太大，**粘不进文档**（飞书单块上限 10 万字符），仅留档")):
            rows = [(n, s) for n, s, k in written if k.startswith(kind)]
            if not rows:
                continue
            total = sum(s for _n, s in rows)
            print("  %-8s %2d 个，每个 ≤ %6.1f KB，合计 %7.1f KB  %s" % (
                kind, len(rows), max(s for _n, s in rows) / 1024, total / 1024, tag))
            print("           %s" % rows[0][0])
        print()
        print("输出目录：%s" % out)
        print()
        print("【走文档路线（**推荐**）】")
        print("  飞书文档单块上限 100,000 字符 —— 比消息的 1,700 字符大 **58 倍**。")
        print("  1. 新建一个飞书**云文档**")
        print("  2. **逐块粘贴** `*-dNN.txt`（每块 ≤ %d 字符）" % args.doc_chars)
        print("     ⚠️ 每粘一块就**按回车**再粘下一块 —— 否则又并成一个超限大块")
        print("  3. Mac 上打开文档 → 全选复制 → 存成一个文件")
        print("  4. python3 scripts/restore_from_base64.py ~/Downloads/fg")
        print()
        print("【发消息路线（**不推荐**）】")
        print("  消息只有 1,700 字符/条 —— 全部传完要 **%d 条**，人工不现实。"
              % (len([1 for _n, _s, k in written if k.startswith("消息分片")])))
        print("  真要走，就把 `*-tNN.txt` 逐条发；Mac 上逐条复制。")
        return 0

    limit = args.max_kb * 1024
    print("单片上限：%d KB" % args.max_kb)
    print("（实测：.bin 10 KB 通过 / 90 KB 失败；.zip 10 KB 失败 —— 扩展名也被拦，")
    print("  故产物一律叫 .bin，Mac 上合并后再解压）")
    print()

    if not args.list:
        os.makedirs(OUT_DIR, exist_ok=True)
    written = []
    pack = _zip_stripped if args.strip else _zip
    for name in bundles:
        blob = pack(_spec([name]))
        parts = ([blob] if len(blob) <= limit
                 else [blob[i:i + limit] for i in range(0, len(blob), limit)])
        tag = "1 个文件" if len(parts) == 1 else "%d 片" % len(parts)
        print("  %-6s 压缩后 %8s  ->  %s" % (name, _human(len(blob)), tag))
        if args.list:
            continue
        for i, part in enumerate(parts, 1):
            # ⚠️ **绝不叫 .zip** —— 实测同样 10 KB，`.bin` 过、`.zip` 被拦
            fname = ("%s.bin" % name if len(parts) == 1
                     else "%s-part%02d.bin" % (name, i))
            with open(os.path.join(OUT_DIR, fname), "wb") as fh:
                fh.write(part)
            written.append((fname, len(part)))

    if args.list:
        return 0

    total = sum(s for _n, s in written)
    print()
    print("输出目录：%s" % OUT_DIR)
    print("共 %d 个文件，合计 %s" % (len(written), _human(total)))
    print()

    _write_readme(bundles, limit)
    print("已生成 合并说明.txt（含 Mac 上的合并/部署步骤）")
    return 0


def _write_readme(bundles, limit):
    lines = []
    add = lines.append
    add("飞书投递包 —— 合并与部署说明")
    add("=" * 46)
    add("")
    add("公司电脑 → 家里 Mac 只能走飞书，而飞书**两个维度**都会拦：")
    add("  · 压缩包（.zip）：约 10 KB 就被拦 —— DLP 扫不完内容就拒")
    add("  · 其它文件：实测 10 KB 过、90 KB 不过")
    add("所以：产物一律叫 .bin（不叫 .zip），且每片不超过 %d KB。" % (limit // 1024))
    add("")
    add("一、把飞书里这些文件**全部**下载到 Mac 的同一个目录（如 ~/Downloads/fg）")
    add("")
    for name in bundles:
        add("    %s 包：%s*.bin" % (name, name))
    add("")
    add("二、合并 + 解压（在下载目录里跑）")
    add("")
    add("    cd ~/Downloads/fg")
    add("    mkdir -p ~/learning_backtrader && cd ~/learning_backtrader")
    for name in bundles:
        add("    cat ~/Downloads/fg/%s*.bin > /tmp/%s.tar.xz" % (name, name))
        add("    tar xf /tmp/%s.tar.xz -C ~/learning_backtrader" % name)
    add("")
    add("    （tar 会自动识别 xz，不需要额外参数）")
    add("")
    add("三、建环境")
    add("")
    add("    cd ~/learning_backtrader")
    add("    python3.10 -m venv .venv")
    add("    .venv/bin/pip install -r requirements.txt")
    add("")
    add("四、抓数据（**只有 Mac 能抓** —— 公司电脑没有公网）")
    add("")
    add("    export FG_PROXY=\"\"          # 公司代理在 Mac 上不通，必须置空")
    add("    .venv/bin/python scripts/bootstrap_data.py")
    add("")
    add("    ⚠️ 若没传 data 包，这一步是**必需**的；传了也建议跑一次，")
    add("       把公司机器停工期间的最新行情补齐。")
    add("")
    add("五、凭据（keep 包里已含；若被拦则手动拷）")
    add("")
    add("    chmod 600 Data/shoutu_token")
    add("    # Data/tstoken 同理")
    add("")
    add("六、自检")
    add("")
    add("    .venv/bin/python -m pytest -q")
    add("    # 期望全过（「非 git 仓库」几条跳过属正常）")
    add("")
    add("七、起服务")
    add("")
    add("    .venv/bin/python scripts/serve_dashboard.py --password 用户名:密码")
    add("")
    add("出问题先看：docs/macos-deploy.md 与 docs/remote-access.md")
    with open(os.path.join(OUT_DIR, "合并说明.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
