# -*- coding: utf-8 -*-
"""`scripts/fetch_pe_ratio.py` 的解析器（C2 ERP 估值锚的数据源）。

2026-10-30：FRED 无 PE 系列 ✗ ⇒ 改用 multpl.com 的 S&P500 PE / Shiller CAPE 月度表。
页面抓取**天然脆弱** ✗ ⇒ 这里锁住：
  1. 结构不对就**抛错**，不返回空表 ✓
  2. **带 `available_date`**（月末 + 1 个月）✓ —— 防止用当月 PE 算当月信号 ✗
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


def _monthly(n=108, start_year=1990):
    """生成 n 行月度数据（≥100 行才满足解析器的下限 ✓）。"""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return [("%s 1, %d" % (months[i % 12], start_year + i // 12), "20.0")
            for i in range(n)]


def test_parses_monthly_table():
    """正常两列月度表 ⇒ 解析出 date/pe ✓，按日期升序 ✓。"""
    mod = _load()
    rows = _monthly(108) + [("Nov 1, 1998", "24.50"), ("Dec 1, 1998", "25.10")]

    df = mod.parse_multpl(_html(rows), value_col="pe")

    assert len(df) == len(rows)
    assert list(df.columns) == ["date", "pe", "available_date"]
    assert df["date"].is_monotonic_increasing, "没按日期升序 ✗"
    assert df["pe"].iloc[-1] == pytest.approx(25.10)


def test_available_date_is_one_month_later():
    """`available_date` 必须 = 数据日 **+1 个月** ✓ —— 防前视偏差 ✗。

    月度 PE 通常在月末之后才发布；若下游按 `date` 对齐，
    就等于「用当月还没公布的 PE 算当月信号」✗。
    """
    mod = _load()
    # 1980 起 108 个月 ⇒ 到 1988-12，再追加 1998-11 保证它是最后一行 ✓
    rows = _monthly(108, start_year=1980) + [("Nov 1, 1998", "24.50")]

    df = mod.parse_multpl(_html(rows), value_col="pe")
    last = df.iloc[-1]

    assert last["date"] == pd.Timestamp("1998-11-01")
    assert last["available_date"] == pd.Timestamp("1998-12-01")


def test_value_column_name_is_series_specific():
    """CAPE 用 `value_col="cape"` ✓ —— 列名要和序列对应，别都叫 pe ✗。"""
    mod = _load()
    df = mod.parse_multpl(_html(_monthly(108)), value_col="cape")
    assert list(df.columns) == ["date", "cape", "available_date"]


def test_series_registry_has_both():
    """两条序列都要登记 ✓（PE + CAPE 对照）。"""
    mod = _load()
    assert set(mod.SERIES) == {"pe", "cape"}
    assert mod.SERIES["pe"][1] == "sp500_pe.csv"
    assert mod.SERIES["cape"][1] == "sp500_cape.csv"
    assert "shiller" in mod.SERIES["cape"][0].lower(), "CAPE 的 URL 不对 ✗"


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
