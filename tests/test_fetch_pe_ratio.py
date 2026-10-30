# -*- coding: utf-8 -*-
"""`scripts/fetch_pe_ratio.py` 的解析器（C2 ERP 估值锚的数据源）。

2026-10-30：FRED 无 PE 系列 ✗ ⇒ 改用 multpl.com 的 S&P500 PE 月度表。
页面抓取**天然脆弱** ✗ ⇒ 这里锁住「结构不对就**抛错**，不返回空表」✓
（空表会被下游当成「没有估值数据」而静默跳过 ✗）。
"""
import importlib.util
import os

import pandas as pd
import pytest

from fg_system import config


def _load():
    spec = importlib.util.spec_from_file_location(
        "fetch_pe_ratio", os.path.join(config.ROOT, "scripts", "fetch_pe_ratio.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _html(rows):
    body = "".join("<tr><td>%s</td><td>%s</td></tr>" % (d, v) for d, v in rows)
    return ("<html><body><table><thead><tr><th>Date</th><th>Value</th></tr>"
            "</thead><tbody>%s</tbody></table></body></html>" % body)


def test_parses_monthly_table():
    """正常两列月度表 ⇒ 解析出 date/pe ✓，并按日期升序 ✓。"""
    mod = _load()
    rows = [("Jan 1, 2026", "24.50"), ("Feb 1, 2026", "25.10"),
            ("Mar 1, 2026", "23.80")]
    # 补足 ≥100 行（解析器要求月度序列至少上百行 ✓）
    rows = [("%s 1, %d" % (m, 1990 + i // 12), "20.0")
            for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] * 9)
            ] + rows

    df = mod.parse_multpl(_html(rows))

    assert len(df) == len(rows)
    assert list(df.columns) == ["date", "pe"]
    assert df["date"].is_monotonic_increasing, "没按日期升序 ✗"
    assert df["pe"].iloc[-1] == pytest.approx(23.80)


def test_raises_when_structure_changed():
    """页面结构变了 ⇒ **必须抛错** ✓（不能返回空表静默通过 ✗）。"""
    mod = _load()
    with pytest.raises(RuntimeError, match="页面结构可能已变"):
        mod.parse_multpl("<html><body><p>no table here</p></body></html>")


def test_raises_when_table_too_short():
    """表太短（<100 行）⇒ 也抛错 ✓ —— 月度序列不该这么短，多半解析错了 ✗。"""
    mod = _load()
    with pytest.raises(RuntimeError):
        mod.parse_multpl(_html([("Jan 1, 2026", "24.5"), ("Feb 1, 2026", "25.1")]))
