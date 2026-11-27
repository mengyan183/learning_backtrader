# -*- coding: utf-8 -*-
"""美股交易日历（2026-11-27）。

【为什么需要】
  两处各有一套「节假日近似」，互不知道 ✗：
    · `invest_research._expected_index_date` —— 原来只跳周末
      ⇒ 感恩节（2026-11-26）被当成交易日 ⇒ 简报误报「指数落后 1 个交易日」✗
    · `check_freshness.MAX_LAG_DAYS = 3` —— 自然日容忍 3 天
      ⇒ 遇到「休市 + 周末」连在一起就不够 ✗
  ⇒ 统一到这里，用 `exchange_calendars` 的 **XNYS** 日历 ✓

【为什么不自己算】
  `pandas.tseries.holiday` 是**联邦**日历，不是 NYSE ✗：
    · 多算 2 天（哥伦布日 10-12、退伍军人节 11-11）—— NYSE 照常开市
    · 漏 Good Friday（2026-04-03）—— NYSE 休市
    · 没有 half-day（感恩节次日/平安夜 13:00 收市）
  ⇒ 用现成库，别自研复活节算法 ✓

【降级】
  未装 `exchange_calendars` 时退回「跳周末 + 硬编码 2026 休市日」✓
  不会崩，只是 2027 年之后会退回「只跳周末」（旧行为，不会更差）✓
"""
from __future__ import annotations

import datetime as dt

try:
    import exchange_calendars as _xcals          # noqa: F401
    HAS_XCALS = True
except ImportError:                              # pragma: no cover
    _xcals = None
    HAS_XCALS = False

#: 降级用的 NYSE 休市日（**只覆盖已列年份**）✓
#: 装好 `exchange_calendars` 后这里不再被使用，保留只为「没网装不上」时兜底 ✓
FALLBACK_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
}

_CAL = None


def _cal():
    """XNYS 日历（进程内缓存，构造一次约 200ms）✓"""
    global _CAL
    if _CAL is None and HAS_XCALS:
        _CAL = _xcals.get_calendar("XNYS")
    return _CAL


def is_session(d):
    """`d`（`date`/`str`）是否为 NYSE 交易日 ✓"""
    d = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])
    cal = _cal()
    if cal is not None:
        return bool(cal.is_session(str(d)))
    return d.weekday() < 5 and d.isoformat() not in FALLBACK_HOLIDAYS


def last_session(on_or_before):
    """`on_or_before` **当天或之前**最近的交易日 ✓（最多回溯 15 天）"""
    d = (on_or_before if isinstance(on_or_before, dt.date)
         else dt.date.fromisoformat(str(on_or_before)[:10]))
    cal = _cal()
    if cal is not None:
        start = d - dt.timedelta(days=15)
        sess = cal.sessions_in_range(str(start), str(d))
        if len(sess):
            return sess[-1].date()
    for _ in range(15):
        if is_session(d):
            return d
        d -= dt.timedelta(days=1)
    return d


def expected_index_date(today=None):
    """简报 05:30 跑 ⇒ 应拿到**上一个交易日**的收盘数据（美股 T-1）✓

    2026-11-27 实测：`today=11-27`（周五）⇒ 返回 **11-25**
      （11-26 感恩节休市）✓
    """
    return last_session((today or dt.date.today()) - dt.timedelta(days=1))


def is_half_day(d):
    """`d` 是否为**半天市**（13:00 ET 收市）✓

    ⚠️ 降级模式下恒 `False` —— 无法可靠判断，宁可不说 ✓
    """
    cal = _cal()
    if cal is None:
        return False
    d = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])
    try:
        return bool(cal.is_early_close(str(d)))
    except (AttributeError, ValueError):
        return False
