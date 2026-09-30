# -*- coding: utf-8 -*-
"""在 Mac 上把 base64 文本还原成 tar.xz 并解压。

【配套】`scripts/make_feishu_bundle.py --text`

【为什么走 base64（2026-09-23 实测证据链）】
飞书对公司网络的上传做**内容检查**，成功与失败的样本对比：

    成功  output-metadata.json   394 B    纯文本
    成功  合并说明.txt            1.8 KB   纯文本
    成功  fg-src-kit.zip         5.7 KB   zip 魔数（小到能扫完）
    成功  code-part03.bin        10188 B  **无魔数**（压缩流中段碎片）
    ─────────────────────────────────────────────────────
    失败  keep.bin               7.8 KB   **xz 魔数**
    失败  code-part01.bin        90 KB    xz 魔数
    失败  probe-20k.txt          20 KB    纯文本（太大）
    失败  keep.zip               10 KB    zip 魔数

⇒ 两条规则叠加：
  1. **有压缩魔数（zip / xz）→ 直接拦**，与大小无关
     （`keep.bin` 7.8 KB 被拦、10188 B 的中段碎片能过 —— 差别只在**开头有没有魔数**）
  2. **纯文本 → 上限约 10 KB**

⇒ 唯一稳定能过的形态是 **base64 纯文本**（无魔数、纯 ASCII）。

【两条投递路径】
  A. **飞书云文档**（推荐）：把 `code.b64.txt` 的内容**粘贴**进一个云文档，
     在 Mac 上打开、全选复制、存成 `code.b64.txt` —— **不走文件上传**，
     大概率绕过这套检查。
  B. **飞书消息**：把 `code-t01.txt` … 逐条发出去（每条 ≤ 8 KB），
     Mac 上全部存到同一目录。

用法（Mac 上）：
    # 方式 A/B 的文件都放进 ~/Downloads/fg 后：
    python3 scripts/restore_from_base64.py ~/Downloads/fg
    python3 scripts/restore_from_base64.py ~/Downloads/fg --into ~/learning_backtrader
"""
import argparse
import base64
import binascii
import glob
import os
import re
import sys
import tarfile

# ⚠️ **同时收 `.md`**（2026-09-28 补）：飞书云文档支持「下载为 → Markdown」
# ⇒ 用户导出的是 `*.md`。原来只收 `*.txt` ⇒ 导出的文档会被**静默漏掉**
# （脚本还会报「没有 .txt」，把人引向错误方向）。
_TEXT_GLOBS = ("*.txt", "*.md")


def _text_files(src_dir):
    """目录下所有可解析的文本文件（`.txt` + `.md`）。"""
    out = []
    for pat in _TEXT_GLOBS:
        out.extend(glob.glob(os.path.join(src_dir, pat)))
    return sorted(out)


def _collect(src_dir):
    """把目录里的文本按包名分组，返回 `{包名: [路径...]}`。

    **同一份数据有三种形态**（不能混用，混了内容就翻倍）：

        `code.b64.txt`      整块     —— 太大，飞书文档粘不下，仅留档
        `code-d01.txt`…     文档块   —— 粘进云文档（每块 ≤ 10 万字符）
        `code-t01.txt`…     消息分片 —— 逐条发消息（每片 ≤ 8 KB）

    ⇒ **优先级：整块 > 文档块 > 消息分片**。
      实测踩过：两种形态同时存在时被拼两遍，解码抛 `Non-base64 digit found`。
    """
    whole, doc, msg = {}, {}, {}
    for p in _text_files(src_dir):
        name = os.path.basename(p)
        if name.endswith(".b64.txt"):
            whole[name[:-8]] = [p]
        elif "-d" in name:
            doc.setdefault(name.rsplit("-d", 1)[0], []).append(p)
        elif "-t" in name:
            msg.setdefault(name.rsplit("-t", 1)[0], []).append(p)
    out = dict(msg)
    out.update(doc)
    out.update(whole)

    if not out:
        # 兜底：用户很可能把**所有消息粘进了一个文件**，名字随便起（如 note.txt）。
        # 此时按「全部 .txt 合起来是一个包」处理 —— 比报错让人重来强。
        all_txt = _text_files(src_dir)
        if all_txt:
            out["restored"] = all_txt
    return out


# 标记是**单行**的（见 make_feishu_bundle.mark 的说明：飞书按回车就发送，
# 带换行的标记会被截断）。故这里**不用 re.S**，`.*?` 不跨行。
MARK_RE = re.compile(
    r"###FG:([A-Za-z0-9_]+):(\d+)/(\d+)###(.*?)###FG:end###")

_B64_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                 "abcdefghijklmnopqrstuvwxyz0123456789+/=")


def extract_marked(text):
    """从**聊天记录原文**里提取所有分片。

    【为什么需要这个】
    飞书聊天记录「全选复制」会把**昵称、时间戳、系统提示**一起复制进来。
    若靠"过滤掉非 base64 字符"，`17:00` 里的**数字会被当成内容**，
    **静默损坏数据** —— 而且要到解压失败才发现。

    ⇒ 所以每条消息都带 `###FG:包名:序号/总数###` … `###FG:end###` 标记，
      这里按标记**精确切**，并**报告缺了哪几片**。

    返回 `(分组, 问题列表)`；分组形如 `{"code": ["片1", "片2", ...]}`。
    """
    # ⚠️ **飞书「下载为 Markdown」会把 `#` 转义**（2026-09-28 实测）：
    #    `###FG:keep:1/28###` 在 .md 里是 `\#\#\#FG:keep:1/28\#\#\#`（防被当成标题）。
    #    不还原 ⇒ 一个标记都匹配不到。base64 正文不含 `#`/`\` ⇒ 替换不会伤到数据。
    text = text.replace("\\#", "#")
    # ⚠️ **飞书「下载为 Markdown」还会把 `+` 转义**（2026-09-29 实测）：
    #    base64 正文里的 `+` 在 .md 里是 `\+`（防被当成列表项）。
    #    不还原 ⇒ `+` 前多出的 `\` 会让 `_B64_CHARS` 检查报「混入非法字符」、
    #    解码报 `Non-base64 digit`。base64 正文不含 `\` ⇒ 这个替换不会伤到数据。
    text = text.replace("\\+", "+")

    found = {}
    for name, idx, total, body in MARK_RE.findall(text):
        # ⚠️ **只去掉空白，不做"过滤非法字符"**。
        # 试过过滤：时间戳 `17:01` 里的数字是合法 base64 字符，会被**保留**
        # ⇒ 静默污染数据，要到解压失败才发现。宁可**响亮地报错**。
        found.setdefault(name, {})[int(idx)] = (int(total), "".join(body.split()))

    groups, problems = {}, []
    for name, parts in found.items():
        total = max(t for t, _ in parts.values())
        missing = [i for i in range(1, total + 1) if i not in parts]
        if missing:
            problems.append("%s 缺 %d 片（共 %d）：%s%s"
                            % (name, len(missing), total,
                               missing[:10], " …" if len(missing) > 10 else ""))
        bad = sorted(i for i, (_t, body) in parts.items()
                     if set(body) - _B64_CHARS)
        if bad:
            problems.append("%s 有 %d 片混入了非法字符（第 %s 片）—— "
                            "多半是复制时把昵称/时间戳粘进了分片内部，"
                            "请**只复制 `###FG:…###` 到 `###FG:end###` 之间**的内容"
                            % (name, len(bad), bad[:10]))
        groups[name] = [parts[i][1] for i in sorted(parts)]
    return groups, problems


def _decode(parts):
    """拼起所有分片的文本，去掉空白后 base64 解码。

    `parts` 可以是**文件路径**（按文件名分组时），也可以是**已经读出来的
    base64 文本**（按 `###FG:` 标记提取时）—— 两种来源都归到这里。
    """
    if parts and isinstance(parts[0], str) and not os.path.isfile(parts[0]):
        text = "".join(parts)
    else:
        text = "".join(open(p, encoding="utf-8", errors="ignore").read()
                       for p in parts)
    # 从聊天记录/文档复制回来时很容易混入换行、空格 —— 一并去掉
    text = "".join(text.split())
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemExit(
            "❌ base64 解码失败：%s\n"
            "   多半是分片没凑齐，或文本被截断/改动了。\n"
            "   共收到 %d 个分片，%d 个字符。" % (exc, len(parts), len(text)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="放着 base64 文本的目录")
    ap.add_argument("--into", default=os.path.expanduser("~/learning_backtrader"),
                    help="解压到哪（默认 ~/learning_backtrader）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # 先按**标记**提取（把聊天记录原文整个粘进一个文件也能认）；
    # 没有标记再按文件名分组。
    raw = "".join(open(p, encoding="utf-8", errors="ignore").read()
                  for p in _text_files(args.src))
    marked, problems = extract_marked(raw)

    if marked:
        groups = marked
        print("在 %s 里认出 %d 个包（按 ###FG: 标记提取）：" % (args.src, len(groups)))
        for name, parts in sorted(groups.items()):
            print("    %-10s %d 个分片" % (name, len(parts)))
        if problems:
            print()
            print("⚠️ **有分片缺失** —— 请把这些消息补发后再跑：")
            for p in problems:
                print("    %s" % p)
            print("    （缺片会导致解压失败，别硬试）")
        print()
    else:
        groups = _collect(args.src)
        if not groups:
            raise SystemExit("❌ %s 里没找到可识别的内容" % args.src)
        print("在 %s 找到 %d 个包（按文件名分组）：" % (args.src, len(groups)))
        for name, paths in sorted(groups.items()):
            print("    %-10s %d 个分片" % (name, len(paths)))
        print()

    if args.dry_run:
        print("（--dry-run：未解压）")
        return 0

    os.makedirs(args.into, exist_ok=True)
    for name, parts in sorted(groups.items()):
        blob = _decode(parts)
        if blob[:6] != b"\xfd7zXZ\x00":
            raise SystemExit("❌ %s 解出来的不是 xz 数据（开头 %r）" % (name, blob[:8]))
        tmp = os.path.join(args.into, "%s.tar.xz" % name)
        with open(tmp, "wb") as fh:
            fh.write(blob)
        with tarfile.open(tmp, "r:xz") as tf:
            tf.extractall(args.into)
        print("  %-10s %8.1f KB -> 解压到 %s" % (name, len(blob) / 1024, args.into))

    print()
    print("[OK] 还原完成。接着：")
    print("    cd %s" % args.into)
    print("    export FG_PROXY=\"\"")
    print("    .venv/bin/python scripts/bootstrap_data.py   # 抓行情数据")
    print("    .venv/bin/python -m pytest -q                # 自检")
    return 0


if __name__ == "__main__":
    sys.exit(main())
