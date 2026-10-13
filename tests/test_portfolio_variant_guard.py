# -*- coding: utf-8 -*-
"""B2/B3 组合级变体等价性守卫（规划 §5 守卫清单：`test_portfolio_variant_guard`）。

背景（团队交叉评审 2026-10-12 §5「等价性守卫」）：
  现有 `test_variant_guard.py` **只覆盖单标的**变换 ✗ ⇒ B2/B3 是**组合级**
  （组合状态源 = `portfolio_features` 的 `basket_ret` 列）⇒ 必须新增本守卫，
  否则视为「无守卫的新机制」✗。

守卫内容（照规划 B2/B3 行的验收）：
  1. **B2/B3 消费 `basket_ret`**：缺该列 ⇒ 返回原样（保守不加规则，与现有变体同风格）；
     有该列 ⇒ `target_position` 被缩放（按组合状态变化）；
  2. **B2 因子封顶 1.0**：组合波动低于目标时**不放大**仓位（`min(1.0, ...)`）；
  3. **三标的同一因子**：B2 是资金池缩放（组合级），同一日三标的乘同一因子；
  4. **B3 触及 dd_floor 清零**：组合回撤达到 `dd_floor`（默认 0.20）⇒ 因子 0；
  5. **V-VOL `archived` 未被改**：B2 是组合级、V-VOL 是逐标的 ⇒ 不重复，
     且**不得**改动 V-VOL 的 `archived` 状态（规划 §5 红线）。
"""
import importlib.util
import os

import numpy as np
import pandas as pd

from fg_system import config
from fg_system import pipeline
from fg_system.backtest import variants as vmod

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_evolve_variant():
    """加载编排脚本（`scripts/evolve_variant.py`），用于测 `build_basket_returns`。"""
    path = os.path.join(REPO, "scripts", "evolve_variant.py")
    spec = importlib.util.spec_from_file_location("evolve_variant_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_prices_long(n=400, symbols=("TQQQ", "SOXL", "UPRO",
                                    "QQQ", "SOXX", "SPY"),
                    start="2020-01-01", vol=0.01):
    """构造 prices 长表（含 ETF 与无杠杆底层），供 `long_to_wide` + 权重使用。"""
    rng = np.random.default_rng(42)
    idx = pd.date_range(start, periods=n, freq="B")
    frames = []
    for i, s in enumerate(symbols):
        close = 100.0 * np.cumprod(1.0 + rng.normal(0.0003, vol * (1 + 0.2 * i), n))
        frames.append(pd.DataFrame({
            "date": idx, "symbol": s,
            "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": 1_000_000.0}))
    return pd.concat(frames, ignore_index=True)


def _mk_features(n=120):
    """纯 features（含 target_position），与 `test_variant_guard.py` 同构。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    target = 0.5 + 0.1 * np.sin(np.arange(n) / 5.0)
    return pd.DataFrame(
        {"fg_index": 50.0, "zone": 2.0, "target_position": target}, index=idx)


def _mk_portfolio(n=120, basket_ret=None):
    """组合特征（含 basket_ret 组合篮子日收益）。缺 basket_ret 时只给阻断列。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({"trend_blocked_us": np.zeros(n, dtype=bool),
                       "us_core": 0.3}, index=idx)
    if basket_ret is not None:
        df["basket_ret"] = np.asarray(basket_ret, dtype=float)
    return df


# ---------------------------------------------------------------- B2 注册
def test_b2_registered_with_label():
    """B2 变体必须注册（`V-PVOL`：组合级波动率目标）。"""
    assert "V-PVOL" in vmod.VARIANTS or "V-B2" in vmod.VARIANTS, (
        "B2 组合级 vol targeting 变体未注册")
    key = "V-PVOL" if "V-PVOL" in vmod.VARIANTS else "V-B2"
    assert vmod.VARIANTS[key].get("label")


# ---------------------------------------------------------------- B2 消费 basket_ret
def test_b2_missing_basket_ret_returns_identical():
    """B2 缺 `basket_ret` 列 ⇒ 返回原样（保守不加规则）。"""
    f = _mk_features(120)
    pf = _mk_portfolio(len(f))  # 无 basket_ret
    out = vmod.apply_variant(f, pf, "V-PVOL")
    assert out.index.equals(f.index)
    assert np.allclose(out["target_position"].values,
                       f["target_position"].values, rtol=0, atol=0)


def test_b2_high_portfolio_vol_shrinks_position():
    """B2：组合波动高于目标 ⇒ 降仓（消费 basket_ret）。"""
    f = _mk_features(120)
    n = len(f)
    rng = np.random.default_rng(11)
    # 高波动组合收益（σ 年化远高于目标 0.25）
    br = rng.normal(0.0, 0.05, n)
    pf = _mk_portfolio(n, basket_ret=br)
    out = vmod.apply_variant(f, pf, "V-PVOL")
    pos = out["target_position"].values
    base = f["target_position"].values
    assert (pos[40:] < base[40:] * 0.999).any(), "高波动组合未降仓"


def test_b2_never_lever_up():
    """B2 因子封顶 1.0：组合波动低于目标时**不放大**仓位。"""
    f = _mk_features(120)
    n = len(f)
    # 极低波动组合收益 ⇒ vol_target/σ 会 > 1，必须封顶为 1.0
    br = np.full(n, 0.0)
    br[::2] = 1e-5
    pf = _mk_portfolio(n, basket_ret=br)
    out = vmod.apply_variant(f, pf, "V-PVOL")
    pos = out["target_position"].values
    base = f["target_position"].values
    assert np.all(pos <= base + 1e-12), "B2 放大了仓位（违反封顶 1.0）"
    # 低波动段应几乎等于原仓位（因子 = 1.0）
    assert np.allclose(pos[40:], base[40:], rtol=1e-9, atol=1e-9)


def test_b2_same_factor_across_symbols():
    """B2 是组合级资金池缩放：三标的同一日乘**同一因子**（不逐标的）。"""
    n = 120
    rng = np.random.default_rng(5)
    br = rng.normal(0.0, 0.02, n)
    pf = _mk_portfolio(n, basket_ret=br)
    # 造三份**不同**单标的 features，但 target/无价格列相同 ⇒ 因子只来自组合
    ratios = []
    for seed in (1, 2, 3):
        f = _mk_features(n)
        out = vmod.apply_variant(f, pf, "V-PVOL")
        r = (out["target_position"].values
             / f["target_position"].values)
        ratios.append(r)
    # 三个标的的缩放比必须逐位相同（同一因子）
    assert np.allclose(ratios[0], ratios[1], rtol=0, atol=0)
    assert np.allclose(ratios[1], ratios[2], rtol=0, atol=0)


# ---------------------------------------------------------------- B3 组合回撤控制
def test_b3_missing_basket_ret_returns_identical():
    """B3 缺 `basket_ret` 列 ⇒ 返回原样（保守不加规则）。"""
    f = _mk_features(120)
    pf = _mk_portfolio(len(f))
    out = vmod.apply_variant(f, pf, "V-DDC")
    assert np.allclose(out["target_position"].values,
                       f["target_position"].values, rtol=0, atol=0)


def test_b3_drawdown_scales_down():
    """B3：组合净值回撤扩大 ⇒ 仓位因子随之减小（clamp 到 [0,1]）。"""
    f = _mk_features(120)
    n = len(f)
    br = np.zeros(n)
    # 前 60 日缓涨，后 60 日持续下跌 ⇒ 组合回撤扩大
    br[:60] = 0.001
    br[60:] = -0.01
    pf = _mk_portfolio(n, basket_ret=br)
    out = vmod.apply_variant(f, pf, "V-DDC")
    pos = out["target_position"].values
    base = f["target_position"].values
    # 回撤段应有降仓；且不放大
    assert (pos[70:] < base[70:] - 1e-12).any(), "组合回撤段未降仓"
    assert np.all(pos <= base + 1e-12)


def test_b3_touch_floor_clears_position():
    """B3 触及 dd_floor（默认 0.20）⇒ 因子 0（清零）。"""
    f = _mk_features(120)
    n = len(f)
    br = np.zeros(n)
    br[:20] = 0.0
    br[20:] = -0.03  # 20 日累计跌 ~ -45%，远超 20% floor
    pf = _mk_portfolio(n, basket_ret=br)
    out = vmod.apply_variant(f, pf, "V-DDC")
    pos = out["target_position"].values
    assert pos[-1] == 0.0, "触及 dd_floor 未清零（dd=%.3f）" % (
        np.prod(1 + br[20:]) - 1.0)


def test_b3_never_lever_up():
    """B3 因子恒 ≤ 1.0（组合无回撤时因子 = 1，不放大）。"""
    f = _mk_features(120)
    n = len(f)
    br = np.full(n, 0.002)  # 单边上涨 ⇒ dd == 0 ⇒ 因子 1.0
    pf = _mk_portfolio(n, basket_ret=br)
    out = vmod.apply_variant(f, pf, "V-DDC")
    pos = out["target_position"].values
    base = f["target_position"].values
    assert np.all(pos <= base + 1e-12)
    assert np.allclose(pos, base, rtol=1e-9, atol=1e-9)


# ---------------------------------------------------------------- V-VOL 状态未改
def test_vvol_archived_unchanged():
    """B2 是组合级 ⇒ 不重复逐标的 V-VOL；**不得**改 V-VOL 的 archived 状态。"""
    assert vmod.VARIANTS["V-VOL"].get("archived") is True, (
        "V-VOL 的 archived 状态被改动（规划 §5 红线：B2 不重复 V-VOL）")


# ---------------------------------------------------------------- 编排层 basket_ret
def test_build_basket_returns_matches_pipeline():
    """编排层 `build_basket_returns` 必须复用 pipeline（inv_vol 权重 + 篮子收益）。"""
    mod = _load_evolve_variant()
    prices = _mk_prices_long(400)
    br = mod.build_basket_returns(prices)
    # 独立复算（同口径）：long_to_wide → risk_weight_series → weighted_basket_returns
    wide = pipeline.long_to_wide(prices)
    w = pipeline.risk_weight_series(wide)
    exp = pipeline.weighted_basket_returns(wide, w, list(config.SYMBOLS))
    pd.testing.assert_series_equal(br, exp, check_freq=False)


def test_basket_ret_is_strategy_independent():
    """`basket_ret` 只由价格 + 权重决定，**不含**策略收益（防自指/前视）。

    同一批 prices、改变输入行序（不改变值）⇒ basket_ret 逐位不变；
    且其值域合理（日收益，非净值）。
    """
    mod = _load_evolve_variant()
    prices = _mk_prices_long(300)
    br1 = mod.build_basket_returns(prices)
    br2 = mod.build_basket_returns(prices.sample(frac=1.0, random_state=1))
    pd.testing.assert_series_equal(br1, br2, check_freq=False)
    # 日收益量级（不应是累计净值那种 100+ 的值）
    assert br1.abs().max() < 1.0


def test_b2_b3_consume_injected_basket_ret_end_to_end():
    """编排层注入 basket_ret 后，B2/B3 在组合级特征上确实改变 target_position。"""
    mod = _load_evolve_variant()
    # prices 覆盖 features 区间（features 自 2024-01-01 起 200 交易日）；
    # 用高波动（日 ~4%）⇒ 组合 σ 年化 > vol_target 0.25 ⇒ B2 降仓；
    # 随机游走必有回撤 ⇒ B3 降仓。
    prices = _mk_prices_long(1400, start="2020-01-01", vol=0.04)
    br = mod.build_basket_returns(prices)
    f = _mk_features(200)
    idx = f.index
    # 把 basket_ret 对齐到 features 日期（prices 范围覆盖 features）
    br = br.reindex(idx)
    assert not br.isna().all(), "构造日期未覆盖（basket_ret 全 NaN）"
    pf = pd.DataFrame({"date": idx,
                       "trend_blocked_us": np.zeros(len(f), dtype=bool),
                       "basket_ret": br.values})
    # 注入后的组合特征（模拟编排层产物：含 date 列，apply_variant 会 set_index）
    for vk in ("V-PVOL", "V-DDC"):
        out = vmod.apply_variant(f, pf, vk)
        # 至少在某些交易日发生缩放（真实价格构造下因子 ≠ 1）
        changed = ~np.isclose(out["target_position"].values,
                              f["target_position"].values, rtol=0, atol=1e-12)
        assert changed.any(), "%s 未消费 basket_ret（target 未变）" % vk
        # 永不放大
        assert np.all(out["target_position"].values
                      <= f["target_position"].values + 1e-12)
