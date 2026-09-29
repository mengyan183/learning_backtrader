# -*- coding: utf-8 -*-
"""拆股/合股事件记录与连续性校验（§4.4）。"""
import pandas as pd

from fg_system import config

SPLIT_COLUMNS = ["symbol", "date", "ratio", "source", "verified"]


class SplitContinuityError(Exception):
    """拆股日前后价格不连续，说明复权失效。"""


def classify(ratio):
    """ratio 语义（§4.4 第 3 条）：>1 拆股，<1 合股，=1 无事件。"""
    if ratio > 1:
        return "split"
    if ratio < 1:
        return "reverse_split"
    return "none"


def load(path=None):
    path = path or f"{config.RAW_DIR}/splits.csv"
    try:
        df = pd.read_csv(path, dtype={"symbol": str})
    except FileNotFoundError:
        return pd.DataFrame(columns=SPLIT_COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=SPLIT_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    df["verified"] = pd.to_numeric(df["verified"], errors="coerce").fillna(0).astype(int)
    return df


def _normalize_events(split_df):
    """把事件表的 date/verified 规整为 Timestamp/int。

    调用方可能直接传入手工构造的 DataFrame（未走 load()），其中 date 是字符串，
    而 iterrows() 对混合 dtype 的 DatetimeIndex 不会逐行转成 Timestamp——
    会导致 ev["date"].date() 抛 AttributeError。此处统一兜底。
    """
    df = split_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["verified"] = pd.to_numeric(df["verified"], errors="coerce").fillna(0).astype(int)
    return df


def check_continuity(prices_path, split_df, tolerance=None):
    """校验每个 verified 事件的拆股日前后涨跌幅在容差内（§14.6 第 1 条）。"""
    tolerance = tolerance if tolerance is not None else config.SPLIT_CONTINUITY_TOLERANCE
    if split_df is None or split_df.empty:
        return True
    split_df = _normalize_events(split_df)
    prices = pd.read_csv(prices_path)
    prices["date"] = pd.to_datetime(prices["date"], format="%m/%d/%Y", errors="coerce")
    prices.loc[prices["date"].isna(), "date"] = pd.to_datetime(
        prices.loc[prices["date"].isna(), "date"], errors="coerce"
    )

    bad = []
    for _, ev in split_df[split_df["verified"] == 1].iterrows():
        s = prices[prices["symbol"] == ev["symbol"]].sort_values("date")
        s = s.set_index("date")["close"]
        if s.empty:
            bad.append("%s: 价格文件中无该标的数据，无法校验拆股连续性" % ev["symbol"])
            continue
        if ev["date"] not in s.index:
            continue
        pos = s.index.get_loc(ev["date"])
        if pos == 0:
            continue
        chg = abs(s.iloc[pos] / s.iloc[pos - 1] - 1)
        if chg > tolerance:
            bad.append(
                "%s %s: 拆股日涨跌 %.2f%% 超容差 %.2f%%（复权可能失效）"
                % (ev["symbol"], ev["date"].date(), chg * 100, tolerance * 100)
            )
    if bad:
        raise SplitContinuityError("拆股连续性校验失败：\n  " + "\n  ".join(bad))
    return True
