# -*- coding: utf-8 -*-
"""守猪待兔历史的**产出校验**（2026-11-25 用户裁定方案 C）。

【为什么需要】
  `stock_emotion/history` 端点对**全部标的**返回 `data: []`（实测 2026-11-24）✗
  ⇒ `shoutu_history.csv` 永久停在 2026-10-14 ✗
  而抓取链路是**两层静默**：
    ① `fetch_shoutu_history.py:284` 无条件 `return 0` ✗
    ② `shoutu_history_daily.sh` 无条件 `exit 0` ✗
  ⇒ 41 天没人发现 ✗

【为什么选「产出校验」而不是改 rc】
  · `StartCalendarInterval` 任务失败，launchd **不重试** ✗
  · `report_daily_failures.py` 只读每日链，**不看**独立 plist 的退出码 ✗
  ⇒ 改了 rc 仍然没人知道 ✗
  ⇒ 改看**数据本身**：rc 会骗人，数据不会 ✓
"""
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from fg_system.data import loader  # noqa: E402


def _mk(tmp_path, dates):
    p = tmp_path / "shoutu_history.csv"
    pd.DataFrame({"date": dates, "symbol": ["YINN"] * len(dates),
                  "score": [-90.0] * len(dates)}).to_csv(p, index=False)
    return str(p)


def test_fresh_not_stale(tmp_path):
    """1 天前 ⇒ 不算停更 ✓。"""
    p = _mk(tmp_path, ["2026-11-24"])
    text, stale = loader.shoutu_history_banner(p, today="2026-11-25")
    assert stale is False, text
    assert "✓" in text and "1 天前" in text, text


def test_stale_over_threshold(tmp_path):
    """超过 7 天 ⇒ 报停更 ✓（真实情况是 42 天）。"""
    p = _mk(tmp_path, ["2026-10-14"])
    text, stale = loader.shoutu_history_banner(p, today="2026-11-25")
    assert stale is True, text
    assert "42 天" in text, text
    assert "不可信" in text, text


def test_exactly_threshold_not_stale(tmp_path):
    """正好 7 天 ⇒ **不算**停更（阈值是「超过」才报）✓。"""
    p = _mk(tmp_path, ["2026-11-18"])
    _text, stale = loader.shoutu_history_banner(p, today="2026-11-25")
    assert stale is False


def test_missing_file_is_stale(tmp_path):
    """文件缺失 ⇒ 视为**更严重**的停更 ✓。"""
    text, stale = loader.shoutu_history_banner(str(tmp_path / "nope.csv"),
                                               today="2026-11-25")
    assert stale is True
    assert "缺失" in text, text


def test_age_days_returns_pair(tmp_path):
    """`shoutu_history_age` 返回 `(last_date, days)` ✓。"""
    p = _mk(tmp_path, ["2026-11-20", "2026-11-22"])
    last, days = loader.shoutu_history_age(p, today="2026-11-25")
    assert str(last.date()) == "2026-11-22"
    assert days == 3


def test_threshold_is_seven_days():
    """阈值必须是 7 天（用户 2026-11-25 裁定）✓。"""
    assert loader.SHOUTU_HISTORY_STALE_DAYS == 7
