# -*- coding: utf-8 -*-
"""守猪待兔**逐标的系数**测试（第 12.26 条 丙-扩展）。

核心要证明的三件事：
  1. **等价性**：`saturation_of` 与 `ms_mod.zone_of` 逐点一致（向量化不能改变语义）
  2. **向后兼容**：无守猪待兔数据时，结果与原市场级口径**完全一致**
     （否则回测结果会变，而历史区间本来就没有守猪待兔数据）
  3. **保守性**：总仓位**不超过**市场级口径（第 12.13 条「不顶边界」）
"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system import pipeline
from fg_system.signal import market_signal as ms_mod


DATES = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"])


def _features(idx=(50.0, 65.0, 30.0), trend=(1.0, 1.0, 1.0)):
    return pd.DataFrame({"fg_index": list(idx), "trend": list(trend)}, index=DATES)


def _weights(symbols=None):
    symbols = symbols or config.SYMBOLS
    return pd.DataFrame(1.0 / len(symbols), index=DATES, columns=symbols)


def _shoutu(values, date="2026-09-23"):
    """构造守猪待兔宽表：只有**一天**有值（模拟当前只有 2 天数据的现实）。"""
    return pd.DataFrame([values], index=pd.to_datetime([date]))


# ---------------------------------------------------------------- 等价性
def test_saturation_matches_zone_of():
    """**守卫**：向量化实现必须与 `ms_mod.zone_of` 逐点一致。

    边界是下闭区间（20 属于档 1），且必须覆盖到边界值本身 ——
    这类 off-by-one 在向量化改写中最容易出错，而它会让仓位系数整体偏移一档。
    """
    vals = np.concatenate([
        np.arange(-110.0, 110.0, 0.5),                     # 连续扫描
        np.asarray(config.ZONE_EDGES, dtype=float),        # 边界本身
        np.asarray(config.ZONE_EDGES, dtype=float) - 1e-9,  # 边界左侧
    ])
    got = pipeline.saturation_of(vals)
    want = np.asarray([config.ZONE_SATURATION[ms_mod.zone_of(v)] for v in vals])
    assert np.array_equal(got, want)


# ---------------------------------------------------------------- 向后兼容（最重要）
def test_no_shoutu_data_equals_market_core():
    """**守卫**：无守猪待兔数据时，必须**完全等于**原市场级口径。

    这条是**回归红线**：历史区间本来就没有守猪待兔数据，
    若结果与原口径不同，说明回测结论全部失效（而回测是既有验收的依据）。
    """
    us = _features()
    w = _weights()
    got = pipeline.shoutu_core_series(us, w, shoutu_wide=pd.DataFrame())
    want = pd.Series(
        [ms_mod.market_core(us["fg_index"].iloc[i], us["trend"].iloc[i], "us_equity")
         for i in range(len(us))], index=us.index)
    pd.testing.assert_series_equal(got, want)


def test_missing_symbol_falls_back_to_market_index():
    """表里没有的标的 ⇒ 该标的退化为市场指数（而不是 NaN 或被跳过）。"""
    us = _features()
    w = _weights()
    idx = pipeline.shoutu_symbol_index(us, shoutu_wide=_shoutu({"TQQQ": 33}))
    # 只有 TQQQ 有值（且只在最后一天）
    assert idx["TQQQ"].iloc[-1] == pytest.approx(66.5)      # (33+100)/2
    assert idx["SOXL"].iloc[-1] == pytest.approx(30.0)      # 回退市场指数
    assert idx["TQQQ"].iloc[0] == pytest.approx(50.0)       # 缺值回退市场指数
    assert idx.notna().all().all()


# ---------------------------------------------------------------- 加权平均
def test_market_saturation_is_weighted_average():
    """市场级系数 = 各标的档位饱和度的**加权平均**。

    TQQQ 66.5→档3(0.25) / SOXL 51.5→档2(0.50) / UPRO 62.0→档3(0.25)
    等权 ⇒ (0.25+0.50+0.25)/3 = 1/3
    """
    us = _features()
    w = _weights()
    wide = _shoutu({"TQQQ": 33, "SOXL": 3, "UPRO": 24})
    sat = pipeline.shoutu_market_saturation(us, w, shoutu_wide=wide)
    assert sat.iloc[-1] == pytest.approx(1.0 / 3.0)
    # 前一天无守猪待兔值 ⇒ 回退市场指数 65 → 档3 → 0.25
    assert sat.iloc[-2] == pytest.approx(0.25)


def test_core_series_uses_trend():
    """趋势系数仍然生效（0.5 折半）。"""
    us = _features(trend=(1.0, 1.0, 0.5))
    w = _weights()
    wide = _shoutu({"TQQQ": 33, "SOXL": 3, "UPRO": 24})
    core = pipeline.shoutu_core_series(us, w, shoutu_wide=wide)
    assert core.iloc[-1] == pytest.approx(
        config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"] * (1.0 / 3.0) * 0.5)


# ---------------------------------------------------------------- 保守性
def test_total_core_never_exceeds_market_level():
    """**守卫**：总仓位不得超过市场级口径（第 12.13 条「不顶边界」）。

    因 Σ(sat_i·w_i) 是加权平均 ∈ [0,1]，而市场级系数是**同一个量纲**，
    故逐标的口径不可能更大。用极端构造验证：全部标的落在最贪档（sat=0）
    时总仓位应为 0，而不是负数或 NaN。
    """
    us = _features()
    w = _weights()
    wide = _shoutu({"TQQQ": 95, "SOXL": 95, "UPRO": 95})   # → 97.5 分位 ⇒ 档4 ⇒ sat 0
    core = pipeline.shoutu_core_series(us, w, shoutu_wide=wide)
    assert core.iloc[-1] == pytest.approx(0.0)
    assert core.notna().all()


def test_symbols_are_independent():
    """不同标的可以落在不同档位（这是"逐标的"的全部意义）。

    构造：TQQQ 极贪(档4, sat 0)、SOXL 极恐(档0, sat 1) ⇒ 平均 0.5，
    与"两个都是中性"的结果相同 —— 证明**逐标的差异确实进入了加权平均**，
    而不是被某个单一标的或市场指数支配。
    """
    us = _features()
    w = _weights()
    wide = _shoutu({"TQQQ": 95, "SOXL": -95, "UPRO": 50})
    sat = pipeline.shoutu_market_saturation(us, w, shoutu_wide=wide)
    # TQQQ: (95+100)/2=97.5 → 档4 → 0.00
    # SOXL: (-95+100)/2=2.5  → 档0 → 1.00
    # UPRO: (50+100)/2=75.0  → 档3 → 0.25
    assert sat.iloc[-1] == pytest.approx((0.00 + 1.00 + 0.25) / 3.0)


# ---------------------------------------------------------------- Q8：逐标的分位数
def _long_wide(n=None, symbols=None):
    """构造**足够长**的守猪待兔历史（> RANK_WINDOW），用于分位数口径测试。

    A：从 -100 线性升到 +100（量程大）
    B：从  -20 线性升到  +20（量程小）
    两者**形状相同、分位数相同**，但**绝对水平差异巨大** ——
    这正是"固定阈值跨标的不可比"的构造。
    """
    n = (config.RANK_WINDOW + 50) if n is None else n
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    a = np.linspace(-100.0, 100.0, n)
    b = np.linspace(-20.0, 20.0, n)
    cols = symbols or ["TQQQ", "SOXL", "UPRO"]
    data = {c: (a if c == "TQQQ" else b) for c in cols}
    return pd.DataFrame(data, index=idx)


def _us_like(index):
    """构造与守猪待兔同索引的 us_features（市场指数固定 50 = 档2）。"""
    return pd.DataFrame({"fg_index": 50.0, "trend": 1.0}, index=index)


def test_percentile_mode_is_used_when_history_sufficient():
    """历史足够时，信号指数取自**分位数**（0~100），不是固定阈值。"""
    wide = _long_wide()
    us = _us_like(wide.index)
    idx = pipeline.shoutu_symbol_index(us, shoutu_wide=wide, mode="percentile")
    last = idx.index[-1]
    # A 的固定阈值口径是 (100+100)/2 = 100；分位数口径应接近 100 但**不等于**它
    assert idx["TQQQ"].loc[last] > 95.0
    # B 的固定阈值口径只有 (20+100)/2 = 60；分位数口径应接近 100
    assert idx["SOXL"].loc[last] > 95.0


def test_percentile_makes_symbols_comparable():
    """**Q8 的全部意义**：同一个分位数在不同标的上应落到**同一档位**。

    固定阈值下：A(+100)→100→档4，B(+20)→60→档3（**不同档**）。
    分位数下：两者都是 ~100 分位 ⇒ **同档**。
    若本测试失败，说明"逐标的分位数"没解决它本该解决的问题。
    """
    wide = _long_wide()
    us = _us_like(wide.index)
    last = wide.index[-1]
    pct = pipeline.shoutu_symbol_index(us, shoutu_wide=wide, mode="percentile").loc[last]
    fixed = pipeline.shoutu_symbol_index(us, shoutu_wide=wide, mode="fixed").loc[last]
    assert ms_mod.zone_of(pct["TQQQ"]) == ms_mod.zone_of(pct["SOXL"])
    assert ms_mod.zone_of(fixed["TQQQ"]) != ms_mod.zone_of(fixed["SOXL"])


def test_percentile_falls_back_to_fixed_when_history_insufficient():
    """**守卫**：历史不足 756 日时，必须回退**固定阈值**（而不是留 NaN）。

    守猪待兔当前只有 2 天数据 ⇒ 实际生效的就是这条路径。
    若这里退化成 NaN，逐标的系数会全部回退市场指数 ⇒ 改动完全不可见。
    """
    wide = _shoutu({"TQQQ": 33, "SOXL": 3, "UPRO": 24})
    us = _us_like(wide.index)
    got = pipeline.shoutu_symbol_index(us, shoutu_wide=wide, mode="percentile")
    fixed = pipeline.shoutu_symbol_index(us, shoutu_wide=wide, mode="fixed")
    pd.testing.assert_frame_equal(got, fixed)
    assert got.notna().all().all()


def test_default_mode_is_percentile():
    """**守卫**：默认口径必须是用户选定的 `percentile`（第 12.26 条 Q8）。"""
    assert config.SHOUTU_INDEX_MODE == "percentile"


def test_percentile_uses_rank_window_not_a_new_parameter():
    """**守卫**：分位数窗口必须复用 `RANK_WINDOW`，不得新造参数（第 4B.6 条）。

    判据用**量程小的标的 B**（±20）：它的固定阈值口径恒 ≤ 60，
    而分位数口径接近 100 ⇒ "从 60 跳到 100"就是分位数生效的标记。

    **注意**：不能用 `isna` 判断 —— 三级回退会把 NaN 填成固定阈值值，
    所以窗口不足时**不是** NaN，而是**固定阈值值**。这正是设计意图。
    """
    n = config.RANK_WINDOW
    wide = _long_wide(n=n)
    us = _us_like(wide.index)
    idx = pipeline.shoutu_symbol_index(us, shoutu_wide=wide, mode="percentile")
    assert idx["SOXL"].iloc[n - 2] < 61.0     # 第 n-1 天：窗口不足 ⇒ 固定阈值
    assert idx["SOXL"].iloc[n - 1] > 95.0     # 第 n 天：分位数生效

    short = _long_wide(n=n - 1)
    us2 = _us_like(short.index)
    idx2 = pipeline.shoutu_symbol_index(us2, shoutu_wide=short, mode="percentile")
    fixed2 = pipeline.shoutu_symbol_index(us2, shoutu_wide=short, mode="fixed")
    pd.testing.assert_frame_equal(idx2, fixed2)  # 全程回退固定阈值


def test_out_of_range_shoutu_value_raises():
    """守猪待兔越界必须报错（同 `loader.shoutu_to_system_scale` 的原则）。"""
    from fg_system.data.loader import DataQualityError
    us = _features()
    w = _weights()
    with pytest.raises(DataQualityError):
        pipeline.shoutu_symbol_index(us, shoutu_wide=_shoutu({"TQQQ": 101}))


def test_shoutu_market_index_is_weighted_mean_of_symbol_index():
    """`shoutu_market_index` = Σ_i w_i × shoutu_symbol_index_i。"""
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    us = pd.DataFrame({"fg_index": [50.0] * 5, "trend": [1.0] * 5}, index=idx)
    # 守猪待兔宽表：TQQQ 恒 +60，SOXL 恒 -60
    wide = pd.DataFrame({"TQQQ": [60.0] * 5, "SOXL": [-60.0] * 5}, index=idx)
    weights = pd.DataFrame({"TQQQ": [0.75] * 5, "SOXL": [0.25] * 5}, index=idx)
    out = pipeline.shoutu_market_index(
        us, weights, shoutu_wide=wide, symbols=["TQQQ", "SOXL"])
    # (60+100)/2 = 80，(-60+100)/2 = 20 ⇒ 0.75×80 + 0.25×20 = 65
    assert out.round(6).tolist() == [65.0] * 5


def test_shoutu_market_index_falls_back_to_fg_index_on_empty_history():
    """历史区间无守猪待兔数据 ⇒ 三级回退到 fg_index ⇒ 逐位等于 fg_index。"""
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    us = pd.DataFrame({"fg_index": [10.0, 30.0, 50.0, 70.0, 90.0],
                       "trend": [1.0] * 5}, index=idx)
    weights = pd.DataFrame({"TQQQ": [0.5] * 5, "SOXL": [0.5] * 5}, index=idx)
    out = pipeline.shoutu_market_index(
        us, weights, shoutu_wide=pd.DataFrame(), symbols=["TQQQ", "SOXL"])
    assert out.round(9).tolist() == us["fg_index"].round(9).tolist()


def test_shoutu_market_index_falls_back_for_uncovered_symbols_and_dates():
    """⚠️ 守卫：**部分覆盖**时未覆盖的标的/日期必须逐位回退 `fg_index`。

    这才是生产里的回退形态（宽表只覆盖部分标的/日期）。若这条失败 ⇒
    keyed extremes 在守猪待兔未覆盖区间会**改变行为**，与 spec §6 的
    「历史区间零影响」性质冲突。
    """
    idx = pd.date_range("2024-01-01", periods=6, freq="B")
    us = pd.DataFrame({"fg_index": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
                       "trend": [1.0] * 6}, index=idx)
    weights = pd.DataFrame({"TQQQ": [0.5] * 6, "SOXL": [0.5] * 6}, index=idx)
    # 只覆盖最后一天、且只有 TQQQ（SOXL 完全缺）
    wide = pd.DataFrame({"TQQQ": [float("nan")] * 5 + [60.0]}, index=idx)
    out = pipeline.shoutu_market_index(us, weights, shoutu_wide=wide,
                                       symbols=["TQQQ", "SOXL"])
    # 前 5 天：两列都回退到 fg_index ⇒ Σw=1 ⇒ 逐位等于 fg_index
    assert out.iloc[:5].round(9).tolist() == us["fg_index"].iloc[:5].round(9).tolist()
    # 第 6 天：TQQQ=(60+100)/2=80、SOXL 回退 fg_index=60 ⇒ 0.5×80 + 0.5×60 = 70
    assert abs(out.iloc[5] - 70.0) < 1e-9


def test_shoutu_market_index_returns_nan_row_when_weights_missing():
    """⚠️ 守卫：某行权重缺失（NaN）⇒ 该行返回 NaN，不得给出**部分和**。

    这正是 `min_count=len(symbols)` 存在的理由。若这条失败 ⇒ 权重缺失时
    会静默给出偏低的信号值。

    **注意**：缺失必须落在**开头**（无前值可填）。`weights` 走
    `.reindex(...).ffill()` ⇒ 中间/末尾的 NaN 会被**前值填充**（有意行为，
    对应停牌/周末）；只有开头无前值可填的 NaN 才会留下 ⇒ 触发本守卫。
    """
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    us = pd.DataFrame({"fg_index": [50.0] * 3, "trend": [1.0] * 3}, index=idx)
    weights = pd.DataFrame({"TQQQ": [float("nan"), 0.5, 0.5],
                            "SOXL": [float("nan"), 0.5, 0.5]}, index=idx)
    wide = pd.DataFrame({"TQQQ": [60.0] * 3, "SOXL": [-60.0] * 3}, index=idx)
    out = pipeline.shoutu_market_index(us, weights, shoutu_wide=wide,
                                       symbols=["TQQQ", "SOXL"])
    assert pd.isna(out.iloc[0])
    assert out.iloc[1] == pytest.approx(50.0)
    assert out.iloc[2] == pytest.approx(50.0)


def test_shoutu_market_index_does_not_renormalise_for_symbol_subset():
    """⚠️ 守卫：`symbols` 传子集时**不做归一化** ⇒ 结果 = 子集权重之和 × 子集指数。

    ⚠️ 这条锁定的是**已知陷阱**：此时 docstring 里「因 Σw = 1」的前提**不再成立**。
    若将来有人给函数加了归一化，这条会失败 —— 那时请先改 docstring 与 spec，别直接改断言。
    """
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    us = pd.DataFrame({"fg_index": [50.0] * 2, "trend": [1.0] * 2}, index=idx)
    weights = pd.DataFrame({"TQQQ": [0.25] * 2, "SOXL": [0.25] * 2,
                            "UPRO": [0.5] * 2}, index=idx)
    wide = pd.DataFrame({"TQQQ": [60.0] * 2, "SOXL": [-60.0] * 2}, index=idx)
    out = pipeline.shoutu_market_index(us, weights, shoutu_wide=wide,
                                       symbols=["TQQQ", "SOXL"])
    # (60+100)/2=80, (-60+100)/2=20 ⇒ 0.25×80 + 0.25×20 = 25（不归一化）
    assert out.round(6).tolist() == [25.0, 25.0]
