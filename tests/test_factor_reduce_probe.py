# -*- coding: utf-8 -*-
"""风控型因子裁判 `factor_reduce_probe.py`（2026-11-02）。

【为什么存在】`factor_backtest_probe` 的口径是「因子 → 仓位 0.2~1.0 映射」✗
它要求因子能**决定仓位比例** ✗ 但 F-016/F-018/F-020 的能力只是「识别危险时刻」✗
⇒ 用满仓吃 beta 的口径去测，必然得出「跑输 B0」✗ 是口径错配 ✗
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import scripts.factor_reduce_probe as P  # noqa: E402


def _fake_close(n=600, start="2020-01-01", drift=0.0005):
    idx = pd.bdate_range(start, periods=n)
    px = 100.0 * np.cumprod(1.0 + np.full(n, drift))
    return pd.Series(px, index=idx)


def test_ratio_zero_equals_buy_and_hold():
    """`ratio=0` 必须等于买入持有 ✓（只扣首日建仓成本 ✗）。

    ⚠️ 期望值用**复利** `(1+drift)**252 - 1` ✗ 不是单利 `drift×252` ✗
       （两者差 6%：0.1342 vs 0.126 ✗ —— 我第一版就写错了 ✗）
    """
    close = _fake_close()
    sig = pd.Series(0.5, index=close.index)
    m0 = P._run(close, sig, 0.0)
    expect = (1.0 + 0.0005) ** 252 - 1.0
    assert m0["annual_return"] == pytest.approx(expect, rel=0.05)
    assert m0["avg_pos"] == pytest.approx(1.0)


def test_trend_filter_does_not_change_b0():
    """🔴 `--trend-filter` **不能**改变 `ratio=0` 的 B0 ✗

    2026-11-02 踩坑：`w.where(~above, 1.0)` 会把**原本 NaN** 的仓位也填成 1.0 ✗
    ⇒ 实测 GDXU 无过滤 n_days=695、有过滤 796（多 101 天 ✗）
    ⇒ 那 101 天是分位窗预热期（本无信号 ✗）⇒ B0 从 +54.09% 假跌到 +7.86% ✗
    """
    close = _fake_close(n=800)
    # 前 300 天无信号（模拟 252 日分位窗预热 ✗）
    sig = pd.Series(np.nan, index=close.index)
    sig.iloc[300:] = 0.5
    m0 = P._run(close, sig, 0.0, trend_filter=False)
    m1 = P._run(close, sig, 0.0, trend_filter=True)
    assert m0["n_days"] == m1["n_days"], "n_days 不该变 ✗（NaN 被填成满仓了 ✗）"
    assert m0["annual_return"] == pytest.approx(m1["annual_return"], rel=1e-9)


def test_trend_filter_forces_full_position_above_ma():
    """均线**之上** ⇒ 仓位强制 1.0（不因因子减仓）✓。

    ⚠️ 只看 **MA200 有效之后** 的区间 ✗ ——
       前 200 天 `ma` 是 NaN ⇒ `above=False` ⇒ 不强制满仓 ✗
       整体 avg_pos 会是 0.667（200/600 无 MA ✗），不是 >0.95 ✗
       —— 我第一版就漏了这点 ✗
    """
    close = _fake_close(n=800, drift=0.002)      # 单边上涨 ⇒ 恒在 MA200 之上 ✓
    sig = pd.Series(1.0, index=close.index)      # 因子说「最危险」

    # ⚠️ 不能截断后再传 ✗ —— `_run` 内部重算 MA200，
    #    截断后的前 200 天又是 NaN ✗（我前两版都栽在这 ✗）
    # ⇒ 改为「有过滤的仓位必须**明显高于**无过滤」✓
    m = P._run(close, sig, 1.0, trend_filter=True)
    m_no = P._run(close, sig, 1.0, trend_filter=False)
    assert m_no["avg_pos"] < 0.05, "无过滤时应被减到接近 0 ✗"
    # 800 天里后 600 天在 MA 之上 ⇒ avg_pos 约 0.75 ✓
    assert m["avg_pos"] > m_no["avg_pos"] + 0.5, \
        "趋势过滤应显著提高仓位 ✗"


def test_metrics_basic():
    """指标自洽：年化/回撤/Sharpe/Calmar 都算得出 ✓。"""
    ret = pd.Series(np.random.RandomState(0).normal(0.0005, 0.01, 500),
                    index=pd.bdate_range("2020-01-01", periods=500))
    m = P._metrics(ret, pd.Series(1.0, index=ret.index))
    assert m is not None
    for k in ("annual_return", "max_drawdown", "sharpe", "calmar",
              "avg_pos", "n_days"):
        assert k in m
    assert m["max_drawdown"] <= 0


def test_unknown_factor_raises():
    """未知因子 ⇒ 明确报错 ✓（不静默返回空 ✗）。"""
    with pytest.raises(SystemExit):
        P._signal(pd.DataFrame({"symbol": [], "date": [], "close": []}),
                  "SPY", "not_a_factor")
