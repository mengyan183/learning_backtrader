"""Kalshi KXFED 抓取脚本的解析与幂等测试（不联网）。"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.fetch_kalshi_fed import parse_kxfed, append_csv  # noqa: E402


def _market(ticker, strike, bid, ask, close="2026-10-28T18:55:00Z"):
    return {
        "ticker": ticker,
        "event_ticker": ticker[:ticker.rindex("-")],  # KXFED-26OCT
        "floor_strike": strike,
        "yes_bid_dollars": str(bid),
        "yes_ask_dollars": str(ask),
        "last_price_dollars": str((bid + ask) / 2),
        "close_time": close,
    }


def _sample_markets():
    """10 月会议：当前上限 3.75%，加息(→≥4.00) 21%，不动 78.5%。"""
    return [
        _market("KXFED-26OCT-T3.75", 3.75, 0.99, 1.00),
        _market("KXFED-26OCT-T4.00", 4.00, 0.20, 0.22),
        _market("KXFED-26OCT-T4.25", 4.25, 0.00, 0.01),
        _market("KXFED-26OCT-T4.50", 4.50, 0.00, 0.01),
        # 更远事件（12 月）不应被选中
        _market("KXFED-26DEC-T4.00", 4.00, 0.80, 0.83,
                close="2026-12-16T18:55:00Z"),
        _market("KXFED-26DEC-T4.25", 4.25, 0.14, 0.17,
                close="2026-12-16T18:55:00Z"),
    ]


def test_parse_normal():
    row = parse_kxfed(_sample_markets())
    assert row is not None
    assert row["meeting"] == "2026-10-28"       # 选最早事件
    assert row["ease_pct"] == pytest.approx(0.5, abs=0.2)
    assert row["hold_pct"] == pytest.approx(78.5, abs=0.5)
    assert row["hike_pct"] == pytest.approx(21.0, abs=0.5)
    assert row["src"] == "kalshi-kxfed"
    assert row["date"] == "2026-10-14" or len(row["date"]) == 10


def test_parse_empty():
    assert parse_kxfed([]) is None


def test_parse_no_high_conf_strike():
    """无 P≥0.9 档位（无合约或全是平局）→ None。"""
    markets = [
        _market("KXFED-26OCT-T4.00", 4.00, 0.40, 0.42),
        _market("KXFED-26OCT-T4.25", 4.25, 0.35, 0.37),
    ]
    assert parse_kxfed(markets) is None


def test_parse_single_strike():
    """只有一档 → 档位不足，None。"""
    assert parse_kxfed([_market("KXFED-26OCT-T4.00", 4.00, 0.2, 0.22)]) is None


def test_append_csv_idempotent_same_day(tmp_path):
    """同一天追加只保留一行（幂等）。"""
    out = tmp_path / "kalshi_fed.csv"
    row1 = {"date": "2026-10-14", "meeting": "2026-10-28",
            "ease_pct": 0.5, "hold_pct": 78.5, "hike_pct": 21.0,
            "src": "kalshi-kxfed"}
    append_csv(row1, out=out)
    row2 = dict(row1, hike_pct=20.0)  # 同日重跑，数值更新
    append_csv(row2, out=out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "date,meeting,ease_pct,hold_pct,hike_pct,src"
    assert len(lines) == 2                    # 表头 + 1 行
    assert "20.0" in lines[1]
    assert "21.0" not in lines[1]


def test_append_csv_keeps_other_days(tmp_path):
    """不同日期行保留。"""
    out = tmp_path / "kalshi_fed.csv"
    append_csv({"date": "2026-10-13", "meeting": "2026-10-28",
                "ease_pct": 0.5, "hold_pct": 78.0, "hike_pct": 21.5,
                "src": "kalshi-kxfed"}, out=out)
    append_csv({"date": "2026-10-14", "meeting": "2026-10-28",
                "ease_pct": 0.5, "hold_pct": 78.5, "hike_pct": 21.0,
                "src": "kalshi-kxfed"}, out=out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3                    # 表头 + 2 天
