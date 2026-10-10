# -*- coding: utf-8 -*-
"""R-5 守卫：`signal/legacy.py` 是**兼容层**，生产代码不得依赖。

背景（WT-12 代码审查 R-5）：`legacy.py` 是 v1 的逐字副本，靠"向后兼容"名义
长期保留 ⇒ 会永久堆积。审查建议「加明确退役条件 / 标注 deprecated」。

本测试锁住**退役条件第 1 条**（可自动判定的那条）：引用 `legacy` 的只允许是
`fg_system/signal/__init__.py`（兼容重导出）与 `tests/**`。一旦**生产模块**
直接 import 它，说明有人把兼容层当新代码用 ⇒ 立刻失败。

为什么不用"断言 docstring 里有某句话"：那种断言改代码即可改绿、无判别力
（本仓已有此结论，见 tests/data/test_shoutu_record.py 的删除说明）。
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCAN_DIRS = ("fg_system", "scripts")
# 唯一允许引用 legacy 的生产文件（向后兼容重导出）
ALLOWED = {os.path.join("fg_system", "signal", "__init__.py")}

PAT = re.compile(r"(signal\.legacy|from\s+\.legacy|from\s+fg_system\.signal\s+import[^\n]*\blegacy\b)")


def test_legacy_marked_deprecated():
    from fg_system.signal import legacy
    assert getattr(legacy, "__deprecated__", False) is True, (
        "legacy 必须显式标注 __deprecated__，否则没人知道它可以退役")


def test_only_compat_shim_imports_legacy():
    offenders = []
    for root_dir in SCAN_DIRS:
        for dirpath, _dirs, files in os.walk(os.path.join(REPO, root_dir)):
            for name in files:
                if not name.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), REPO)
                rel_norm = rel.replace("\\", "/")
                # ① 兼容层自身：其 docstring 会提到自己的模块名（退役条件里）
                # ② 唯一允许的重导出文件
                if rel_norm == "fg_system/signal/legacy.py":
                    continue
                if rel_norm in {p.replace("\\", "/") for p in ALLOWED}:
                    continue
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    text = f.read()
                if PAT.search(text):
                    offenders.append(rel)
    assert not offenders, (
        "生产代码直接引用了兼容层 signal/legacy.py：%s\n"
        "新代码请用 market_signal / portfolio；若 v1 已无消费者，"
        "按 legacy.py docstring 的退役条件整体删除。" % offenders)
