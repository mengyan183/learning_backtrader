# -*- coding: utf-8 -*-
"""回测评估测试（§11.4–11.6）。"""
import pandas as pd
import pytest

from fg_system.backtest import runner


def test_performance_metrics_keys():
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    returns = pd.Series(0.0005, index=idx)
    m = runner.performance_metrics(returns)
    for key in ["annual_return", "max_drawdown", "sharpe", "calmar",
                "annual_vol", "total_return"]:
        assert key in m


def test_max_drawdown_is_negative_or_zero():
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    returns = pd.Series([0.01, -0.05] * 100, index=idx)
    m = runner.performance_metrics(returns)
    assert m["max_drawdown"] <= 0.0


def test_yearly_table_has_one_row_per_year():
    idx = pd.date_range("2022-01-01", periods=600, freq="B")
    returns = pd.Series(0.0003, index=idx)
    table = runner.yearly_table(returns)
    assert len(table) == 3          # 2022 / 2023 / 2024


def test_rolling_3y_table_columns():
    idx = pd.date_range("2018-01-01", periods=1500, freq="B")
    returns = pd.Series(0.0002, index=idx)
    table = runner.rolling_table(returns, window_years=3)
    assert set(["annual_return", "max_drawdown"]).issubset(table.columns)
