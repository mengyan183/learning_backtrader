# -*- coding: utf-8 -*-
"""合成杠杆序列（§4.2）。

用途：加密 ETF 真实历史最长仅 4 年，无法覆盖完整加密周期。用底层资产
（BTC/COIN/MSTR）的日收益合成杠杆序列，把回测拉到 10 年。

**定位声明（必须向使用者明确）**：合成序列不是真实交易标的的历史，
它只用于验证**策略逻辑**。任何基于合成轨的收益数字都必须标注「合成」。

**已知偏差（实测，必须向使用者披露）**：
本模型是「N 倍日再平衡」的机制化复现，但真实加密杠杆 ETF 的实际拖累远超其费率：
  - BITX/BITU 持有 BTC **期货**，有展期升水成本
  - MSTX/MSTU 是 2x **单股互换**，融资价差在超高波动标的上极宽
实测反推所需的等效年化成本率为 2%~58%（CONL 仅 ~2%，符合合理费用；其余远超标）：
  BITX 30.2% / BITU 22.9% / MSTX 57.9% / MSTU 35.3% / CONL 2.2%。
因此本模块采用**实测校准**：用真实产品在重叠区间的实际表现反推成本率，
使合成序列复现真实产品的**已实现拖累**（校准后残留年化偏离 < 0.3%）。

**但这意味着**：合成轨的绝对收益是「按构造校准」出来的，**不具备预测性**；
且校准基于 2022-2026 的利率与升水环境，外推到 2018-2022 存在不确定性。
任何收益/回撤结论必须优先引用**真实轨**；合成轨仅用于验证策略**行为**。
"""
import os

import numpy as np
import pandas as pd

from fg_system import config

TRADING_DAYS = 252.0


class SyntheticQualityError(Exception):
    """合成序列与真实 ETF 偏离过大。必须中止，不得用该序列出结论。"""


def synthetic_returns(underlying_returns, leverage, cost_rate):
    """合成日收益 = N × 底层日收益 − 产品损耗/252。

    产品损耗（费用+融资+跟踪误差）按交易日均匀摊到每一天。波动率拖累
    **不需要显式建模**——它由 N × r 的复利自然产生（v1 §4.5 已实测验证）。
    """
    return leverage * underlying_returns - cost_rate / TRADING_DAYS


def build_synthetic_series(underlying_returns, leverage, cost_rate, base=100.0):
    """合成价格序列 = base × ∏(1 + 合成日收益)。

    首个数据点即已含当日收益（base 是序列起点的**前一日**收盘）。
    """
    r = synthetic_returns(underlying_returns, leverage, cost_rate)
    return base * (1.0 + r.fillna(0.0)).cumprod()


def deviation_gate(synthetic_close, real_close, min_points=2):
    """合成与真实的**年化收益偏离**（正数表示合成跑赢真实）。

    仅用两者重叠区间计算。这是纯数学函数：`min_points` 只做「点数不足则
    无统计意义、返回 NaN」的保护，默认 2。样本量安全阀在 `check_gate` 里。
    """
    joined = pd.concat(
        [synthetic_close.rename("synth"), real_close.rename("real")], axis=1
    ).dropna()
    if len(joined) < min_points:
        return float("nan")

    def annual(s):
        years = len(s) / TRADING_DAYS
        if years <= 0:
            return float("nan")
        total = s.iloc[-1] / s.iloc[0] - 1.0
        return (1.0 + total) ** (1.0 / years) - 1.0 if total > -1 else -1.0

    return float(annual(joined["synth"]) - annual(joined["real"]))


def is_implausible(rate, threshold=None):
    """校准出的成本率是否「不合理地高」。

    True 表示实际拖累远超合理费用，该标的的合成轨是**经验校准**而非机制建模，
    必须在报告中披露（§4.2）。纯函数，便于测试与复用。
    """
    threshold = (
        config.CRYPTO_IMPLAUSIBLE_COST_RATE if threshold is None else threshold
    )
    return bool(abs(rate) > threshold)


def check_gate(symbol, synthetic_close, real_close, gate=None, min_points=60):
    """质量门（§4.2）：**用当前 config 成本率算出的偏离**超阈值时抛异常。

    语义：偏离超阈值说明 config 没校准好（校准后应接近 0）。点数不足
    min_points 时同样抛异常——不足样本的偏离没有统计意义，不得静默通过。
    """
    gate = config.SYNTHETIC_DEVIATION_GATE if gate is None else gate
    dev = deviation_gate(synthetic_close, real_close, min_points=min_points)
    if np.isnan(dev):
        raise SyntheticQualityError(
            "%s: 合成与真实的重叠区间不足 %d 个交易日，无法做质量门校验"
            % (symbol, min_points))
    if abs(dev) > gate:
        raise SyntheticQualityError(
            "%s: 合成与真实年化偏离 %.2f%%，超阈值 %.2f%%（合成轨结论作废）"
            % (symbol, dev * 100, gate * 100))
    return True


def calibrate_cost_rate(underlying_returns, real_close, leverage, base=100.0,
                        lo=-1.0, hi=5.0, iterations=200):
    """二分求「让合成累计收益等于真实 ETF 累计收益」所需的年化成本率。

    这是**实测校准**，不是费用估计。返回值可能远超合理费率——那意味着
    该产品的实际拖累来自模型未捕捉的机制（期货展期升水、单股互换融资价差等），
    必须在报告中披露，不得当作「费率」使用。

    单调性：合成累计收益 = ∏(1 + leverage·r − cost/252) − 1 关于 cost 单调递减。

    口径与 `deviation_gate` 一致：在两条序列的**共同日期**上，把合成序列的
    首日锚为 `base`、真实序列的首日锚为其首个真实价格，比较全区间总收益
    （首日收益未定义，按 0 处理）。
    """
    und = pd.Series(underlying_returns)
    real = pd.Series(real_close)
    # 仅在真实价格缺失处对齐丢弃；底层首日收益未定义（NaN）按 0 处理，
    # 与 build_synthetic_series 的 fillna(0) 一致，不得丢弃该日。
    joined = pd.concat(
        [und.rename("und"), real.rename("real")], axis=1
    ).dropna(subset=["real"])
    if joined.empty:
        return float("nan")

    target = float(joined["real"].iloc[-1] / joined["real"].iloc[0] - 1.0)
    r = joined["und"].fillna(0.0)

    def cum_return(cost):
        synth = base * (1.0 + leverage * r - cost / TRADING_DAYS).cumprod()
        return float(synth.iloc[-1] / synth.iloc[0] - 1.0)

    # cum_return 关于 cost 单调递减：f(lo) 最大、f(hi) 最小。
    f_lo = cum_return(lo)
    f_hi = cum_return(hi)
    if f_lo <= target:
        return float(lo)
    if f_hi >= target:
        return float(hi)

    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        if cum_return(mid) > target:
            lo = mid
        else:
            hi = mid
    return float(0.5 * (lo + hi))


def _etf_calendar(real, symbol):
    """该 ETF 的真实交易日历（升序）。无数据时返回 None。"""
    if real is None or real.empty:
        return None
    cal = real[real["symbol"] == symbol].set_index("date")["close"].sort_index().index
    return cal if len(cal) else None


def _trading_calendar(real, symbol, raw_dir):
    """合成所用的美股交易日历（升序）。

    优先取全区间美股日历（Data/raw/prices.csv 的 SPY 日期，2016-2026），
    这样既把成本摊到 ~252 交易日/年（而非 7×24 底层的 365 天/年），
    又**保留底层的完整历史**（合成轨的目的就是把回测拉长）。
    若无美股日历，退回该 ETF 的自身日期，再退回 None（用底层原始日历）。
    """
    prices_path = os.path.join(raw_dir, "prices.csv")
    if os.path.exists(prices_path):
        px = pd.read_csv(prices_path, dtype={"symbol": str}, parse_dates=["date"])
        spy = px[px["symbol"] == "SPY"].set_index("date")["close"].sort_index().index
        if len(spy):
            return spy
    return _etf_calendar(real, symbol)


def build_all(raw_dir=None):
    """构建全部加密标的的合成序列。

    返回长表 DataFrame[date, symbol, close]。底层来自 crypto_underlying.csv
    （BTC）与 crypto_prices.csv（MSTR/COIN 正股）。

    合成建在**美股交易日历**上：先把底层 reindex 到美股交易日再算收益，
    使成本按 ~252 交易日/年摊（而非 7×24 底层日历的 365 天/年），
    且收益间隔与 ETF 实际持有间隔一致；同时保留底层的完整历史。

    若某标的在 crypto_prices.csv 里没有数据，退回用底层原始日历并在返回的
    DataFrame 里照常输出（validate_against_real 会跳过它）。
    """
    raw_dir = raw_dir or config.RAW_DIR
    btc = pd.read_csv(config.CRYPTO_UNDERLYING_PATH, parse_dates=["date"]).set_index("date")["close"]

    underlying = {"BTC": btc}
    real = None
    crypto_path = config.CRYPTO_PRICES_PATH
    if os.path.exists(crypto_path):
        real = pd.read_csv(crypto_path, dtype={"symbol": str}, parse_dates=["date"])
        for sym in ("MSTR", "COIN"):
            s = real[real["symbol"] == sym].set_index("date")["close"].sort_index()
            if not s.empty:
                underlying[sym] = s

    frames = []
    for symbol, und_name in config.CRYPTO_UNDERLYING.items():
        if und_name not in underlying:
            continue
        und_close = underlying[und_name].sort_index()
        cal = _trading_calendar(real, symbol, raw_dir)
        if cal is not None:
            und_close = und_close.reindex(cal).ffill().dropna()
        und_ret = und_close.pct_change()
        close = build_synthetic_series(
            und_ret,
            leverage=config.CRYPTO_LEVERAGE[symbol],
            cost_rate=config.CRYPTO_PRODUCT_COST_RATE.get(symbol, 0.0),
        )
        frames.append(pd.DataFrame({
            "date": close.index, "symbol": symbol, "close": close.values,
        }))

    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "close"])
    return pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)


def validate_against_real(raw_dir=None, gate=None):
    """返回 {symbol: {"deviation", "calibrated_rate", "years", "warning"}}。

    - deviation: 当前 config 成本率下，合成与真实的年化偏离
    - calibrated_rate: 让两者匹配所需的年化成本率（实测校准值，非费率）
    - years: 重叠区间的年数
    - warning: calibrated_rate 不合理地高（`is_implausible`）时为 True，
      表示「实际拖累远超合理费用，该标的的合成轨是经验校准而非机制建模」

    注意：`check_gate` 语义为——**用当前 config 成本率算出的偏离超阈值时才抛异常**
    （说明 config 没校准好）。校准后偏差应接近 0。
    """
    raw_dir = raw_dir or config.RAW_DIR
    synth = build_all(raw_dir)
    result = {}
    if not os.path.exists(config.CRYPTO_PRICES_PATH):
        return result
    real = pd.read_csv(config.CRYPTO_PRICES_PATH, dtype={"symbol": str}, parse_dates=["date"])

    btc = pd.read_csv(config.CRYPTO_UNDERLYING_PATH, parse_dates=["date"]).set_index("date")["close"]
    underlying = {"BTC": btc}
    for sym in ("MSTR", "COIN"):
        s = real[real["symbol"] == sym].set_index("date")["close"].sort_index()
        if not s.empty:
            underlying[sym] = s

    for symbol in config.CRYPTO_FLAT_SYMBOLS:
        s = synth[synth["symbol"] == symbol].set_index("date")["close"]
        r = real[real["symbol"] == symbol].set_index("date")["close"].sort_index()
        if s.empty or r.empty:
            continue

        dev = deviation_gate(s, r)
        check_gate(symbol, s, r, gate=gate)

        und_name = config.CRYPTO_UNDERLYING[symbol]
        rate = float("nan")
        if und_name in underlying:
            # 用与 build_all 完全相同的日历对齐底层，使校准与质量门口径一致。
            cal = _trading_calendar(real, symbol, raw_dir)
            und = underlying[und_name].sort_index()
            if cal is not None:
                und = und.reindex(cal).ffill().dropna()
            und_ret = und.pct_change().reindex(r.index).dropna()
            rate = calibrate_cost_rate(
                und_ret, r.reindex(und_ret.index), config.CRYPTO_LEVERAGE[symbol])

        joined = pd.concat([s.rename("s"), r.rename("r")], axis=1).dropna()
        years = len(joined) / TRADING_DAYS

        result[symbol] = {
            "deviation": dev,
            "calibrated_rate": rate,
            "years": years,
            "warning": is_implausible(rate),
        }
    return result


def write(path=None, raw_dir=None):
    """构建并落盘 synthetic_leverage.csv。"""
    path = path or config.SYNTHETIC_PATH
    df = build_all(raw_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    return df
