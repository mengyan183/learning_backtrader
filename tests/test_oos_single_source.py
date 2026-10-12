# -*- coding: utf-8 -*-
"""WT-18：OOS 起点单一来源一致性测试。

背景（团队评审 2026-10-12 §3①）：「OOS 只验收一次」这条纪律此前**无法机械验证**，
因为仓库里同时存在**两套** OOS 起点：
  - `fg_system/config.py` 的 `OOS_START`（纪律声明口径）；
  - 研究脚本硬编码的日期（研究产物口径，声称「与 baseline meta 同口径」）。

本测试做两件事：
  1. **扫描全仓源码**，断言**无字面日期硬编码残留**出现在需要读 OOS 起点的脚本里
     （排除 `evolution/` 产物、`docs/` 文档、`tests/` 自身）；
  2. 断言研究脚本的 OOS 起点**确实等于** `evolution/baseline.json` 的
     `meta.is_oos.oos_start`（单一来源），而非另写一份常量。

注：`config.OOS_START` 与 `baseline.json` 的数字**不同是正常的**——前者是纪律声明
（先验固定），后者是研究产物（数据派生 80/20）。本测试**不**断言二者相等，
只断言**研究脚本与 baseline.json 同源**。见 `fg_system/evo_meta.py`。
"""
import importlib.util
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要纳入「无硬编码」扫描的源码目录（相对 REPO）。
SCAN_DIRS = ["fg_system", "scripts"]
# 排除目录（产物/文档/测试自身）：产物里保留历史日期是正确的。
EXCLUDE_DIRS = {"evolution", "docs", "tests", ".git", "__pycache__",
                ".venv", "venv", "node_modules", "Data"}
# 被扫描的源码后缀。
SCAN_EXTS = (".py",)

# 硬编码的「研究产物 OOS 起点」特征：月份为 10 的 2024 年日期（曾硬编码为 2024-10-01）。
HARDCODE_RE = re.compile(r"2024-10-0\d")


def _iter_source_files():
    for d in SCAN_DIRS:
        root = os.path.join(REPO, d)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [x for x in dirnames if x not in EXCLUDE_DIRS]
            for fn in filenames:
                if fn.endswith(SCAN_EXTS):
                    yield os.path.join(dirpath, fn)


def test_no_hardcoded_oos_start_in_source():
    """全仓源码（排除 evolution/docs/tests）不得残留 `2024-10-0x` 硬编码。"""
    offenders = []
    for path in _iter_source_files():
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if HARDCODE_RE.search(line):
                    offenders.append("%s:%d: %s" % (rel, i, line.strip()))
    assert not offenders, (
        "发现 OOS 起点硬编码残留（应改读 config.OOS_START 或 baseline.json）：\n"
        + "\n".join(offenders))


def _load(script_rel):
    path = os.path.join(REPO, script_rel)
    spec = importlib.util.spec_from_file_location(
        os.path.splitext(os.path.basename(script_rel))[0], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_evolve_scripts_read_oos_start_from_baseline_meta():
    """研究脚本的 OOS 起点必须来自 baseline.json 的 meta.is_oos（单一来源）。"""
    from fg_system import evo_meta

    expected = evo_meta.oos_start()
    for script in ("scripts/evolve_propose.py", "scripts/evolve_variant.py"):
        mod = _load(script)
        assert getattr(mod, "OOS_START", None) == expected, (
            "%s 的 OOS_START 未与 baseline.json meta 同源" % script)


def test_baseline_meta_declares_is_oos():
    """research 产物必须显式声明 80/20 划分口径与起止日。"""
    from fg_system import evo_meta

    meta = evo_meta.load_baseline_meta()
    is_oos = meta["is_oos"]
    assert is_oos["method"] == "time_80_20"
    assert is_oos["is_end"] < is_oos["oos_start"]
