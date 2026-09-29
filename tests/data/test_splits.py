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
