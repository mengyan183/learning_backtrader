# -*- coding: utf-8 -*-
"""F-013 稳定币使用效率/背离因子（M2.4 情绪子因子候选池）。

来源：Data/raw/stablecoin_usage.csv（B-10 稳定币链路，CoinGecko 主源 +
DefiLlama 交叉校验偏差 -0.15%；口径=USDC 成交量/流通市值，CEX 现货代理）。
先验（evolution/hypotheses.md）：
- H-030 TVL 背离：价格/成交反弹但链上资金沉淀未跟随 → 贪婪虚高 → 后续收益低。
- H-034 使用效率领先：使用效率提升先行于市值增长，链上活跃度是币股基本面
  领先指标。
口径：主序列 usage_30d（30 日均值，平滑波动），正向（使用效率升 → 链上活跃
→ 风险偏好升 → 贪婪）；派生背离信号（usage_30d 20 日变化）供 H-030 观察。
纪律：**不进合成权重**，先进 factor_screen 评测池；样本 365 日 < 756 日
滚动分位窗，按 accumulating 处理。
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from fg_system import config

REPO = Path(config.REPO_ROOT) if hasattr(config, "REPO_ROOT") else Path(
    __file__).resolve().parent.parent.parent
DEFAULT_CSV = REPO / "Data" / "raw" / "stablecoin_usage.csv"


def load_usage(csv_path=None):
    csv_path = csv_path or DEFAULT_CSV
    if not os.path.exists(csv_path):
        return None
    return pd.read_csv(csv_path, parse_dates=["date"])


def usage_signal(df, ref_index=None, col="usage_30d"):
    """F-013 稳定币使用效率信号：usage_30d → 日频序列（对齐 ref_index）。

    返回使用率（0~1，30 日均值）；评测协议用 756 日滚动分位分层。
    """
    if df is None or len(df) == 0 or col not in df.columns:
        return pd.Series(dtype=float)
    s = df.set_index("date")[col].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if ref_index is not None:
        return s.reindex(ref_index)
    return s


def divergence_signal(df, window=20):
    """H-030 背离观察信号：usage_30d 的 window 日变化（环比，绝对值）。

    TVL/使用率环比下行而价格反弹 = 背离 → 后续收益偏低的观察信号。
    仅观察（H-030 检验用），不评测。
    """
    s = usage_signal(df)
    if len(s) < window:
        return pd.Series(dtype=float)
    return s.diff(window)


class StablecoinUsageFactor:
    """稳定币使用效率因子（F-013）。接口对齐生产因子：score(wide) → 0-1 分数。"""

    name = "stablecoin_breadth"

    def __init__(self, csv_path=None, col="usage_30d"):
        self.csv_path = csv_path or str(DEFAULT_CSV)
        self.col = col

    def signal(self, ref_index=None):
        return usage_signal(load_usage(self.csv_path), ref_index, self.col)

    def score(self, wide=None, window=756):
        """0-1 分数：signal 的滚动百分位（生产因子同款口径）。

        样本 < window 时返回空（进评测池按 accumulating 处理）。
        """
        s = self.signal()
        if len(s.dropna()) < window:
            return pd.Series(dtype=float)
        rank = s.rolling(window, min_periods=window).rank(pct=True)
        return rank
