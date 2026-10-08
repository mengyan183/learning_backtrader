# -*- coding: utf-8 -*-
"""cerebro 装配、基准对比与评估输出（§11.4–11.6）。"""
import os

import backtrader as bt
import numpy as np
import pandas as pd

from fg_system import config
from fg_system import leverage
from fg_system.backtest import feed as feed_mod
from fg_system.backtest import strategy as strategy_mod


def performance_metrics(returns, periods_per_year=252.0):
    """基于日收益序列计算核心指标。"""
    r = pd.Series(returns).dropna()
    if r.empty:
        return {
            "total_return": float("nan"), "annual_return": float("nan"),
            "max_drawdown": float("nan"), "annual_vol": float("nan"),
            "sharpe": float("nan"), "calmar": float("nan"),
        }
    cum = (1.0 + r).cumprod()
    years = len(r) / periods_per_year
    total = float(cum.iloc[-1] - 1.0)
    annual = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 else float("nan")
    peak = cum.cummax()
    dd = cum / peak - 1.0
    max_dd = float(dd.min())
    vol = float(r.std() * np.sqrt(periods_per_year))
    sharpe = float(annual / vol) if vol > 0 else float("nan")
    calmar = float(annual / abs(max_dd)) if max_dd < 0 else float("nan")
    return {
        "total_return": total,
        "annual_return": annual,
        "max_drawdown": max_dd,
        "annual_vol": vol,
        "sharpe": sharpe,
        "calmar": calmar,
    }


def yearly_table(returns):
    r = pd.Series(returns).dropna()
    rows = []
    for year, g in r.groupby(r.index.year):
        m = performance_metrics(g)
        m["year"] = year
        rows.append(m)
    if not rows:
        return pd.DataFrame(columns=["total_return", "annual_return", "max_drawdown",
                                     "annual_vol", "sharpe", "calmar"]).rename_axis("year")
    return pd.DataFrame(rows).set_index("year")


def rolling_table(returns, window_years=3):
    r = pd.Series(returns).dropna()
    window = int(252 * window_years)
    rows = []
    for end in range(window, len(r) + 1):
        chunk = r.iloc[end - window:end]
        m = performance_metrics(chunk)
        m["end"] = chunk.index[-1]
        rows.append(m)
    if not rows:
        return pd.DataFrame(columns=["total_return", "annual_return", "max_drawdown",
                                     "annual_vol", "sharpe", "calmar"]).rename_axis("end")
    return pd.DataFrame(rows).set_index("end")


class RecordingStrategy(strategy_mod.FgStrategy):
    """在 FgStrategy 基础上逐日记录账户净值曲线（用于评估，不改变交易逻辑）。"""

    def __init__(self):
        super().__init__()
        self.equity_dates = []
        self.equity_values = []

    def next(self):
        self.equity_dates.append(self.datas[0].datetime.date(0))
        self.equity_values.append(float(self.broker.getvalue()))
        super().next()

    def equity_curve(self):
        return pd.Series(self.equity_values,
                         index=pd.to_datetime(self.equity_dates))


def build_cerebro(features, symbol, strategy_cls=None):
    cerebro = bt.Cerebro(stdstats=False)
    data = feed_mod.FgPandasData(dataname=features[["open", "high", "low", "close", "volume",
                                                    "fg_index", "zone", "target_position"]])
    cerebro.adddata(data, name=symbol)
    cerebro.addstrategy(strategy_cls or strategy_mod.FgStrategy)
    cerebro.broker.setcash(config.INITIAL_CASH)
    cerebro.broker.setcommission(commission=config.COMMISSION)
    cerebro.broker.set_slippage_perc(config.SLIPPAGE)
    return cerebro


def run_single(features, symbol, strategy_cls=RecordingStrategy):
    """对单个标的跑回测，返回 (策略对象, 日收益序列)。"""
    cerebro = build_cerebro(features, symbol, strategy_cls=strategy_cls)
    result = cerebro.run()
    strat = result[0]
    returns = None
    if hasattr(strat, "equity_curve"):
        curve = strat.equity_curve()
        returns = curve.pct_change().dropna()
    return strat, returns


def buy_and_hold_returns(prices, symbol):
    s = prices[prices["symbol"] == symbol].set_index("date")["close"].sort_index()
    return s.pct_change().dropna()


def report(features_path=None, prices_path=None):
    """生成完整评估报告（§11.6）。"""
    features_path = features_path or config.FEATURES_PATH
    prices_path = prices_path or os.path.join(config.RAW_DIR, "prices.csv")

    features_all = pd.read_csv(features_path, parse_dates=["date"]).set_index("date")
    prices = pd.read_csv(prices_path, parse_dates=["date"])

    out = {}
    for symbol in config.SYMBOLS:
        f = features_all.copy()
        p = prices[prices["symbol"] == symbol].set_index("date").sort_index()
        f = f.join(p[["open", "high", "low", "close", "volume"]], how="inner")
        strat, returns = run_single(f, symbol)
        bh = None
        if len(p):
            bh = p["close"].pct_change().dropna()
        out[symbol] = {
            "strategy": strat,
            "returns": returns,
            "metrics": performance_metrics(returns) if returns is not None else {},
            "buy_and_hold": performance_metrics(bh) if bh is not None else {},
        }

    out["loss_attribution"] = leverage.attribution_table(prices)
    return out
