#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公司端（Windows）最小打包脚本：单文件 → 飞书分片（URL-safe base64）。

【为什么 URL-safe（2026-10-08 实测根因）】
飞书消息传输对标准 base64 的 `+`/`/` 有转义风险（`+` 有被改写的先例，
结果 base64 解码正常但字节被换、xz 流损坏、解压报 Corrupt input data）。
⇒ 本脚本把 `+`→`-`、`/`→`_` 后再发；Mac 端 restore_from_base64._decode
   已做反向替换兼容（标准 base64 字符集不含 `-`/`_`，不误伤旧协议）。

【用法（Windows）】
    python scripts/pack_one.py --src tests/company_sync_test.py
    # → 生成 sync_pieces.txt（每行一片，带 ###FG: 标记，每条 ≤1500 字符）
    # → 打开文件，逐行复制，每条发一条飞书消息给「海外投资助手」

【Mac 端对应】
    .venv/bin/python scripts/fg_sync_ingest.py <分片目录>
"""

import argparse
import base64
import io
import os
import sys
import tarfile
import time

# URL-safe 字符映射：+ → - ，/ → _ （解码端在 restore_from_base64._decode 反向替换）
def _b64url(data: bytes) -> str:
    return base64.b64encode(data).decode().replace("+", "-").replace("/", "_")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True,
                    help="要同步的文件，必须是仓库内相对路径（如 tests/xxx.py、scripts/xxx.py）")
    ap.add_argument("--out", default="sync_pieces.txt",
                    help="输出分片文件（每行一片）")
    ap.add_argument("--max-chars", type=int, default=1500,
                    help="每条飞书消息的字符上限（实测 1700，留余量取 1500）")
    # ⚠️ 包名**只允许 [A-Za-z0-9_]** —— Mac 端 mac_bootstrap.sh 的标记正则是
    #    `###FG:([A-Za-z0-9_]+):(\d+)/(\d+)###` ⇒ 带 `-`/`.` 会**整包匹配不到** ✗。
    # 约定（2026-10-10）：`sync_<MMDD><序号字母>`，如 sync_1009a、sync_1009b。
    # 为什么要换名：同一个包名先后发两次 ⇒ Mac 端看到两个不同总数 ⇒ 判成
    #    「混了旧导出」⇒ **整包跳过**（连本该能进的那份也进不去）✗。
    ap.add_argument("--pkg", default="sync_" + time.strftime("%m%d"),
                    help="分片包名（###FG:包名:序号/总数###）；只允许 [A-Za-z0-9_]")
    args = ap.parse_args()

    src = args.src.replace("\\", "/")
    if src.startswith("/") or src.startswith("../") or src.startswith("..\\"):
        sys.exit("❌ --src 必须是仓库内相对路径（tar 内路径决定 Mac 端白名单）")
    if not os.path.isfile(src):
        sys.exit("❌ 找不到文件：%s" % src)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        data = open(src, "rb").read()
        info = tarfile.TarInfo(src)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    blob = buf.getvalue()
    b64 = _b64url(blob)

    pieces = [b64[i:i + args.max_chars] for i in range(0, len(b64), args.max_chars)]
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        for n, p in enumerate(pieces, 1):
            fh.write("###FG:%s:%d/%d###%s###FG:end###\n" % (args.pkg, n, len(pieces), p))

    print("打包完成：%s（%d 字节 xz → %d 片，每片 ≤%d 字符）" % (src, len(blob), len(pieces), args.max_chars))
    print("下一步：打开 %s，【每行一条消息】逐行复制发给飞书「海外投资助手」。别合并行、别漏行。" % args.out)


if __name__ == "__main__":
    main()
