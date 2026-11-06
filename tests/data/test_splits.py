# -*- coding: utf-8 -*-
"""拆股记录与连续性校验测试（§4.4、§14.6）。"""
import pandas as pd
import pytest

from fg_system.data import splits


def test_ratio_semantics_split_vs_reverse():
    assert splits.classify(2.0) == "split"
    assert splits.classify(0.2) == "reverse_split"
    assert splits.classify(1.0) == "none"


def test_continuity_passes_for_adjusted_series(tmp_path):
    """复权后拆股日前后应连续。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/12/2021,TQQQ,22.7,23.0,22.0,22.635,146031440\n"
        "01/13/2021,TQQQ,22.6,23.2,22.5,23.075,108750000\n"
    )
    p = tmp_path / "prices.csv"
    p.write_text(csv, encoding="utf-8")
    sp = pd.DataFrame(
        [{"symbol": "TQQQ", "date": "2021-01-13", "ratio": 2.0, "source": "test", "verified": 1}]
    )
    assert splits.check_continuity(str(p), sp) is True


def test_continuity_fails_for_unadjusted_series(tmp_path):
    """未复权序列在拆股日会出现 ~-50% 跳空，必须报错。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/12/2021,TQQQ,330,331,329,330,1000\n"
        "01/13/2021,TQQQ,165,166,164,165,2000\n"
    )
    p = tmp_path / "prices.csv"
    p.write_text(csv, encoding="utf-8")
    sp = pd.DataFrame(
        [{"symbol": "TQQQ", "date": "2021-01-13", "ratio": 2.0, "source": "test", "verified": 1}]
    )
    with pytest.raises(splits.SplitContinuityError):
        splits.check_continuity(str(p), sp)


def test_only_verified_events_are_checked(tmp_path):
    """verified=0 的事件不参与校验。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/12/2021,TQQQ,330,331,329,330,1000\n"
        "01/13/2021,TQQQ,165,166,164,165,2000\n"
    )
    p = tmp_path / "prices.csv"
    p.write_text(csv, encoding="utf-8")
    sp = pd.DataFrame(
        [{"symbol": "TQQQ", "date": "2021-01-13", "ratio": 2.0, "source": "test", "verified": 0}]
    )
    assert splits.check_continuity(str(p), sp) is True


# ---------------------------------------------------------- 前复权（2026-11-06）
def _split_prices(shock_soxl=-0.387):
    """SOXX 1:3 拆股日（-70.997%）+ SOXL 同日按 3× 反应（2026-11-05 实测 -38.7%）。"""
    dates = pd.date_range("2026-09-01", periods=60, freq="B")
    rows = []
    for i, d in enumerate(dates):
        if i < 45:
            soxx, soxl = 451.06, 66.75
        else:
            soxx = 130.94 * (1 + 0.001 * (i - 45))
            soxl = 66.75 * (1 + shock_soxl) * (1 + 0.001 * (i - 45))
        for sym, c in (("SOXX", soxx), ("SOXL", soxl)):
            rows.append({"date": d, "symbol": sym, "open": c, "high": c,
                         "low": c, "close": c, "volume": 1000.0})
    return pd.DataFrame(rows)


def test_detect_finds_leverage_confirmed_split():
    out = splits.detect(_split_prices())
    assert [(sym, ratio) for sym, _dt, ratio in out] == [("SOXX", 3.0)]


def test_apply_backfills_split_history():
    """拆股日之前的价格 ÷ 3 ⇒ 当日收益回到真实的 -12.9%。"""
    df = splits.apply(_split_prices(), None)
    soxx = df[df["symbol"] == "SOXX"].set_index("date")["close"]
    assert soxx.iloc[0] == pytest.approx(451.06 / 3, rel=1e-6)
    assert soxx.iloc[45] / soxx.iloc[44] - 1 == pytest.approx(-0.1291, abs=0.002)


def test_apply_is_idempotent():
    once = splits.apply(_split_prices(), None)
    twice = splits.apply(once, None)
    pd.testing.assert_frame_equal(once, twice)


def test_apply_rejects_unconfirmed_crash():
    """真实暴跌（杠杆 ETF 同步崩）不得被当成拆股 —— 价格原样返回。"""
    df = _split_prices(shock_soxl=-0.71)
    pd.testing.assert_frame_equal(df, splits.apply(df, None))


def test_apply_honors_verified_event_without_leverage():
    """无杠杆对手盘的标的（如 SLV）只能靠事件表复权。"""
    dates = pd.date_range("2026-09-01", periods=10, freq="B")
    rows = [{"date": d, "symbol": "SLV",
             "open": 40.0 if i < 5 else 20.0, "high": 40.0 if i < 5 else 20.0,
             "low": 40.0 if i < 5 else 20.0, "close": 40.0 if i < 5 else 20.0,
             "volume": 100.0} for i, d in enumerate(dates)]
    ev = pd.DataFrame([{"symbol": "SLV", "date": dates[5], "ratio": 2.0,
                        "source": "test", "verified": 1}])
    out = splits.apply(pd.DataFrame(rows), ev)
    slv = out.set_index("date")["close"]
    assert slv.iloc[0] == pytest.approx(20.0)
    assert slv.iloc[5] / slv.iloc[4] - 1 == pytest.approx(0.0, abs=1e-9)
    assert out.set_index("date")["volume"].iloc[0] == pytest.approx(200.0)
