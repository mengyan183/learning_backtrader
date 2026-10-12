#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""往返校验：dist/feishu/text/<包名>-tNNN.txt → 解码 → 解包 → 与仓库原文件逐字节比对。

为什么需要：只报「已发出」不算证据。飞书传输有把 `+` 改写的先例（见 pack_one.py
文件头），base64 解码**不会报错**但字节已变 ⇒ 必须做往返 md5 比对才能证明内容无损。

用法（Windows）：
    py -3.10 scripts/verify_pkg.py sync_1010c AGENTS.md
    py -3.10 scripts/verify_pkg.py sync_1010b evolution/hypotheses.md scripts/evolve_approve.py
"""
import base64
import hashlib
import io
import os
import sys
import tarfile

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
TEXT_DIR = os.path.join(REPO, "dist", "feishu", "text")

# 自设输出编码：Windows 默认 GBK，print 非 ASCII 会直接崩（见 AGENTS.md §6.2）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_pieces(pkg):
    """按序号读回分片正文（###FG:包名:n/总###<b64>###FG:end###）。"""
    pieces = []
    for n in range(1, 1000):
        path = os.path.join(TEXT_DIR, "%s-t%03d.txt" % (pkg, n))
        if not os.path.exists(path):
            break
        parts = open(path, encoding="utf-8").read().strip().split("###", 3)
        if len(parts) < 3 or not parts[1].startswith("FG:%s:" % pkg):
            sys.exit("❌ 第 %d 片格式不对：%s" % (n, parts[1] if len(parts) > 1 else ""))
        pieces.append(parts[2])
    return pieces


def main():
    if len(sys.argv) < 3:
        sys.exit("用法：py -3.10 scripts/verify_pkg.py <包名> <文件1> [文件2 ...]")
    pkg = sys.argv[1]
    srcs = sys.argv[2:]

    pieces = load_pieces(pkg)
    if not pieces:
        sys.exit("❌ %s 里没有 %s 的分片；先跑 scripts/pack_many.py" % (TEXT_DIR, pkg))

    b64 = "".join(pieces).replace("-", "+").replace("_", "/")
    tf = tarfile.open(fileobj=io.BytesIO(base64.b64decode(b64)), mode="r:xz")
    got = {m.name: tf.extractfile(m).read() for m in tf.getmembers()}

    ok = True
    for rel in srcs:
        want = open(os.path.join(REPO, rel.replace("/", os.sep)), "rb").read()
        same = got.get(rel) == want
        ok &= same
        print("%s %-32s %6d 字节  md5=%s"
              % ("✓" if same else "✗", rel, len(want),
                 hashlib.md5(want).hexdigest()[:12]))

    print("-" * 64)
    print("包 %s | 片数 %d | 解包文件数 %d | 往返一致性：%s"
          % (pkg, len(pieces), len(got), "全部一致 ✓" if ok else "不一致 ✗"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
