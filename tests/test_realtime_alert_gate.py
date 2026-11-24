# -*- coding: utf-8 -*-
"""盘中异动告警的三道闸（2026-11-23 事故）。

🔴 事故现场（用户截图）：
   04:36 推送了 4 条「盘中异动」，其中
     CRCG −5.3%（实时价 4.28，**2026-11-20T10:46**）
     GDXU −11.9%（实时价 47.16，**2026-11-20T10:46**）
   —— 那是 **4 天前**的数据；且这两个标的早已清仓 ✗

根因：`check_alert` 只判「现在是不是交易时段」✗
     ① 不判**是否持仓** ⇒ 已清仓标的（无订阅、无行情）也告警
     ② 不判**数据新鲜度** ⇒ 冻结价格在每次进交易时段时重报
"""
import datetime as dt
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from scripts import futu_realtime as rt  # noqa: E402


def test_stale_sec_parses_and_rejects():
    """`_stale_sec` 正常解析；脏值返回 `None`（视为不可信）✓。"""
    fresh = dt.datetime.now().isoformat(timespec="seconds")
    assert 0 <= rt._stale_sec(fresh) < 5

    old = (dt.datetime.now() - dt.timedelta(days=4)).isoformat(timespec="seconds")
    assert rt._stale_sec(old) > 3 * 86400

    assert rt._stale_sec(None) is None
    assert rt._stale_sec("") is None
    assert rt._stale_sec("not-a-date") is None


def test_alert_skips_stale_price(monkeypatch):
    """**陈旧价格不是当下异动** ⇒ 不告警 ✓（本次事故的直接原因）。"""
    monkeypatch.setattr(rt, "_in_trading_hours", lambda *a, **k: True)
    monkeypatch.setattr(rt, "alert_symbols", lambda: {"CRCG"})
    monkeypatch.setattr(rt, "state", {"alerts": {}})

    old = (dt.datetime.now() - dt.timedelta(days=4)).isoformat(timespec="seconds")
    rt.check_alert("CRCG", {"day_chg_pct": -5.3, "price": 4.28, "ts": old})
    assert "CRCG" not in rt.state["alerts"], "4 天前的数据不该触发告警 ✗"


def test_alert_skips_non_holding(monkeypatch):
    """**只监控持仓** ⇒ QQQ（只做指数预览）不告警 ✓。"""
    monkeypatch.setattr(rt, "_in_trading_hours", lambda *a, **k: True)
    monkeypatch.setattr(rt, "alert_symbols", lambda: {"YINN"})
    monkeypatch.setattr(rt, "state", {"alerts": {}})

    fresh = dt.datetime.now().isoformat(timespec="seconds")
    rt.check_alert("QQQ", {"day_chg_pct": -5.7, "price": 608.45, "ts": fresh})
    assert "QQQ" not in rt.state["alerts"], "非持仓标的不该告警 ✗"


def test_alert_skips_outside_trading_hours(monkeypatch):
    """盘前/盘后/周末不告警 ✓（2026-10-05 根因，原有行为不能丢）。"""
    monkeypatch.setattr(rt, "_in_trading_hours", lambda *a, **k: False)
    monkeypatch.setattr(rt, "alert_symbols", lambda: {"YINN"})
    monkeypatch.setattr(rt, "state", {"alerts": {}})

    fresh = dt.datetime.now().isoformat(timespec="seconds")
    rt.check_alert("YINN", {"day_chg_pct": -6.0, "price": 18.6, "ts": fresh})
    assert "YINN" not in rt.state["alerts"]


def test_holding_symbols_filters_zero_qty(tmp_path, monkeypatch):
    """`qty=0`（已清仓）的标的不算持仓 ✓。

    🔴 事故里 AXTX / CONL / CRCG / GDXU 都是 `qty=0` 的历史行，
       却被 `holding_symbols()` 当成持仓订阅 ⇒ 订阅无数据 ⇒ 价格冻结 ✗
    """
    p = tmp_path / "Data"
    p.mkdir()
    pd.DataFrame({
        "date": pd.to_datetime(["2026-11-20"] * 4),
        "account": ["stock"] * 4,
        "symbol": ["YINN", "AXTX", "CRCG", "GDXU"],
        "name": ["a", "b", "c", "d"],
        "qty": [159, 0, 0, 0],
        "price": [18.63, 9.41, 4.28, 47.16],
        "cost": [26.82, 21.9, 5.0, 50.0],
        "market_value": [2925.0, 0.0, 0.0, 0.0],
    }).to_csv(p / "positions.csv", index=False)
    monkeypatch.setattr(rt, "REPO", str(tmp_path))

    assert rt.holding_symbols(include_index=False) == ["YINN"]
    # QQQ 仍要订阅（指数预览），但不参与告警
    assert rt.holding_symbols(include_index=True) == ["QQQ", "YINN"]
