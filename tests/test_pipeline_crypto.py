# -*- coding: utf-8 -*-
"""加密管道与组合管道测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system import pipeline


# ---------------------------------------------------------------- 趋势与回撤

def test_crypto_drawdown_series_uses_btc():
    """加密回撤基准必须是 BTC 现货，不是 BITX（§6.4）。"""
    idx = pd.bdate_range("2024-01-01", periods=300)
    btc = pd.Series(np.linspace(100000, 50000, 300), index=idx)
    wide = pd.DataFrame({("BTC", "close"): btc})
    dd = pipeline.crypto_drawdown_series(wide)
    assert dd.dropna().iloc[-1] > 0.4


def test_crypto_drawdown_series_nan_during_warmup():
    idx = pd.bdate_range("2024-01-01", periods=300)
    btc = pd.Series(np.linspace(100000, 50000, 300), index=idx)
    wide = pd.DataFrame({("BTC", "close"): btc})
    dd = pipeline.crypto_drawdown_series(wide)
    assert dd.iloc[:251].isna().all()


def test_crypto_trend_series_uses_btc():
    idx = pd.bdate_range("2020-01-01", periods=300)
    btc = pd.Series(np.linspace(200000, 50000, 300), index=idx)
    wide = pd.DataFrame({("BTC", "close"): btc})
    tf = pipeline.crypto_trend_series(wide)
    assert tf.iloc[-1] == pytest.approx(config.TREND_FILTER_FACTOR)


def test_equity_trend_series_uses_qqq():
    idx = pd.bdate_range("2020-01-01", periods=300)
    qqq = pd.Series(np.linspace(500, 200, 300), index=idx)
    wide = pd.DataFrame({("QQQ", "close"): qqq})
    tf = pipeline.equity_trend_series(wide)
    assert tf.iloc[-1] == pytest.approx(config.TREND_FILTER_FACTOR)


# ---------------------------------------------------------------- 组合管道

def _us(idx, fg_index):
    return pd.DataFrame({
        "fg_index": fg_index, "drawdown": [0.0] * len(idx), "trend": [1.0] * len(idx),
    }, index=idx)


def _cr(idx, crypto_index):
    return pd.DataFrame({
        "crypto_fg_index": crypto_index, "drawdown": [0.0] * len(idx),
        "trend": [1.0] * len(idx),
    }, index=idx)


def test_run_portfolio_shifts_target_position():
    """§10.3：喂给回测前必须整体 shift(1)。"""
    idx = pd.bdate_range("2024-01-01", periods=5)
    out = pipeline.run_portfolio(_us(idx, [10.0] * 5), _cr(idx, [10.0] * 5), write=False)
    assert pd.isna(out["target_position"].iloc[0])
    expected_core = (config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
                     + config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"])
    assert out["core_position"].iloc[1] == pytest.approx(expected_core)
    # 注意：指数 10.0 恰好等于 EXTREME_FEAR_TRIGGER（下闭区间），会触发极恐
    # 提前释放弹药，因此 target = core + 1 批弹药，不是纯 core。
    assert out["ammo_position"].iloc[1] == pytest.approx(config.AMMO_PER_BATCH)
    assert out["target_position"].iloc[1] == pytest.approx(
        expected_core + config.AMMO_PER_BATCH)


def test_run_portfolio_marks_warmup():
    idx = pd.bdate_range("2024-01-01", periods=3)
    out = pipeline.run_portfolio(
        _us(idx, [np.nan, 10.0, 10.0]), _cr(idx, [np.nan, 10.0, 10.0]), write=False)
    assert bool(out["warmup"].iloc[0]) is True


def test_run_portfolio_handles_partial_market():
    """一个市场 warmup 时，组合只用另一个市场。"""
    idx = pd.bdate_range("2024-01-01", periods=3)
    out = pipeline.run_portfolio(
        _us(idx, [np.nan] * 3), _cr(idx, [10.0] * 3), write=False)
    expected = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert out["core_position"].iloc[0] == pytest.approx(expected)


def test_run_portfolio_keeps_state_across_days():
    """回归：熔断状态必须跨日保持，不能在循环内重置。

    构造：指数 90 触发熔断 → 次日 88 **熔断维持**（88 >= 60 未达解锁线，
    且 90-88=2 < EXTREME_GREED_UNLOCK_DROP 15，不会解锁）。

    判别力：若状态在循环内被重置，第 2 天会走五档——而五档在指数 >=80 时
    给饱和度 0，核心仓会是 0；正确实现应维持熔断底仓 full × 0.25。
    """
    idx = pd.bdate_range("2024-01-01", periods=3)
    out = pipeline.run_portfolio(
        _us(idx, [90.0, 88.0, 88.0]), _cr(idx, [np.nan] * 3), write=False)
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert out["us_core"].iloc[1] == pytest.approx(full * config.EXTREME_GREED_FLOOR)
    assert out["us_core"].iloc[1] > 0.0, "熔断底仓必须非零（五档此时是 0）"


def test_run_portfolio_shared_ammo_released_once():
    """共享弹药池：同一天两市场同时触发，只释放 1 批。"""
    idx = pd.bdate_range("2024-01-01", periods=3)
    us = _us(idx, [10.0] * 3)
    cr = _cr(idx, [10.0] * 3)
    us["drawdown"] = [0.65, 0.65, 0.65]
    cr["drawdown"] = [0.80, 0.80, 0.80]
    out = pipeline.run_portfolio(us, cr, write=False)
    assert out["ammo_released"].iloc[-1] <= 3


# ---------------------------------------------------------------- v2.5 分市场弹药记账

def test_run_portfolio_per_market_ammo_sums_to_total():
    """分市场弹药必须自洽：`ammo_us + ammo_crypto == ammo_position`（第 12.8.1 条）。

    **为什么必须有分市场记账**：共享池是「先到先得」，实测**加密把 3 批全拿走、
    大盘拿到 0 批**。若把整份 `ammo_position` 记到大盘头上，会严重高估大盘暴露
    （曾据此算出 51.5%，实际只有 31.5%）。
    """
    idx = pd.bdate_range("2024-01-01", periods=3)
    us = _us(idx, [10.0] * 3)
    cr = _cr(idx, [10.0] * 3)
    us["drawdown"] = [0.65, 0.65, 0.65]
    cr["drawdown"] = [0.80, 0.80, 0.80]
    out = pipeline.run_portfolio(us, cr, write=False)
    assert np.allclose(out["ammo_us"] + out["ammo_crypto"], out["ammo_position"])


def test_run_portfolio_deeper_drawdown_market_is_capped():
    """加密回撤更深会优先拿弹药，**但受份额上限约束**：最多 2 批，第 3 批归大盘。

    这正是 v2.5 要修的问题（第 12.11 条）：**不加上限时加密会把 3 批全拿走、
    大盘得 0 批**，使「共享弹药池」名存实亡、大盘的「跌了加仓」从未生效。
    """
    idx = pd.bdate_range("2024-01-01", periods=3)
    # 指数取中性 50：**不能取 10**——10 恰好命中 `EXTREME_FEAR_TRIGGER`（下闭区间），
    # 会走「极恐提前释放弹药」分支，掩盖本测试要验证的裁决逻辑。
    us = _us(idx, [50.0] * 3)
    cr = _cr(idx, [50.0] * 3)
    # 大盘比值恒为 0.25/0.20 = 1.25
    us["drawdown"] = [0.25, 0.25, 0.25]
    # 加密三批的比值 0.95/0.30=3.17、0.95/0.50=1.90、0.95/0.70=1.36，**全程 > 1.25**
    cr["drawdown"] = [0.95, 0.95, 0.95]
    out = pipeline.run_portfolio(us, cr, write=False)
    per = config.AMMO_PER_BATCH
    assert out["ammo_crypto"].iloc[-1] == pytest.approx(per * 2), "加密最多 2 批"
    assert out["ammo_us"].iloc[-1] == pytest.approx(per * 1), "第 3 批必须归大盘"


def test_run_portfolio_crypto_trend_blocks_core():
    """加密趋势过滤生效时，加密核心仓必须减半。"""
    idx = pd.bdate_range("2024-01-01", periods=3)
    cr = _cr(idx, [10.0] * 3)
    cr["trend"] = config.TREND_FILTER_FACTOR
    out = pipeline.run_portfolio(_us(idx, [np.nan] * 3), cr, write=False)
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert out["crypto_core"].iloc[0] == pytest.approx(full * config.TREND_FILTER_FACTOR)
    assert bool(out["trend_blocked_crypto"].iloc[0]) is True
