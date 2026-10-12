#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用发送器：包装 feishu_send.main()，把中文会话名固定在这里（UTF-8 源码）。

为什么单独一个文件：.bat 由 cmd 按 OEM 代码页解析，写中文会话名会乱码 ⇒
中文只放在 .py 里，.bat 只传 ASCII 的包名。

用法（Windows，通常由 send_pkg.bat 调用）：
    py -3.10 scripts/send_pkg.py <包名> [feishu_send 的其余参数…]
    py -3.10 scripts/send_pkg.py sync_1010c --start 9      # 断了续发
"""
import os
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)

if len(sys.argv) < 2:
    sys.exit("用法：py -3.10 scripts/send_pkg.py <包名> [feishu_send 的其余参数…]")

CHAT = "海外投资助手"
pkg = sys.argv[1]
rest = sys.argv[2:]
sys.argv = ["feishu_send.py", "--pkg", pkg, "--chat", CHAT] + rest

import feishu_send  # noqa: E402

sys.exit(feishu_send.main())
