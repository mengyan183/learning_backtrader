# -*- coding: utf-8 -*-
"""M2.4 情绪子因子候选池：news_sentiment（F-010）/ stablecoin_breadth（F-013）。"""
import pandas as pd

from fg_system.factors.news_sentiment import NewsSentimentFactor, news_signal
from fg_system.factors.stablecoin_breadth import (
    StablecoinUsageFactor, divergence_signal, usage_signal)
from scripts.factor_screen import factor_f013_stablecoin_usage


def test_news_signal_basic():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-10-08", "2026-10-09"]),
                       "mkt_score": [0.625, -0.625]})
    s = news_signal(df)
    assert list(s) == [0.625, -0.625]
    assert s.index.is_monotonic_increasing


def test_news_signal_ref_index_ffill():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-10-08"]),
                       "mkt_score": [0.5]})
    ref = pd.date_range("2026-10-08", "2026-10-10")
    s = news_signal(df, ref)
    assert len(s) == 3
    assert s.iloc[-1] == 0.5  # ffill


def test_news_factor_empty_on_short_sample():
    f = NewsSentimentFactor()
    # 样本 < 756 窗 → score 空（accumulating 处理入口）
    assert len(f.score()) == 0


def test_usage_signal_basic():
    df = pd.DataFrame({"date": pd.to_datetime(["2025-10-11", "2025-10-12"]),
                       "usage_30d": [0.391607, 0.374122]})
    s = usage_signal(df)
    assert len(s) == 2
    assert s.iloc[-1] == 0.374122


def test_usage_signal_ref_index_no_ffill():
    df = pd.DataFrame({"date": pd.to_datetime(["2025-10-11"]),
                       "usage_30d": [0.39]})
    ref = pd.date_range("2025-10-11", "2025-10-13")
    s = usage_signal(df, ref)
    assert len(s) == 3
    assert s.isna().sum() == 2  # 低频序列缺失即缺失（避免滚动窗零方差）


def test_divergence_signal():
    df = pd.DataFrame({"date": pd.date_range("2025-10-01", periods=25),
                       "usage_30d": range(25)})
    d = divergence_signal(df, window=20)
    assert len(d) == 25
    assert d.iloc[-1] == 20  # s[24] - s[4] = 24 - 4 = 20


def test_stablecoin_factor_score_empty_on_short_sample():
    f = StablecoinUsageFactor()
    assert len(f.score()) == 0  # 365 日 < 756 窗 → accumulating


def test_screen_has_f013():
    # factor_screen 装配单元含 F-013（函数可导入、签名兼容）
    df = pd.DataFrame({"date": pd.to_datetime(["2025-10-11", "2025-10-12"]),
                       "usage_30d": [0.39, 0.37]})
    s = factor_f013_stablecoin_usage(df)
    assert len(s) == 2
    assert s.iloc[-1] == 0.37
