# -*- coding: utf-8 -*-
"""贪婪恐惧指数交易纪律系统。"""
import sys

__version__ = "0.1.0"


def _make_console_safe():
    """让控制台输出**永不因编码问题崩溃**。

    【问题（2026-09-23 实测踩到）】
    Windows 控制台默认 **GBK**，而本系统大量用 `✅` / `❌` / `⚠️` 做输出标记
    —— 这三个字符 **GBK 编不了**，一旦 `print` 就 `UnicodeEncodeError` 把进程打挂：

        $ python scripts/check_deploy_set.py
        UnicodeEncodeError: 'gbk' codec can't encode character '\\u26a0'

    实测波及 **13 个文件**（scripts/ 下 8 个 + fg_system/ 下 5 个），
    包括 `serve_dashboard.py` —— 也就是每天要跑的那个。

    【修法】
    把 stdout/stderr 的 `errors` 改成 `replace`：编不了的字符降级成 `?`，
    **其余中文照常显示**，进程不再崩。

    比「统一改成 UTF-8」更稳：控制台若是 GBK，硬写 UTF-8 会变成乱码，
    而 `errors="replace"` 只牺牲那一个符号。

    【为什么放在包 `__init__` 而不是逐个脚本改】
    13 处逐个改必然漏（以后新增脚本还会再犯）。放在这里，
    **任何 `import fg_system` 的入口自动生效**。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:          # 被重定向的流 / 测试捕获对象可能不支持
            pass


_make_console_safe()
