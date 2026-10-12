# -*- coding: utf-8 -*-
"""`_check_shoutu_freshness` 的窗口充分性防御（WT-19）。

三态：空窗口 / 单元素窗口 / 正常窗口。
- 空 / 单元素：必须**明确报错**（`ValueError` + 可读信息），而非裸 `IndexError` traceback；
- 正常：返回 `None`（无异常）。

不读真实 `Data/`：`hist` 与小 `DataFrame` 全部就地构造。
"""
import pandas as pd
import pytest

from fg_system import config, pipeline

LAG = int(config.SHOUTU_SIGNAL_MAX_LAG_DAYS)


def _hist(last_day, n=5):
    """构造最小 `hist` 长表（只需 `date` 列被新鲜度校验读取）。"""
    dates = pd.date_range(end=last_day, periods=n, freq="D")
    return pd.DataFrame({"date": dates, "symbol": ["s"] * n,
                         "score": [1.0] * n, "price": [1.0] * n})


def _features(index):
    return pd.DataFrame({"fg_index": [50.0] * len(index)}, index=index)


def test_empty_window_raises_clear_error():
    """空索引：显式 `ValueError`（带「窗口不足」+ 路径），不是 IndexError。"""
    hist = _hist("2024-01-10")
    empty = pd.DataFrame(columns=["fg_index"], dtype=float)
    with pytest.raises(ValueError) as ei:
        pipeline._check_shoutu_freshness(hist, empty)
    msg = str(ei.value)
    assert "窗口不足" in msg
    assert "0 行" in msg
    assert "path" in msg.lower() or "路径=" in msg
    assert pipeline.__file__ in msg


def test_single_element_window_raises_clear_error():
    """单元素索引：窗口 < lag+1，必须明确报「窗口不足」而非误报「信号源陈旧」。"""
    hist = _hist("2024-01-10")
    one = _features(pd.DatetimeIndex(["2024-01-10"]))
    with pytest.raises(ValueError) as ei:
        pipeline._check_shoutu_freshness(hist, one)
    msg = str(ei.value)
    assert "窗口不足" in msg
    assert "1 行" in msg
    # 不得与「信号源陈旧」混淆
    assert "陈旧" not in msg


def test_nat_index_raises_clear_error():
    """含 NaT 的索引：明确报「缺失日期」，而非 `tail[...]` 触发 IndexError。"""
    hist = _hist("2024-01-10")
    nat = _features(pd.DatetimeIndex([pd.NaT] * (LAG + 2)))
    with pytest.raises(ValueError) as ei:
        pipeline._check_shoutu_freshness(hist, nat)
    assert "NaT" in str(ei.value)


def test_normal_window_returns_none():
    """正常窗口（长度 ≥ lag+1 且 history 足够新）：正常返回 `None`，不抛错。"""
    days = pd.date_range("2024-01-01", periods=LAG + 5, freq="D")
    hist = _hist(days[-1])                       # hist 与窗口同日 ⇒ 绝不陈旧
    feats = _features(days)
    assert pipeline._check_shoutu_freshness(hist, feats) is None


def test_stale_source_still_rejected():
    """回归：窗口充分时，陈旧信号源仍须被显式拒绝（防御不得掩盖原判据）。"""
    days = pd.date_range("2024-01-01", periods=LAG + 5, freq="D")
    hist = _hist("2023-01-01")                   # 远早于窗口 ⇒ 陈旧
    feats = _features(days)
    with pytest.raises(ValueError) as ei:
        pipeline._check_shoutu_freshness(hist, feats)
    assert "陈旧" in str(ei.value)
