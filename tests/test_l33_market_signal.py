# -*- coding: utf-8 -*-
"""L3.3 实时链路增强（market_signal）测试。"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from scripts import futu_realtime as rt


def test_btc_thread_starts_before_futu_connect():
    """币安线程必须在富途连接**之前**启动 ✓（2026-11-23 卡死 27 小时）。

    🔴 事故：富途 OpenD 挂 ⇒ `OpenQuoteContext()` 卡在 SDK 重连循环
       （日志全是 `init connect fail`）⇒ 进程活着（PID 2020），但
       **主循环与 BTC 线程都没起来** ⇒ `realtime_state.json` 停在 11-22 01:35 ✗
    ⇒ 用 AST 锁住「启动顺序」这个结构不变量（不是字符串出现与否）✓
    """
    import ast

    path = os.path.join(REPO, "scripts", "futu_realtime.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    # ⚠️ 必须限定在 `main()` 内 ✗ —— `snapshot_fallback` 里也有一个
    #    `OpenQuoteContext(...)`（第 183 行）⇒ 全局取首个会误判 ✗
    main_fn = next((n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert main_fn is not None, "找不到 main() ✗"

    thread_line = ctx_line = None
    for node in ast.walk(main_fn):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name == "Thread":
            for kw in node.keywords:
                if (kw.arg == "target"
                        and getattr(kw.value, "id", "") == "crypto_ticker_loop"):
                    thread_line = (node.lineno if thread_line is None
                                   else min(thread_line, node.lineno))
        elif name == "OpenQuoteContext" and ctx_line is None:
            ctx_line = node.lineno

    assert thread_line is not None, "找不到 crypto_ticker_loop 线程启动 ✗"
    assert ctx_line is not None, "找不到 OpenQuoteContext 调用 ✗"
    assert thread_line < ctx_line, (
        "币安线程必须在富途连接之前启动（线程第 %d 行 vs 连接第 %d 行）✗"
        % (thread_line, ctx_line))


@pytest.fixture
def preview():
    return {
        "fg_index": 58.3, "zone": "贪婪", "closed_index": 54.9,
        "delta": 3.4, "reason": "QQQ 盘中走强推升 price 因子", "ts": "2026-10-11T15:30:00",
    }


@pytest.fixture
def state(preview):
    return {
        "updated": "2026-10-11T15:30:05",
        "prices": {"QQQ": {"price": 752.62, "day_chg_pct": 1.2,
                           "ts": "2026-10-11T15:29:00"}},
        "preview_index": preview,
        "alerts": {},
    }


class TestBuildMarketSignal:
    def test_structure_and_fields(self, state, preview):
        ms = rt.build_market_signal(state, preview)
        assert ms is not None
        assert ms["type"] == "preview"
        assert ms["fg_index"] == 58.3
        assert ms["zone"] == "贪婪"
        assert ms["closed_index"] == 54.9
        assert ms["delta"] == 3.4
        # L3.3 语义字段
        assert "price=实时QQQ重算" in ms["factor_drivers"]
        assert ms["freshness_ts"] == "2026-10-11T15:29:00"
        assert isinstance(ms["in_trading_hours"], bool)
        assert ms["ts"] == preview["ts"]

    def test_none_preview_returns_none(self, state):
        assert rt.build_market_signal(state, None) is None

    def test_missing_qqq_price_freshness_none(self, state, preview):
        state["prices"] = {"AXTX": {"price": 1.0}}
        ms = rt.build_market_signal(state, preview)
        assert ms["freshness_ts"] is None

    def test_trading_hours_weekend(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        # 2026-10-11 是周日（美东），必为盘外
        assert rt._in_trading_hours(
            datetime(2026, 10, 11, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        ) is False

    def test_trading_hours_midweek_open(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        # 2026-10-07 周三 13:00 美东 → 交易时段
        assert rt._in_trading_hours(
            datetime(2026, 10, 7, 13, 0, tzinfo=ZoneInfo("America/New_York"))
        ) is True


class TestRealtimeRoute:
    def test_route_serves_market_signal(self, tmp_path, monkeypatch):
        """/realtime 返回 market_signal 且只读（no-store）。"""
        from fg_system.dashboard import server as srv
        state = {
            "updated": "2026-10-11T15:30:05",
            "prices": {"QQQ": {"price": 752.62, "ts": "2026-10-11T15:29:00"}},
            "preview_index": {"fg_index": 58.3, "zone": "贪婪", "closed_index": 54.9,
                              "delta": 3.4, "ts": "2026-10-11T15:30:00"},
            "market_signal": {"type": "preview", "fg_index": 58.3,
                              "factor_drivers": "price=实时QQQ重算",
                              "in_trading_hours": True,
                              "freshness_ts": "2026-10-11T15:29:00"},
            "alerts": {},
        }
        fake = tmp_path / "realtime_state.json"
        fake.write_text(json.dumps(state), encoding="utf-8")
        monkeypatch.setattr(srv.config, "DATA_DIR", str(tmp_path))
        app = srv.make_handler(lambda: None)
        client = app.test_client()
        r = client.get("/realtime")
        assert r.status_code == 200
        assert r.headers.get("Cache-Control") == "no-store"
        body = r.get_json()
        assert body["market_signal"]["type"] == "preview"
        assert body["market_signal"]["fg_index"] == 58.3
        assert body["preview_index"]["fg_index"] == 58.3  # 兼容字段保留

    def test_route_404_when_no_state(self, tmp_path, monkeypatch):
        from fg_system.dashboard import server as srv
        monkeypatch.setattr(srv.config, "DATA_DIR", str(tmp_path))
        app = srv.make_handler(lambda: None)
        client = app.test_client()
        r = client.get("/realtime")
        assert r.status_code == 404
