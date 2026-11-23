# -*- coding: utf-8 -*-
"""`update_prices` 的周末空转 + 与 `update_indices` 的解耦（2026-11-23）。

🔴 事故链（实测 `t-20261123-184328`）：
   周一早上本地已是**周五收盘** ⇒ `missing_ranges` 给出 `fromdate = 周六` ✗
   Nasdaq 对周末区间返回 **HTTP 200 + 空表** ✗
   `fetch_symbol` 把空表当**限流** ⇒ 3 轮 × 2 个 assetclass = 6 次请求/标的 ✗
   实测 **36 秒/标的** ⇒ 39 只跑满 180s 预算后抛 `RuntimeError` ✗
   每日链里紧跟的 `update_indices()`（写 `vix.csv`）**永远执行不到** ✗
   ⇒ `vix.csv` 卡在 11-18，简报连报「六因子缺 2 个」✗
"""
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system.data import fetch as f  # noqa: E402


class _Splits:
    """替身：避免测试去读真实 `splits.csv` ✓。"""

    @staticmethod
    def load():
        return None

    @staticmethod
    def apply(df, _s):
        return df


def test_update_indices_runs_even_if_prices_fails(monkeypatch):
    """`update_prices` 抛异常时，`update_indices` **仍必须执行** ✓。

    这是 `vix.csv` 能更新的唯一前提 —— 两者串在同一条 `-c` 里时，
    前者的异常会把后者整段吞掉 ✗
    """
    called = []

    def boom():
        raise RuntimeError("update_prices 提前结束（超过 180s 预算）")

    monkeypatch.setattr(f, "update_prices", boom)
    monkeypatch.setattr(f, "update_indices", lambda: called.append("indices"))

    out = f.update_prices_and_indices()
    assert called == ["indices"], "update_indices 被前一步的异常连坐了 ✗"
    assert "RuntimeError" in out["prices"]
    assert out["indices"] == "ok"


def test_weekend_fromdate_is_skipped(tmp_path, monkeypatch):
    """`fromdate` 落在周末 ⇒ **一次请求都不发** ✓。

    本地最后一笔是周五 ⇒ 下一天是周六 ⇒ Nasdaq 不可能有数据 ⇒
    发出去只会换来「200 + 空表」，被当限流重试 6 次 × 6 秒 ✗
    """
    p = tmp_path / "prices.csv"
    pd.DataFrame({
        "date": pd.to_datetime(["2026-11-19", "2026-11-20"]),   # 周四、周五
        "symbol": ["SPY", "SPY"],
        "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
        "close": [1.0, 1.0], "volume": [1, 1],
    }).to_csv(p, index=False)

    hits = []

    def _fake_fetch(sym, **_kw):
        hits.append(sym)
        return pd.DataFrame(columns=f.PRICE_COLUMNS)

    monkeypatch.setattr(f, "fetch_symbol", _fake_fetch)
    monkeypatch.setattr(f, "splits", _Splits)

    _merged, added = f.update_prices(path=str(p), symbols=["SPY"], sleep=0)
    assert hits == [], "周末区间不该发请求（会触发 6 次重试 × 6 秒）✗"
    assert added["SPY"] == 0


def test_weekday_fromdate_still_fetches(tmp_path, monkeypatch):
    """工作日起点**不得**被误跳过 ✓（本地最后一笔是周四 ⇒ 周五要抓）。"""
    p = tmp_path / "prices.csv"
    pd.DataFrame({
        "date": pd.to_datetime(["2026-11-18", "2026-11-19"]),   # 周三、周四
        "symbol": ["SPY", "SPY"],
        "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
        "close": [1.0, 1.0], "volume": [1, 1],
    }).to_csv(p, index=False)

    hits = []

    def _fake_fetch(sym, **_kw):
        hits.append(sym)
        return pd.DataFrame(columns=f.PRICE_COLUMNS)

    monkeypatch.setattr(f, "fetch_symbol", _fake_fetch)
    monkeypatch.setattr(f, "splits", _Splits)

    f.update_prices(path=str(p), symbols=["SPY"], sleep=0)
    assert hits == ["SPY"], "工作日起点被误跳过了 ✗"


def test_market_holiday_fromdate_is_skipped(tmp_path, monkeypatch):
    """法定假日（**工作日**）同样必须跳过 ✓。

    2026-11-26 是感恩节（周四）⇒ `weekday()` 拦不住 ⇒ 只能靠假日表 ✓
    """
    p = tmp_path / "prices.csv"
    pd.DataFrame({
        "date": pd.to_datetime(["2026-11-24", "2026-11-25"]),   # 周二、周三
        "symbol": ["SPY", "SPY"],
        "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
        "close": [1.0, 1.0], "volume": [1, 1],
    }).to_csv(p, index=False)

    hits = []
    monkeypatch.setattr(f, "fetch_symbol",
                        lambda sym, **kw: hits.append(sym) or pd.DataFrame(
                            columns=f.PRICE_COLUMNS))
    monkeypatch.setattr(f, "splits", _Splits)

    f.update_prices(path=str(p), symbols=["SPY"], sleep=0)
    assert hits == [], "感恩节（周四）没被跳过 ⇒ 会跑满 6 次重试 ✗"


def test_holiday_table_covers_current_and_next_year():
    """节假日表必须覆盖**今年和明年** ✓。

    🔴 忘了更新不会报错，只会静默退化回「假日跑满 6 次重试」✗
    ⇒ 用断言把它变成**会响的**失败 ✓
    """
    import datetime as dt

    y = dt.date.today().year
    for year in (y, y + 1):
        got = [d for d in f.US_MARKET_HOLIDAYS if d.startswith(str(year))]
        assert len(got) >= 9, ("%d 年的美股休市日只配了 %d 条 ✗ "
                               "⇒ 假日会跑满 6 次重试" % (year, len(got)))
