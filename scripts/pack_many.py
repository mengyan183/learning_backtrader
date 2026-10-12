#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多文件打包 → 飞书分片（写入 dist/feishu/text/<包名>-tNNN.txt，供 feishu_send.py 发送）。

与 pack_one.py 的分工：
    pack_one.py  单文件 → sync_pieces.txt（手工逐条复制的老流程）
    pack_many.py 多文件 → dist/feishu/text/（可直接被 feishu_send.py --pkg 发送）

用法（Windows）：
    py -3.10 scripts/pack_many.py sync_1010c AGENTS.md
    py -3.10 scripts/pack_many.py sync_1010d docs/windows-tasks.md scripts/foo.py

约定（与 pack_one.py 一致）：
    · 包名只允许 [A-Za-z0-9_]（Mac 端标记正则是 ###FG:([A-Za-z0-9_]+):(\\d+)/(\\d+)###）。
    · 同一包名重复发送是**幂等**的：Mac 端按 <包>_<序号> 逐片覆盖，总数一致即可。
    · 路径必须是仓库内相对路径（tar 内路径决定 Mac 端白名单）。
"""
import io
import os
import sys
import tarfile

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from pack_one import _b64url  # noqa: E402 —— 复用已验证编码器，避免两套实现分叉

# 自设输出编码：Windows 默认 GBK，print 非 ASCII 会直接崩（见 AGENTS.md §6.2）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = os.path.join(REPO, "dist", "feishu", "text")
MAX_CHARS = 1500


def main():
    if len(sys.argv) < 3:
        sys.exit("用法：py -3.10 scripts/pack_many.py <包名> <文件1> [文件2 ...]")
    pkg = sys.argv[1]
    srcs = sys.argv[2:]

    os.makedirs(OUT_DIR, exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for rel in srcs:
            path = os.path.join(REPO, rel.replace("/", os.sep))
            if not os.path.isfile(path):
                sys.exit("❌ 找不到：%s" % rel)
            data = open(path, "rb").read()
            info = tarfile.TarInfo(rel)   # mtime=0，与 pack_one.py 一致 ⇒ 可复现
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

    blob = buf.getvalue()
    b64 = _b64url(blob)
    pieces = [b64[i:i + MAX_CHARS] for i in range(0, len(b64), MAX_CHARS)]

    for n, piece in enumerate(pieces, 1):
        dst = os.path.join(OUT_DIR, "%s-t%03d.txt" % (pkg, n))
        with open(dst, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("###FG:%s:%d/%d###%s###FG:end###\n" % (pkg, n, len(pieces), piece))

    print("包名 %s：%d 个文件 → %d 字节(xz) → %d 片（每片 ≤%d 字符）"
          % (pkg, len(srcs), len(blob), len(pieces), MAX_CHARS))
    for rel in srcs:
        print("    %s  (%d 字节)"
              % (rel, os.path.getsize(os.path.join(REPO, rel.replace("/", os.sep)))))
    print("下一步：py -3.10 scripts/send_pkg.bat %s" % pkg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
