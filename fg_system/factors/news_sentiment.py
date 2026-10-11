# -*- coding: utf-8 -*-
"""F-010 新闻情绪因子（M2.4 情绪子因子候选池）。

来源：Data/raw/news_sentiment.csv（B-7 新闻舆情链路，fetch_sentiment）。
口径：大盘净情绪分 mkt_score（正向：情绪正 → 风险偏好升 → 贪婪）。
纪律：**不进合成权重**，先进 factor_screen 评测池；样本不足标 accumulating
（当前 3 行，2026-10-08 起，样本积累中）。
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from fg_system import config

REPO = Path(config.REPO_ROOT) if hasattr(config, "REPO_ROOT") else Path(
    __file__).resolve().parent.parent.parent
DEFAULT_CSV = REPO / "Data" / "raw" / "news_sentiment.csv"


def load_news(csv_path=None):
    csv_path = csv_path or DEFAULT_CSV
    if not os.path.exists(csv_path):
        return None
    return pd.read_csv(csv_path, parse_dates=["date"])


def news_signal(df, ref_index=None, score_col="mkt_score"):
    """F-010 新闻情绪信号：mkt_score → 日频序列（对齐 ref_index，前向填充）。

    返回原始分（-1~1 净情绪）；评测协议用 756 日滚动分位分层。
    """
    if df is None or len(df) == 0 or score_col not in df.columns:
        return pd.Series(dtype=float)
    s = df.set_index("date")[score_col].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if ref_index is not None:
        return s.reindex(ref_index).ffill()
    return s


class NewsSentimentFactor:
    """新闻舆情因子（F-010）。接口对齐生产因子：score(wide) → 0-1 分数。"""

    name = "news_sentiment"

    def __init__(self, csv_path=None, score_col="mkt_score"):
        self.csv_path = csv_path or str(DEFAULT_CSV)
        self.score_col = score_col

    def signal(self, ref_index=None):
        return news_signal(load_news(self.csv_path), ref_index, self.score_col)

    def score(self, wide=None, window=756):
        """0-1 分数：signal 的滚动百分位（生产因子同款口径）。

        样本 < window 时返回空（进评测池按 accumulating 处理）。
        """
        s = self.signal()
        if len(s.dropna()) < window:
            return pd.Series(dtype=float)
        rank = s.rolling(window, min_periods=window).rank(pct=True)
        return rank
