# -*- coding: utf-8 -*-
"""freshness 模块单测：刷新触发必须**受控**（节流 + 当天快照不覆盖）。

2026-10-07 新增。语义演进（用户新需求）：网页刷新时底层文件过期 → 后台触发
更新；但守猪待兔仍**绝不无条件抓取**（当天已有快照 → 跳过，防污染/耗额度）。
"""
import time

import pandas as pd
import pytest

from fg_system.dashboard import freshness


def test_stale_judgement():
    """行情文件过期判定：缺失=过期；滞后>3 天=过期；滞后≤3 天=新鲜。"""
    assert freshness._is_stale(None, pd.Timestamp("2026-10-06")) is True
    assert freshness._is_stale(
        pd.Timestamp("2026-10-03"), pd.Timestamp("2026-10-06")) is False
    assert freshness._is_stale(
        pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-06")) is True


def test_skip_refresh_when_prices_fresh(tmp_path, monkeypatch):
    """行情新鲜 → 不触发任何后台刷新（含守猪待兔）。"""
    # 构造一个"新鲜"的 prices.csv（最后日期 = 最近交易日）
    today = freshness._recent_trading_day()
    px_path = freshness.config.RAW_DIR
    monkeypatch.setattr(freshness.config, "RAW_DIR", str(tmp_path))
    monkeypatch.setattr(freshness.config, "DATA_DIR", str(tmp_path))
    p = tmp_path / "prices.csv"
    p.write_text("date,symbol,close\n%s,A,1.0\n" % today.date())
    triggered = []
    monkeypatch.setattr(freshness, "_run_refresh", lambda: triggered.append(1))
    assert freshness.check_and_refresh() is False
    assert triggered == []


def test_trigger_when_prices_stale(tmp_path, monkeypatch):
    """行情明显过期（>3 天）→ 后台触发刷新（异步线程）。"""
    freshness._state.update({"last_trigger": 0.0, "running": False})
    monkeypatch.setattr(freshness, "_log", lambda msg: None)  # 测试不污染真实日志
    px_path = tmp_path / "prices.csv"
    px_path.write_text("date,symbol,close\n2026-09-01,A,1.0\n")
    monkeypatch.setattr(freshness.config, "RAW_DIR", str(tmp_path))
    monkeypatch.setattr(freshness.config, "DATA_DIR", str(tmp_path))
    started = []
    monkeypatch.setattr(freshness, "_run_refresh",
                        lambda: (time.sleep(0.05), started.append(1)))
    assert freshness.check_and_refresh() is True
    time.sleep(0.15)
    assert started, "过期时应已触发后台刷新"


def test_throttle_prevents_repeated_trigger(tmp_path, monkeypatch):
    """节流：10 分钟内不重复触发（防每次刷新都打数据源）。"""
    freshness._state.update({"last_trigger": 0.0, "running": False})
    monkeypatch.setattr(freshness, "_log", lambda msg: None)  # 测试不污染真实日志
    px_path = tmp_path / "prices.csv"
    px_path.write_text("date,symbol,close\n2026-09-01,A,1.0\n")
    monkeypatch.setattr(freshness.config, "RAW_DIR", str(tmp_path))
    monkeypatch.setattr(freshness.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(freshness, "_run_refresh", lambda: time.sleep(0.05))
    assert freshness.check_and_refresh() is True
    time.sleep(0.1)
    assert freshness.check_and_refresh() is False   # 节流窗口内
