# -*- coding: utf-8 -*-
"""A1（守猪待兔清仓线全系统回放）的单元测试与等价性红线。

设计：docs/superpowers/specs/2026-09-24-shoutu-variants-replay-design.md
"""
import ast
import os

import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system import pipeline
from fg_system import shoutu_variants
from fg_system.signal import market_signal as ms


def test_market_target_core_override_replaces_market_core():
    """`core` 给定时替换五档结果（50.0 的默认 core 是 0.18，这里应变成 0.123）。"""
    out, _ = ms.market_target(50.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                              "us_equity", core=0.123)
    assert abs(out.core_position - 0.123) < 1e-9


def test_market_target_core_none_is_identical_to_default():
    """等价性红线：不传 `core` 与传 `core=None` 逐位相同。"""
    a, _ = ms.market_target(50.0, 0.0, 1.0, ms.MarketState(market="us_equity"), "us_equity")
    b, _ = ms.market_target(50.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                            "us_equity", core=None)
    assert a == b


def test_market_target_core_nan_is_no_signal():
    """变体 core 为 NaN（warmup）⇒ 与「指数无效」同语义（core_position=None）。"""
    out, _ = ms.market_target(float("nan"), 0.0, 1.0, ms.MarketState(market="us_equity"),
                              "us_equity", core=float("nan"))
    assert out.core_position is None


def test_market_target_circuit_breaker_still_beats_variant_core():
    """⚠️ 熔断仍然生效：极贪触发时，变体 core 必须被 `full × 熔断底仓` 替换。"""
    out, _ = ms.market_target(config.EXTREME_GREED_TRIGGER, 0.0, 1.0,
                              ms.MarketState(market="us_equity"),
                              "us_equity", core=0.123)
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"] * 1.0
    assert abs(out.core_position - full * config.EXTREME_GREED_FLOOR) < 1e-9


def _us_features(idx, fg_vals, trend=1.0):
    """最小 `us_equity` features（列名与 `run_equity_v2` 对齐）。

    ⚠️ 若与 `tests/test_pipeline_crypto.py` 的既有 helper 不一致，**以那份为准**
    （它是既有约定；本函数只是让本文件自包含）。
    """
    return pd.DataFrame({
        "fg_index": fg_vals, "zone": 2.0, "drawdown": 0.0,
        "core_position": 0.1, "ammo_position": 0.0, "target_position": 0.1,
        "trend": trend, "trend_blocked": trend < 1.0, "warmup": False,
    }, index=idx)


def _cr_features(idx, fg_vals, trend=1.0):
    return pd.DataFrame({
        "crypto_fg_index": fg_vals, "drawdown": 0.0, "trend": trend,
        "trend_blocked": trend < 1.0, "core_position": 0.1, "target_position": 0.1,
        "warmup": False,
    }, index=idx)


def _portfolio_inputs(n=40, fg=50.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return _us_features(idx, [fg] * n), _cr_features(idx, [fg] * n)


def test_run_portfolio_us_core_none_is_identical_to_default():
    """等价性红线：不传 `us_core` 与传 `us_core=None` **逐位相同**。"""
    us, cr = _portfolio_inputs()
    a = pipeline.run_portfolio(us, cr, write=False)
    b = pipeline.run_portfolio(us, cr, write=False, us_core=None)
    pd.testing.assert_frame_equal(a, b)


def test_run_portfolio_us_core_override_reaches_us_core_column():
    """`us_core` 覆盖后，输出的 `us_core` 列等于传入序列。"""
    us, cr = _portfolio_inputs()
    override = pd.Series(0.05, index=us.index)
    out = pipeline.run_portfolio(us, cr, write=False, us_core=override)
    assert out["us_core"].dropna().eq(0.05).all()


def test_run_portfolio_us_core_override_does_not_touch_crypto():
    """覆盖**只作用于 us_equity**，加密核心仓不受影响。"""
    us, cr = _portfolio_inputs()
    base = pipeline.run_portfolio(us, cr, write=False)
    over = pipeline.run_portfolio(us, cr, write=False,
                                 us_core=pd.Series(0.05, index=us.index))
    pd.testing.assert_series_equal(base["crypto_core"], over["crypto_core"])


def test_saturation_of_default_equals_explicit_global_tables():
    """等价性红线：默认参数 == 显式传全局表。"""
    vals = [0.0, 20.0, 39.9, 60.0, 80.0, 99.9]
    a = pipeline.saturation_of(vals)
    b = pipeline.saturation_of(vals, edges=config.ZONE_EDGES,
                              saturation=config.ZONE_SATURATION)
    assert list(a) == list(b)


def test_saturation_of_variant_tables_land_on_expected_zones():
    """V2 边界：守猪待兔 +60→系统 80 落档 3（0.25）；+80→系统 90 落档 4（0.00）。"""
    got = pipeline.saturation_of([80.0, 90.0], edges=[20.0, 40.0, 60.0, 90.0],
                                saturation=[1.00, 0.75, 0.50, 0.25, 0.00])
    assert list(got) == [0.25, 0.00]


def test_saturation_of_v3_never_clears():
    """V3：末档留 25% 底仓 ⇒ 任何值都不给 0。"""
    got = pipeline.saturation_of([0.0, 50.0, 80.0, 100.0],
                                edges=[20.0, 40.0, 60.0, 80.0],
                                saturation=[1.00, 0.75, 0.50, 0.25, 0.25])
    assert min(got) == pytest.approx(0.25)


def test_saturation_of_rejects_table_length_mismatch():
    """档数必须 = 边界数 + 1。"""
    with pytest.raises(ValueError):
        pipeline.saturation_of([50.0], edges=[20.0, 40.0],
                               saturation=[1.0, 0.5, 0.0, 0.0])


# ---------------------------------------------------------------- 评审 A 的 Minor（Step 0）
def test_run_portfolio_rejects_non_series_us_core():
    """⚠️ 传 list/ndarray 必须**抛错**，不得静默全丢（评审 A 的 Minor）。"""
    us, cr = _portfolio_inputs()
    with pytest.raises(TypeError):
        pipeline.run_portfolio(us, cr, write=False, us_core=[0.05] * len(us))


def test_saturation_of_rejects_non_finite_tables():
    """edges / saturation 含 NaN ⇒ 抛错（不得静默给无意义结果）。"""
    with pytest.raises(ValueError):
        pipeline.saturation_of([50.0], edges=[20.0, np.nan, 60.0, 80.0],
                               saturation=[1.0, 0.75, 0.5, 0.25, 0.0])


def test_saturation_of_returns_nan_for_nan_input():
    """⚠️ NaN 输入必须返回 NaN，**不得**静默落到末档（那会把「无信号」变成「清仓」）。"""
    got = pipeline.saturation_of([50.0, np.nan, 80.0])
    assert got[0] == pytest.approx(0.50)
    assert np.isnan(got[1]), "NaN 输入必须返回 NaN（评审 B 的 Critical）"
    assert got[2] == pytest.approx(0.00)


def test_saturation_of_variant_tables_also_keep_nan():
    """变体表同样适用（否则 warmup 期会被当成清仓）。"""
    got = pipeline.saturation_of([np.nan], edges=[20.0, 40.0, 60.0, 90.0],
                                saturation=[1.00, 0.75, 0.50, 0.25, 0.00])
    assert np.isnan(got[0])


# ---------------------------------------------------------------- Task 4：shoutu_variants
def _hist_long(n=30):
    """构造一条守猪待兔长表：三个主标的，值在 0~100 之间来回。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    rows = []
    for s in config.SYMBOLS:
        for i, d in enumerate(idx):
            rows.append({"date": d, "symbol": s, "score": 70.0 if i % 2 else 10.0,
                         "price": 100.0 + i})
    return pd.DataFrame(rows)


def test_variants_tables_have_valid_lengths():
    """档数必须 = 边界数 + 1（先验表的自检）。"""
    for key, v in shoutu_variants.VARIANTS.items():
        assert len(v["saturation"]) == len(v["edges"]) + 1, key


def test_v1_matches_existing_shoutu_core_series():
    """⚠️ 构造一致性：V1（现状表）必须与现成 `shoutu_core_series(...)` 逐位相同。"""
    us = _us_features(pd.date_range("2024-01-01", periods=30, freq="B"), [50.0] * 30)
    w = pd.DataFrame(1.0 / 3.0, index=us.index, columns=config.SYMBOLS)
    hist = _hist_long()
    wide = shoutu_variants.shoutu_wide_from_long(hist)
    got = shoutu_variants.variant_core_series(us, w, hist, "V1")
    exp = pipeline.shoutu_core_series(us, w, shoutu_wide=wide)
    pd.testing.assert_series_equal(got, exp)


def test_v3_never_clears_while_v1_does():
    """V3（末档 25%）在档位 4 的日子 core > 0，而 V1 为 0。"""
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    us = _us_features(idx, [50.0] * 30)
    w = pd.DataFrame(1.0 / 3.0, index=idx, columns=config.SYMBOLS)
    hist = _hist_long()
    v1 = shoutu_variants.variant_core_series(us, w, hist, "V1")
    v3 = shoutu_variants.variant_core_series(us, w, hist, "V3")
    assert (v1 == 0.0).any(), "V1 应当出现清仓日（守猪待兔 >= +60）"
    assert (v3 > 0.0).all(), "V3 从不清仓"


def test_variant_core_requires_trend_column():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    us = _us_features(idx, [50.0] * 10).drop(columns=["trend"])
    with pytest.raises(ValueError):
        shoutu_variants.variant_core_series(us, None, _hist_long(), "V1")


def test_variant_core_rejects_unknown_variant_and_empty_history():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    us = _us_features(idx, [50.0] * 10)
    with pytest.raises(KeyError):
        shoutu_variants.variant_core_series(us, None, _hist_long(), "V9")
    with pytest.raises(ValueError):
        shoutu_variants.variant_core_series(us, None, pd.DataFrame(), "V1")


def test_shoutu_wide_from_long_rejects_no_main_symbols():
    """主样本零覆盖 ⇒ 抛错（**不得静默回退成基准**）。"""
    other = pd.DataFrame({"date": [pd.Timestamp("2024-01-02")], "symbol": ["CONL"],
                          "score": [10.0], "price": [1.0]})
    with pytest.raises(ValueError):
        shoutu_variants.shoutu_wide_from_long(other)


# ---------------------------------------------------------------- Task 5：回放脚本静态守卫
def _script_src():
    p = os.path.join(config.ROOT, "scripts", "analyze_shoutu_variants.py")
    return open(p, encoding="utf-8").read()


def test_script_uses_library_functions():
    """计算必须走库层，不得在脚本里重写档位/指标逻辑。"""
    called = set()
    for node in ast.walk(ast.parse(_script_src())):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                called.add(f.attr)
            elif isinstance(f, ast.Name):
                called.add(f.id)
    for need in ("variant_core_series", "run_portfolio", "performance_metrics",
                 "run_single"):
        assert need in called, "脚本没有调用 %s" % need


def test_script_does_not_hardcode_symbols_or_variant_tables():
    """标的与变体表都必须来自 config / shoutu_variants，不得硬编码。"""
    src = _script_src()
    lits = [n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for sym in config.SHOUTU_SYMBOLS:
        assert not any(s == sym for s in lits), "脚本里硬编码了标的 %s" % sym
    assert not any(s in ("V1", "V2", "V3") for s in lits), \
        "变体键必须来自 shoutu_variants.VARIANTS，不得在脚本里硬编码"


def test_script_does_not_read_global_zone_tables():
    """变体档位表必须来自 shoutu_variants，不得在脚本里读/改全局 ZONE_*。"""
    src = _script_src()
    assert "ZONE_EDGES" not in src
    assert "ZONE_SATURATION" not in src


# ---------------------------------------------------------------- Task 5b：归因表
def test_attribution_sums_to_basket_return():
    """一致性（构造保证）：各标的加权贡献之和 == `Σ_t base_t × 篮子收益_t`。

    ⚠️ 若 `pipeline.weighted_basket_returns` 内部对首日 NaN 的处理与
    `pct_change(fill_method=None)` 不同，请以**库内实现**为准对齐期望值
    —— **只对齐口径，不得放宽断言**（仍必须是严格相等）。
    """
    idx = pd.date_range("2024-01-01", periods=20, freq="B")
    wide = pd.DataFrame({(s, "close"): [100.0 + i for i in range(20)]
                         for s in config.SYMBOLS}, index=idx)
    w = pd.DataFrame(1.0 / 3.0, index=idx, columns=config.SYMBOLS)
    base = pd.Series(0.5, index=idx)
    mask = pd.Series(True, index=idx)
    got = shoutu_variants.attribution_contributions(wide, w, base, mask)
    basket = pipeline.weighted_basket_returns(wide, w)
    assert got.sum() == pytest.approx(float((base * basket).sum()))
    assert list(got.index) == list(config.SYMBOLS)


def test_attribution_respects_mask():
    """掩码外的日子不计入。"""
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    wide = pd.DataFrame({(s, "close"): [100.0 + i for i in range(10)]
                         for s in config.SYMBOLS}, index=idx)
    w = pd.DataFrame(1.0 / 3.0, index=idx, columns=config.SYMBOLS)
    base = pd.Series(0.5, index=idx)
    mask = pd.Series([True, False] * 5, index=idx)
    got = shoutu_variants.attribution_contributions(wide, w, base, mask)
    all_on = shoutu_variants.attribution_contributions(
        wide, w, base, pd.Series(True, index=idx))
    assert (got < all_on).all()


# ---------------------------------------------------------------- Task 3：keyed extremes
def test_market_target_trigger_index_none_is_identical_to_default():
    """等价性红线：不传 `trigger_index` 与传 `trigger_index=None` 逐位相同。"""
    a, _ = ms.market_target(90.0, 0.0, 1.0, ms.MarketState(market="us_equity"), "us_equity")
    b, _ = ms.market_target(90.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                            "us_equity", trigger_index=None)
    assert a == b


def test_market_target_trigger_index_drives_circuit_breaker():
    """`trigger_index` 驱动熔断：`index_value` 低但 `trigger_index` 极贪 ⇒ 仍熔断。"""
    out, _ = ms.market_target(10.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                              "us_equity",
                              trigger_index=float(config.EXTREME_GREED_TRIGGER))
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"] * 1.0
    assert abs(out.core_position - full * config.EXTREME_GREED_FLOOR) < 1e-9
    assert out.extreme is True


def test_market_target_trigger_index_drives_extreme_fear():
    """`trigger_index` 驱动极恐：`index_value` 中性但 `trigger_index` 极恐 ⇒ 置位。"""
    out, _ = ms.market_target(50.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                              "us_equity",
                              trigger_index=float(config.EXTREME_FEAR_TRIGGER))
    assert out.extreme_fear is True


def test_market_target_trigger_index_nan_falls_back_to_index_value():
    """`trigger_index` 为 NaN ⇒ 退回 `index_value`（NaN 不是有效信号）。"""
    a, _ = ms.market_target(90.0, 0.0, 1.0, ms.MarketState(market="us_equity"), "us_equity")
    b, _ = ms.market_target(90.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                            "us_equity", trigger_index=float("nan"))
    assert a == b


def test_market_target_trigger_index_drives_circuit_breaker_unlock():
    """⚠️ 守卫：熔断**解锁**的指数条件也必须吃 `trigger_index`。

    spec §9.3-3：只换**指数条件**（回落至 `EXTREME_GREED_UNLOCK_INDEX` /
    自峰值回落 `EXTREME_GREED_UNLOCK_DROP` 点），价格条件（反弹 10%）不变。
    若这条失败 ⇒ 解锁仍看市场指数 ⇒ 熔断会「该解不解」。
    """
    st = ms.MarketState(market="us_equity")
    st.circuit_breaker = True
    st.cb_trigger_index = 90.0
    out, new_state = ms.market_target(
        88.0, 0.0, 1.0, st, "us_equity",
        trigger_index=float(config.EXTREME_GREED_UNLOCK_INDEX) - 1.0)
    assert new_state.circuit_breaker is False


def test_market_target_core_override_and_trigger_index_are_independent():
    """⚠️ 守卫：五档来源（`core=`）与触发源（`trigger_index=`）**解耦**。

    spec 的核心卖点：变体 core 与极端规则触发源是两个独立注入点。
    `core=0.9`（变体给得很高）+ `trigger_index` 极贪 ⇒ 熔断**仍压过**变体 core，
    且用的是 `full × EXTREME_GREED_FLOOR`（**不是** `0.9 × FLOOR`）。
    若这条失败 ⇒ 熔断不再优先于变体 ⇒ A2 的 keyed extremes 失效。
    """
    out, _ = ms.market_target(50.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                              "us_equity", core=0.9,
                              trigger_index=float(config.EXTREME_GREED_TRIGGER))
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"] * 1.0
    assert abs(out.core_position - full * config.EXTREME_GREED_FLOOR) < 1e-9
    assert out.extreme is True


# ---------------------------------------------------------------- Task 4：run_portfolio 透传 + 覆盖率守卫
def test_run_portfolio_us_trigger_index_none_is_identical_to_default():
    """等价性红线：不传 `us_trigger_index` 与传 `None` 逐位相同。"""
    us, cr = _portfolio_inputs()
    a = pipeline.run_portfolio(us, cr, write=False)
    b = pipeline.run_portfolio(us, cr, write=False, us_trigger_index=None)
    pd.testing.assert_frame_equal(a, b)


def test_run_portfolio_us_trigger_index_reaches_market_target():
    """`us_trigger_index` 极贪 ⇒ 熔断，即使 `fg_index` 中性。"""
    us, cr = _portfolio_inputs(fg=50.0)
    trig = pd.Series(float(config.EXTREME_GREED_TRIGGER), index=us.index)
    out = pipeline.run_portfolio(us, cr, write=False, us_trigger_index=trig)
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert abs(out["us_core"].dropna().iloc[-1] - full * config.EXTREME_GREED_FLOOR) < 1e-9


def test_run_portfolio_rejects_non_series_us_trigger_index():
    """传 list 必须抛错（同 `us_core` 的守卫）。"""
    us, cr = _portfolio_inputs()
    with pytest.raises(TypeError):
        pipeline.run_portfolio(us, cr, write=False, us_trigger_index=[50.0] * len(us))


def test_run_portfolio_rejects_us_core_with_nan():
    """⚠️ 含 NaN 的 `us_core` ⇒ 抛错（拒绝静默退回市场指数口径，spec §7.5）。"""
    us, cr = _portfolio_inputs()
    bad = pd.Series(0.05, index=us.index)
    bad.iloc[3] = float("nan")
    with pytest.raises(ValueError) as e:
        pipeline.run_portfolio(us, cr, write=False, us_core=bad)
    assert "NaN" in str(e.value)


def test_run_portfolio_rejects_us_trigger_index_with_nan():
    """⚠️ 含 NaN 的 `us_trigger_index` ⇒ 抛错（对称守卫）。"""
    us, cr = _portfolio_inputs()
    bad = pd.Series(50.0, index=us.index)
    bad.iloc[3] = float("nan")
    with pytest.raises(ValueError) as e:
        pipeline.run_portfolio(us, cr, write=False, us_trigger_index=bad)
    assert "NaN" in str(e.value)


def test_run_portfolio_allows_warmup_nan_in_us_core():
    """⚠️ warmup 天（`fg_index` 为 NaN）的 `us_core` NaN 是**预期**的，不得抛错。

    实测（Task 1）：A1 三个变体的 `us_core` 各有 **760 天 NaN，恰好等于 warmup**。
    守卫若不放行，每个变体回放都会抛错 ⇒ 打断 warmup 语义。
    """
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    us = _us_features(idx, [float("nan")] * 10 + [50.0] * 30)
    cr = _cr_features(idx, [50.0] * 40)
    core = pd.Series(0.05, index=idx)
    core.iloc[:10] = float("nan")          # 与 warmup 对齐
    out = pipeline.run_portfolio(us, cr, write=False, us_core=core)
    assert out["us_core"].iloc[:10].isna().all()
    assert out["us_core"].iloc[10:].eq(0.05).all()


def test_run_portfolio_allows_warmup_nan_in_both_series():
    """⚠️ 守卫：`us_core` 与 `us_trigger_index` **同时**传，warmup 的 NaN 都放行。

    若这条失败 ⇒ 两条序列同时启用时 warmup 会被误判为缺失。
    """
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    us = _us_features(idx, [float("nan")] * 10 + [50.0] * 30)
    cr = _cr_features(idx, [50.0] * 40)
    core = pd.Series(0.05, index=idx)
    core.iloc[:10] = float("nan")
    trig = pd.Series(50.0, index=idx)
    trig.iloc[:10] = float("nan")
    out = pipeline.run_portfolio(us, cr, write=False, us_core=core,
                                 us_trigger_index=trig)
    assert out["us_core"].iloc[10:].eq(0.05).all()


def test_run_portfolio_rejects_trigger_index_shorter_than_window():
    """⚠️ 守卫：`us_trigger_index` 比窗口短 ⇒ `reindex` 补 NaN ⇒ 抛错。

    这条锁住「长度不匹配必须显式报错，不得静默少算几天」。
    """
    us, cr = _portfolio_inputs()
    short = pd.Series(50.0, index=us.index[:10])
    with pytest.raises(ValueError):
        pipeline.run_portfolio(us, cr, write=False, us_trigger_index=short)


def test_run_portfolio_rejects_core_with_disjoint_index():
    """⚠️ 守卫：`us_core` 的 index 与窗口**完全不交叠** ⇒ `reindex` 全 NaN ⇒ 抛错。

    这条锁住「index 传错（例如 RangeIndex 或别的日期段）不得静默全丢」。
    """
    us, cr = _portfolio_inputs()
    other = pd.Series(0.05, index=pd.date_range("2030-01-01", periods=len(us), freq="B"))
    with pytest.raises(ValueError):
        pipeline.run_portfolio(us, cr, write=False, us_core=other)


# ---------------------------------------------------------------- A2-E Task 1：keyed 历史区间红线
def test_keyed_extremes_is_identity_before_effect_window():
    """⚠️ 守卫：`keyed=True` 在守猪待兔覆盖区间**之前**必须与 `keyed=False` 逐位相同。

    依据 A2 spec §6 的关键性质：历史区间守猪待兔无数据 ⇒ `shoutu_symbol_index` 三级回退到
    `fg_index` ⇒ 因 `Σ w_i = 1`，`shoutu_market_index` **逐位等于 `fg_index`**。
    若这条失败 ⇒ keyed extremes 在历史区间改变了行为，与 spec 冲突（且说明实现有问题）。
    """
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    us = pd.DataFrame({"fg_index": [50.0] * 40, "trend": [1.0] * 40}, index=idx)
    cr = pd.DataFrame({"crypto_fg_index": [50.0] * 40, "trend": [1.0] * 40,
                       "drawdown": 0.0, "warmup": False}, index=idx)
    # 空的守猪待兔宽表 ⇒ 全部回退 fg_index
    trig = pipeline.shoutu_market_index(us, pd.DataFrame({"TQQQ": [0.5] * 40,
                                                          "SOXL": [0.5] * 40}, index=idx),
                                        shoutu_wide=pd.DataFrame(),
                                        symbols=["TQQQ", "SOXL"])
    assert trig.round(9).tolist() == us["fg_index"].round(9).tolist()


# ---------------------------------------------------------------- 研究用底层映射（2026-09-28）
def test_signal_underlying_map_covers_all_shoutu_symbols():
    """映射必须覆盖**全部**守猪待兔标的。

    漏一个 ⇒ `risk_weight_series` 在那一列取不到底层 ⇒ 按 §4C.6「任一标的缺波动率
    ⇒ 整行退化为等权」⇒ 全样本 inv-vol 会**静默**全退化成等权（看起来像跑了、其实没跑）。
    """
    for sym in config.SHOUTU_SYMBOLS:
        assert sym in config.SIGNAL_UNDERLYING_MAP, "%s 缺无杠杆底层" % sym


def test_signal_underlying_map_does_not_touch_production():
    """⚠️ 红线：研究用映射**不得**污染生产 `UNDERLYING_MAP`。

    主样本三标的的底层必须与生产**逐字一致**，否则研究口径会悄悄偏离生产。
    """
    assert set(config.UNDERLYING_MAP) == set(config.SYMBOLS)
    for sym, und in config.UNDERLYING_MAP.items():
        assert config.SIGNAL_UNDERLYING_MAP[sym] == und, \
            "%s 的研究底层与生产不一致" % sym


def test_gdxu_underlying_is_not_gdx_alone():
    """⚠️ **事实锁**：GDXU 的底层**不是** GDX 单只。

    GDXU = MicroSectors Gold Miners 3X Leveraged **ETN**（BMO），跟踪指数 `MINERS`
    = **GDX + GDXJ 市值加权**。旧文档写的「GDXU = 3×GDX」不准确。
    若有人把映射改回单只 GDX（或把 blend 改成单键），本用例必须失败。
    """
    assert config.SIGNAL_UNDERLYING_MAP["GDXU"] != "GDX", \
        "GDXU 的底层是指数 MINERS（GDX+GDXJ），不是 GDX 单只"
    assert set(config.GDXU_UNDERLYING_BLEND) == {"GDX", "GDXJ"}
    assert sum(config.GDXU_UNDERLYING_BLEND.values()) == pytest.approx(1.0)


def test_gdxj_is_fetchable():
    """GDXJ 必须进抓取清单（否则 GDXU 的 blend 少一只、整条通路取不到 σ）。"""
    assert "GDXJ" in config.RESEARCH_SYMBOLS
    assert "GDXJ" in config.FETCH_SYMBOLS
    assert "GDXJ" not in config.SYMBOLS, "GDXJ 是研究标的，不得进生产篮子"


def test_blend_close_is_weighted_sum():
    """合成序列必须等于加权和（同列同日对齐）。"""
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    wide = pd.DataFrame({("A", "close"): [100.0, 110.0, 121.0],
                         ("B", "close"): [200.0, 180.0, 198.0]}, index=idx)
    got = pipeline.blend_close(wide, {"A": 0.75, "B": 0.25})
    assert got.tolist() == pytest.approx([125.0, 127.5, 140.25])


def test_blend_close_keeps_missing_price_as_nan():
    """缺价必须是 NaN，**不得**前向填充（同 §4.3 价格类缺失）。"""
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    wide = pd.DataFrame({("A", "close"): [1.0, np.nan, 3.0],
                         ("B", "close"): [1.0, 1.0, 1.0]}, index=idx)
    got = pipeline.blend_close(wide, {"A": 0.5, "B": 0.5})
    assert np.isnan(got.iloc[1])


def test_blend_close_rejects_weights_not_summing_to_one():
    """权重和不为 1 ⇒ 抛错（**不得**静默归一化）。"""
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    wide = pd.DataFrame({("A", "close"): [1.0, 2.0]}, index=idx)
    with pytest.raises(ValueError):
        pipeline.blend_close(wide, {"A": 0.9})


def test_blend_close_rejects_missing_column():
    """缺列 ⇒ 抛错（**不得**静默少算一只，那等于悄悄换了底层）。"""
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    wide = pd.DataFrame({("A", "close"): [1.0, 2.0]}, index=idx)
    with pytest.raises(KeyError):
        pipeline.blend_close(wide, {"A": 0.5, "B": 0.5})


def _vol_wide(n=400, seed=7):
    """构造三只主标的的底层 + 一条额外列（用于验证映射真的生效）。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    return idx, pd.DataFrame({
        ("QQQ", "close"): 100.0 * np.cumprod(1 + rng.normal(0, 0.010, n)),
        ("SOXX", "close"): 100.0 * np.cumprod(1 + rng.normal(0, 0.020, n)),
        ("SPY", "close"): 100.0 * np.cumprod(1 + rng.normal(0, 0.008, n)),
        ("ALT", "close"): 100.0 * np.cumprod(1 + rng.normal(0, 0.050, n)),
    }, index=idx)


def test_risk_weight_series_underlying_map_default_is_identical():
    """等价性红线：不传 `underlying_map` 与传 `None` / 显式传 `UNDERLYING_MAP`
    **三者逐位相同**（生产口径不得被新参数改变）。"""
    _, wide = _vol_wide()
    a = pipeline.risk_weight_series(wide)
    b = pipeline.risk_weight_series(wide, underlying_map=None)
    c = pipeline.risk_weight_series(wide, underlying_map=config.UNDERLYING_MAP)
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(a, c)


def test_risk_weight_series_custom_map_changes_vol_source():
    """换映射必须**真的**换 σ 来源（否则该参数是死代码）。"""
    _, wide = _vol_wide()
    a = pipeline.risk_weight_series(wide)
    b = pipeline.risk_weight_series(
        wide, underlying_map=dict(config.UNDERLYING_MAP, TQQQ="ALT"))
    assert not a.equals(b), "换了 σ 来源，权重必须变化"


def test_risk_weight_series_missing_map_entry_raises():
    """映射缺某个 symbol ⇒ KeyError（**不得**静默用别的列）。"""
    _, wide = _vol_wide(n=5)
    with pytest.raises(KeyError):
        pipeline.risk_weight_series(wide, underlying_map={})


def test_variants_script_forces_utf8_stdout():
    """守卫：脚本必须把 stdout 固定为 UTF-8。

    为什么：定时任务 / CI / `>` 重定向会把 stdout 写进文件，Windows 默认 **cp936**
    ⇒ `⚠️` / `⇒` / `—` 全变成 `??`，日志事后不可读（实测本脚本重定向后口径提醒行乱码）。
    这条与「脚本不得硬编码标的」同类：都是**脚本层的不变量**，改动时不能悄悄丢掉。
    """
    src = _script_src()
    assert "reconfigure" in src, "脚本没有把 stdout 固定为 UTF-8"
    assert 'encoding="utf-8"' in src, "reconfigure 必须显式指定 utf-8"


def test_signal_wide_adds_gdxu_blend_and_crypto_underlying():
    """`pipeline.signal_wide` 必须补齐**两个**非生产底层列。

    为什么需要它（第 12.28 条①）：按 `SHOUTU_SYMBOLS`（8 个）算 inv-vol 权重时，
    `GDXU` 的底层是**合成列** `GDXU_UND`（GDX+GDXJ 市值加权），
    `CONL` 的底层 `COIN` 在 `crypto_prices.csv`（**不在** `prices.csv`）
    ⇒ 直接用生产宽表会 `KeyError`。

    ⚠️ fixture 必须构造**生产同款**的宽表（含全部非币底层）：
    `signal_wide` 对「不在宽表里的底层」**一律**去 `crypto_prices.csv` 找，
    而那里只有币股。若只放 GDX/GDXJ，循环会去找 QQQ/SOXX/... ⇒ `ValueError`
    （实测踩到：最小 fixture 与本实现互斥）。
    """
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    cols = {("GDX", "close"): [10.0, 11.0, 12.0, 13.0, 14.0],
            ("GDXJ", "close"): [20.0, 21.0, 22.0, 23.0, 24.0]}
    # 非币底层：生产 `load_wide()` 里本来就有它们 ⇒ fixture 必须同款
    for und in ("QQQ", "SOXX", "SPY", "FXI", "AXTI", "CRCL"):
        cols[(und, "close")] = [100.0] * 5
    wide = pd.DataFrame(cols, index=idx)

    out = pipeline.signal_wide(wide)

    # ① GDXU 的合成底层列（GDX+GDXJ 市值加权）
    und = config.GDXU_UNDERLYING_COLUMN
    assert (und, "close") in out.columns, "没补上 GDXU 的合成底层列"
    w = config.GDXU_UNDERLYING_BLEND
    expect = (w["GDX"] * wide[("GDX", "close")]
              + w["GDXJ"] * wide[("GDXJ", "close")])
    assert out[(und, "close")].tolist() == pytest.approx(expect.tolist())

    # ② CONL 的底层 COIN 只能从 crypto_prices.csv 补
    assert ("COIN", "close") in out.columns, "没从 crypto_prices.csv 补上 COIN"

    # ③ 只增列，不改列
    assert ("GDX", "close") in out.columns
    assert len(out.columns) == len(wide.columns) + 2, "应该恰好补 2 列"


def test_signal_wide_is_single_source_with_the_script():
    """**守卫**：脚本不得再自己实现一份「补齐底层列」的逻辑（第 12.26 条⑤ / 第 12.28 条①）。

    ⚠️ **刻意用 AST，不用字符串匹配** —— 字符串守卫会被「换个名字再实现一份」绕过
    （`def _sig_wide(...)` 既不含 `def _signal_wide`，也能通过
    `"pipeline.signal_wide(" in src`），而**那正是本守卫要防的东西**
    （§12.27-① 的教训：静态守卫必须能咬人）。

    判据：脚本里**不得引用**那份逻辑的**两个原料** ——
      · `config.CRYPTO_PRICES_PATH`（币股底层的唯一来源）
      · `config.GDXU_UNDERLYING_BLEND`（GDXU 合成列的唯一来源）
    任何「自己实现一份」的写法都必然要碰其中之一；而库层 `pipeline.signal_wide`
    已把它们封装在内。同时要求脚本**确实调用**了库层函数。
    """
    import ast

    src = open(os.path.join(config.ROOT, "scripts",
                            "analyze_shoutu_variants.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)

    # ① 脚本不得引用那两个「原料」常量
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("CRYPTO_PRICES_PATH",
                                     "GDXU_UNDERLYING_BLEND"), \
                ("脚本自己引用了 %s —— 说明它又实现了一份「补齐底层列」的逻辑；"
                 "必须改为调用 pipeline.signal_wide" % node.attr)

    # ② 脚本必须**调用**库层的 signal_wide（AST 层，不是子串）
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "signal_wide"]
    assert calls, "脚本没有调用 pipeline.signal_wide（必须单源，不得自己实现）"
