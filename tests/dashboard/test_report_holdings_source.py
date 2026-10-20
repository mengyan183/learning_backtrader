# -*- coding: utf-8 -*-
"""持仓页「系统」列的**来源标注**（2026-10-20 修）。

缺陷：底层数据不足时系统列回退**市场级**指数 ✗，但文案与个股分**格式完全一样**
（都是「系统 62 中性」）⇒ 用户**无法分辨** ✗。
修法：回退时标「（大盘）」✓；`fg` 为 None 时显示「系统 —」✓（原 `%.0f % None` 会 TypeError ✗）。
"""
import os
import re

import pandas as pd
import pytest

from fg_system.dashboard import report


@pytest.fixture
def env(tmp_path, monkeypatch):
    """2 只持仓：AXTX（底层 AXTI 有 900 行 ✓）/ CONL（底层 COIN 缺 ✗）。"""
    pos = pd.DataFrame([
        {"date": "2026-10-16", "account": "stock", "symbol": "AXTX",
         "name": "2倍做多AXTI", "qty": 48.0, "price": 20.6, "cost": 24.0,
         "market_value": 988.8, "notional": 988.8, "margin": None,
         "bucket": "system", "currency": "USD"},
        {"date": "2026-10-16", "account": "stock", "symbol": "CONL",
         "name": "2倍做多COIN", "qty": 600.0, "price": 6.37, "cost": 5.46,
         "market_value": 3822.0, "notional": 3822.0, "margin": None,
         "bucket": "system", "currency": "USD"},
    ])
    p = tmp_path / "positions.csv"
    pos.to_csv(p, index=False)
    monkeypatch.setattr(report.config, "POSITIONS_PATH", str(p))
    monkeypatch.setattr(report.config, "ACCOUNTS_PATH",
                        str(tmp_path / "no_accounts.csv"))

    dates = pd.date_range("2022-01-03", periods=900, freq="B")
    close = pd.Series(range(100, 1000), index=dates, dtype=float)
    prices = pd.DataFrame({"symbol": "AXTI", "date": dates,
                           "close": close.values})
    # `_holdings_block` 会读这些列 ⇒ 全给上（NaN 即可，除 fg_index）
    features = pd.DataFrame({
        "date": dates[-1:], "fg_index": [62.0], "zone": [3.0],
        "core_position": [0.3375], "ammo_position": [0.1333],
        "target_position": [0.3583], "drawdown": [0.05],
        "trend_blocked": [False], "circuit_breaker": [False],
        "greed_tier": ["—"], "vix_chg": [0.0],
        "funding_btc": [0.0], "funding_eth": [0.0],
    })
    return features, prices


def test_fallback_marks_market_source(env):
    """CONL 底层缺 ⇒ 回退大盘 ⇒ 必须标「（大盘）」✓；AXTX 有底层 ⇒ 不标 ✓。"""
    features, prices = env
    html = report._holdings_block(features, shoutu=None, prices=prices)
    assert html.count("（大盘）") == 1, "只应有一只标的被标为大盘回退"
    # AXTX 那格是个股分（无标注），CONL 那格带标注（档位名不硬编码）
    assert re.search(r"系统 62 \S+（大盘）", html)


def test_no_fallback_when_underlying_present(env):
    """把 CONL 的底层补进 prices ⇒ 两只都算个股分 ⇒ 不再出现「（大盘）」✓。"""
    features, prices = env
    dates = pd.date_range("2022-01-03", periods=900, freq="B")
    coin = pd.DataFrame({"symbol": "COIN", "date": dates,
                         "close": pd.Series(range(200, 1100), dtype=float).values})
    both = pd.concat([prices, coin], ignore_index=True)
    html = report._holdings_block(features, shoutu=None, prices=both)
    assert "（大盘）" not in html


def test_none_fg_does_not_crash(env):
    """`fg_index` 全 NaN ⇒ 回退分支的 `fg` 为 None ⇒ 原代码 `%.0f` 会 TypeError ✗。"""
    features, prices = env
    features = features.assign(fg_index=[None])
    html = report._holdings_block(features, shoutu=None, prices=prices)
    assert "系统 —" in html
