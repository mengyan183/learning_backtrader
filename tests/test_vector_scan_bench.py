# -*- coding: utf-8 -*-
"""L3.1 向量化参数扫描基准实验：向量化层关键函数测试。

覆盖：
- target_series：截断映射
- apply_debounce：防抖执行（|Δ|<阈值不调仓）
- vec_run：无未来函数（shift(1) 次日执行）+ 成本扣除
- 网格单调性（lo 越高，暴露越高）
"""
import numpy as np
import pandas as pd

from scripts.vector_scan_bench import DEBOUNCE, target_series, apply_debounce


def test_target_series_bounds():
    s = pd.Series([0.0, 30.0, 50.0, 80.0, 100.0, np.nan])
    t = target_series(s, 0.25, 0.75)
    assert t.iloc[0] == 0.25          # 低于 lo 截断
    assert t.iloc[1] == 0.3
    assert abs(t.iloc[2] - 0.5) < 1e-9
    assert t.iloc[3] == 0.75
    assert t.iloc[4] == 0.75          # 高于 hi 截断
    assert t.iloc[5] == 0.0           # NaN 补 0


def test_debounce_small_delta_keeps_position():
    s = pd.Series([0.0, 0.02, 0.04, 0.5, 0.52, 0.0])
    adj = apply_debounce(s)
    # 0→0.02/0.04 变化 < 阈值：保持 0；0.04→0.5 变化 ≥ 阈值：跳到 0.5
    assert adj.iloc[0] == 0.0
    assert adj.iloc[1] == 0.0
    assert adj.iloc[2] == 0.0
    assert adj.iloc[3] == 0.5
    assert adj.iloc[4] == 0.5        # 0.5→0.52 < 阈值
    assert adj.iloc[5] == 0.0        # 0.52→0 ≥ 阈值
    assert DEBOUNCE == 0.05


def test_apply_debounce_is_monotone_reachable():
    s = pd.Series([0.0, 1.0, 0.0, 1.0, 0.0])
    adj = apply_debounce(s)
    assert adj.iloc[0] == 0.0
    assert adj.iloc[1] == 1.0
    assert adj.iloc[2] == 0.0
    assert adj.iloc[3] == 1.0
    assert adj.iloc[4] == 0.0


def test_vec_scan_no_lookahead():
    """向量化收益必须用 shift(1)：T 日 target 决定 T+1 收益。"""
    from scripts.vector_scan_bench import vec_run
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    features = pd.DataFrame({"date": dates,
                             "fg_index": [80.0, 80.0, 20.0, 20.0, 20.0,
                                          20.0, 20.0, 20.0, 20.0, 20.0]})
    prices = pd.DataFrame({
        "date": dates,
        "symbol": "TQQQ",
        "open": np.linspace(10, 19, 10),
        "high": np.linspace(10, 19, 10) + 0.1,
        "low": np.linspace(10, 19, 10) - 0.1,
        "close": np.linspace(10, 19, 10),
        "volume": 1e6,
    })
    ret = vec_run(features, prices, 0.0, 1.0)
    # T=0 档位 80 → 仓位 0.8，T=1 才生效（shift(1)）：首日收益必须为 0
    assert abs(ret.iloc[0]) < 1e-12
    # 上涨行情中早期高仓位 → 收益为正
    assert ret.iloc[1] > 0.0
    # 含成本：换仓日收益 = 仓位×收益 - 成本
    assert ret.iloc[1] < 0.8 * (1.1 - 1.0)   # 收益减去换仓成本


def test_scan_monotonicity():
    """lo 越高 → 平均暴露越高 → 累计收益单调性（同 hi 下）。"""
    dates = pd.date_range("2024-01-01", periods=252, freq="B")
    rng = np.random.default_rng(7)
    fg = pd.Series(30 + 40 * np.sin(np.linspace(0, 12, 252)) + rng.normal(0, 8, 252)).clip(0, 100)
    features = pd.DataFrame({"date": dates, "fg_index": fg})
    px = pd.DataFrame({
        "date": dates, "symbol": "TQQQ",
        "open": 10.0, "high": 10.5, "low": 9.5,
        "close": np.linspace(10, 30, 252), "volume": 1e6,
    })
    r_lo = vec_run(features, px, 0.0, 1.0)
    r_hi = vec_run(features, px, 0.75, 1.0)
    nav_lo = (1 + r_lo).cumprod().iloc[-1]
    nav_hi = (1 + r_hi).cumprod().iloc[-1]
    assert nav_hi > nav_lo   # 低仓约束下收益更低（上涨行情）
