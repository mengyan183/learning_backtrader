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


SPLIT_MIN_DROP = -0.30      # 只有单日 ≤ -30% 才可能是拆股
SPLIT_REL_TOL = 0.25        # 与 loader.check_split_anomalies 同口径（相对容差）
SPLIT_LEV_TOL = 0.05        # 杠杆对手盘交叉确认容差（5pp）


def _close_series(df, sym):
    s = df[df["symbol"] == sym]
    return s.set_index(pd.to_datetime(s["date"]))["close"].sort_index()


def detect(prices_df):
    """自动识别**被杠杆对手盘确认**的拆股日 ⇒ `[(symbol, date, ratio)]`。

    判据（三条同时成立）：
      ① 标的单日 ≤ -30%；② 隐含比例 `1/(1+r)` 接近整数 ≥2（相对容差 25%）；
      ③ 杠杆 ETF 当日收益 ≈ N × 「去掉拆股后的真实收益」±5pp。

    ③ 是关键：真实暴跌时杠杆 ETF 会同步崩（≈N×跌幅），只有拆股才会出现
    「标的 -71% 而杠杆只 -39%」的形态 ⇒ 不会把暴跌误判成拆股。
    """
    out = []
    for lev, und in config.UNDERLYING_MAP.items():
        n = config.LEVERAGE_RATIO[lev]
        u = _close_series(prices_df, und)
        l = _close_series(prices_df, lev)
        if u.empty or l.empty:
            continue
        for dt, v in u.pct_change().dropna().items():
            if v > SPLIT_MIN_DROP or dt not in l.index:
                continue
            pos = l.index.get_loc(dt)
            if pos == 0:
                continue
            implied = 1.0 / (1.0 + v)
            near = round(implied)
            if near < 2 or abs(implied - near) > SPLIT_REL_TOL * near:
                continue
            lev_ret = l.iloc[pos] / l.iloc[pos - 1] - 1.0
            adj = (1.0 + v) * near - 1.0          # 去掉拆股后的真实收益
            if abs(lev_ret - n * adj) <= SPLIT_LEV_TOL:
                out.append((und, dt, float(near)))
    return out


def apply(prices_df, split_df=None):
    """前复权：拆股日**之前**的行 ÷ ratio（价格）/ × ratio（成交量）。**幂等**。

    事件来源 = `splits.csv` 的 verified 事件 ∪ `detect()` 自动确认的拆股日。

    幂等/防呆判据：**只有当复权能让拆股日更连续时才动手**
    （`|(1+chg)/ratio - 1| < |chg|`）。三种情况自动跳过 ✓：
      ① 已复权（再除一次只会更不连续）✗
      ② 事件表 ratio 方向记反（AXTX 0.24615 实测）✗
      ③ 真实暴跌（detect 已用杠杆对手盘挡掉，这里再兜一层）✗
    """
    if prices_df is None or prices_df.empty:
        return prices_df
    df = prices_df.copy()
    dts = pd.to_datetime(df["date"])

    events = []
    if split_df is not None and not split_df.empty:
        ev = _normalize_events(split_df)
        events += [(r["symbol"], r["date"], float(r["ratio"]))
                   for _, r in ev[ev["verified"] == 1].iterrows()]
    events += detect(df)

    seen = set()
    for sym, dt, ratio in events:
        dt = pd.Timestamp(dt)
        if (sym, dt) in seen or ratio <= 0:
            continue
        seen.add((sym, dt))
        mask = df["symbol"] == sym
        if not mask.any():
            continue
        s = df.loc[mask].assign(_d=dts[mask]).sort_values("_d")
        pos = list(s["_d"]).index(dt) if dt in set(s["_d"]) else None
        if pos is None or pos == 0:
            continue
        chg = s["close"].iloc[pos] / s["close"].iloc[pos - 1] - 1.0
        # 前复权后当日收益 = ratio × (1+chg) - 1（拆股日之前的价格 ÷ ratio）
        if abs(ratio * (1.0 + chg) - 1.0) >= abs(chg):
            continue                                  # 复权后不会更连续 ⇒ 跳过
        before = mask & (dts < dt)
        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                df.loc[before, col] = df.loc[before, col] / ratio
        if "volume" in df.columns:
            df.loc[before, "volume"] = df.loc[before, "volume"] * ratio
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
