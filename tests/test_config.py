# -*- coding: utf-8 -*-
"""配置层测试：参数完整性与内部一致性。"""
import pytest

from fg_system import config


def test_weights_sum_to_one():
    assert sum(config.WEIGHTS.values()) == pytest.approx(1.0)


def test_zone_saturation_length_matches_edges():
    # 5 档 = 4 个边界
    assert len(config.ZONE_SATURATION) == len(config.ZONE_EDGES) + 1


def test_core_and_ammo_caps_within_total():
    """v2.4：核心仓 + 弹药仓 <= 100%，余额为**永久现金缓冲**。

    原断言为 == 1.0（v2 设计：满负荷运转）。v2.1 下调 CORE_CAP、v2.4 定 AMMO_CAP=20%，
    因此出现 35% 永久现金。这是「降低回撤」的主动选择，不是遗漏——
    若上调弹药仓以凑满 100%，大盘最大暴露反而会升高。
    见 docs/trading-discipline.md 第 4.1.1 条。
    """
    assert config.CORE_CAP + config.AMMO_CAP <= 1.0
    assert config.CORE_CAP + config.AMMO_CAP == pytest.approx(0.65)


def test_ammo_batches_descending():
    # 回撤触发点必须递增（20% < 40% < 60%）
    assert config.DRAWDOWN_BATCHES == sorted(config.DRAWDOWN_BATCHES)


def test_ammo_total_matches_cap():
    assert config.AMMO_PER_BATCH * len(config.DRAWDOWN_BATCHES) == pytest.approx(config.AMMO_CAP)


def test_underlying_map_covers_all_symbols():
    assert set(config.UNDERLYING_MAP.keys()) == set(config.SYMBOLS)


def test_leverage_ratio_covers_all_symbols():
    assert set(config.LEVERAGE_RATIO.keys()) == set(config.SYMBOLS)


def test_extreme_greed_thresholds_ordered():
    assert config.EXTREME_GREED_TRIGGER > config.EXTREME_GREED_UNLOCK_INDEX
    assert config.EXTREME_FEAR_TRIGGER < config.EXTREME_GREED_UNLOCK_INDEX


def test_sample_periods_not_overlapping():
    assert config.IS_END < config.OOS_START


# ---------------------------------------------------------------- v2 新增

def test_market_core_ratio_sums_to_one():
    """核心仓内部分割比例之和必须为 1。"""
    assert sum(config.MARKET_CORE_RATIO.values()) == pytest.approx(1.0)


def test_core_ratio_denominator_is_core_cap():
    """MARKET_CORE_RATIO 的分母是 CORE_CAP，不是总资金。

    v2.6 绝对值：大盘 36% + 加密 9% + 弹药 20% = 65%，其余 35% 为现金。
    """
    us = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    cr = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert us == pytest.approx(0.36)
    assert cr == pytest.approx(0.09)
    assert us + cr + config.AMMO_CAP == pytest.approx(0.65)


def test_crypto_layer_cap_descending():
    """加密三层上限必须递减：BTC 层 > 高 Beta 层 > 经营 Beta 层。"""
    caps = config.CRYPTO_LAYER_CAP
    assert caps["btc_beta"] > caps["stock_high_beta"] > caps["stock_ops_beta"]


def test_crypto_layer_cap_covers_all_layers():
    """CRYPTO_SYMBOLS 的每个层名都必须在 CRYPTO_LAYER_CAP 中有定义。"""
    assert set(config.CRYPTO_SYMBOLS.keys()) == set(config.CRYPTO_LAYER_CAP.keys())


def test_crypto_underlying_covers_all_crypto_symbols():
    """每个加密标的都必须有底层映射（合成与偏离检测依赖它）。"""
    flat = [s for group in config.CRYPTO_SYMBOLS.values() for s in group]
    assert set(config.CRYPTO_UNDERLYING.keys()) == set(flat)
    assert set(config.CRYPTO_LEVERAGE.keys()) == set(flat)


def test_crypto_drawdown_batches_wider_than_equity():
    """加密档位必须比大盘宽（§6.4：加密 -20% 是常态，会抽干共享池）。"""
    assert min(config.CRYPTO_DRAWDOWN_BATCHES) > min(config.DRAWDOWN_BATCHES)


def test_crypto_greed_tiers_ascending_and_matched():
    """极贪分批档位递增，且与减仓比例一一对应。"""
    assert config.CRYPTO_GREED_TIERS == sorted(config.CRYPTO_GREED_TIERS)
    assert len(config.CRYPTO_GREED_TIERS) == len(config.CRYPTO_GREED_REDUCE)


def test_crypto_greed_reduce_descending():
    """减仓后的核心仓比例必须递减（越贪越少）。"""
    r = config.CRYPTO_GREED_REDUCE
    assert all(r[i] > r[i + 1] for i in range(len(r) - 1))


def test_trend_filter_factor_between_zero_and_one():
    assert 0.0 < config.TREND_FILTER_FACTOR < 1.0


def test_trend_benchmark_covers_all_markets():
    assert set(config.TREND_BENCHMARK.keys()) == set(config.MARKETS)


def test_crypto_weights_sum_to_one():
    assert sum(config.CRYPTO_WEIGHTS.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------- v2.1 新增（回撤预算）

def test_equity_max_exposure_within_drawdown_budget():
    """大盘最大暴露 × **最坏**「回撤/暴露」比值 必须 <= -40% 预算。

    依据（docs/trading-discipline.md 第 12.7 条的**组合级 30 格矩阵**）：
      实测「组合回撤 / 大盘最大暴露」比值落在 **0.63 ~ 0.74**（均值 0.68）。
      取**最坏**比值 0.74 作护栏：
        最大暴露 × 0.74 <= 0.40  ⇒  最大暴露 <= **54.1%**
      当前 45% × 70% + 20% = **51.5%**  ⇒  0.515 × 0.74 = 38.1% <= 40%  ✅

    **为什么不用更早的「× 0.90（假设最大暴露贯穿 -90% 崩盘）」**：
    那个上界假设该极端情形**贯穿整个崩盘**，历史上从未发生，导致过度保守——
    曾据此推出 `AMMO_CAP <= 12%`，而矩阵显示 20% 即可。见第 12.6 / 12.7 条。

    **v2.6 起，大盘只能拿到「自己份额」的弹药**（`market_batch_cap()` 批，第 12.11 条），
    **不是整份共享池**——共享池先到先得，实测加密拿 2 批、大盘拿 1 批。

    本测试是**回撤约束的可执行化身**：把 CORE_CAP / AMMO_CAP 或市场比例调高即失败。
    """
    from fg_system.signal import portfolio as pf

    budget = 0.40
    worst_ratio = 0.74
    share = pf.market_batch_cap() / len(config.DRAWDOWN_BATCHES)
    max_exposure = (config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
                    + config.AMMO_CAP * share)
    assert max_exposure == pytest.approx(0.36 + 0.20 * 2 / 3)
    assert max_exposure * worst_ratio <= budget


def test_crypto_layer_caps_force_diversification():
    """BTC 层上限必须 < 1.0，强制把一部分加密核心仓分散到 BTC 层之外。

    依据：真实轨实测 MSTX 最大回撤 **-99.61%**（接近净值归零）。
    若 btc_beta == 1.0，加密核心仓可全部压在单一层，**单一标的归零即吞噬整个加密仓**。
    """
    assert config.CRYPTO_LAYER_CAP["btc_beta"] < 1.0
    assert config.CRYPTO_LAYER_CAP["btc_beta"] == pytest.approx(0.80)


def test_crypto_layer_caps_shrink_vs_v2():
    """v2.1 三层上限必须比 v2 原值更保守（不得被调回）。"""
    assert config.CRYPTO_LAYER_CAP["btc_beta"] <= 0.80
    assert config.CRYPTO_LAYER_CAP["stock_high_beta"] <= 0.50
    assert config.CRYPTO_LAYER_CAP["stock_ops_beta"] <= 0.30


def test_ammo_cap_below_v2():
    """弹药池上限必须低于 v2 原值 30%（v2.4 定为 **20%**）。

    依据（第 12.7 条矩阵）：弹药池是**永久仓位**（实测 2018-11-16 后恒定占比 7.8 年）
    且**不受趋势过滤保护**，崩盘中吃满跌幅。组合级实测：
      30% ⇒ 组合回撤 **-42.52%**（击穿 -40%）
      20% ⇒ 组合回撤 **-35.09%**（余量 4.91pp）✅
    """
    assert config.AMMO_CAP < 0.30
    assert config.AMMO_CAP == pytest.approx(0.20)


def test_ammo_per_batch_consistent_with_cap():
    """每批释放额必须由池子上限**派生**（三批加总 = AMMO_CAP）。"""
    assert config.AMMO_PER_BATCH == pytest.approx(0.20 / 3)
    assert config.AMMO_PER_BATCH * len(config.DRAWDOWN_BATCHES) == \
        pytest.approx(config.AMMO_CAP)


def test_weighting_is_inv_vol():
    """v2.3：`us_equity` 内必须用反比波动率权重（§4C.1），不是等权。"""
    assert config.WEIGHTING == "inv_vol"


def test_vol_weight_window_is_a_priori():
    """波动率窗口必须与 `DRAWDOWN_LOOKBACK` 一致（先验值，不得优化，§4C.5）。"""
    assert config.VOL_WEIGHT_WINDOW == 252
    assert config.VOL_WEIGHT_WINDOW == config.DRAWDOWN_LOOKBACK


def test_trend_benchmark_not_changed_by_v2_2():
    """v2.2 取证结论：趋势基准与均线周期**维持不变**。

    2026-06 崩盘中 SOXX 相对自身 200 日均线从 1.658 只跌到 1.161，**全程未跌破**，
    故「按标的基准」不会触发；换 ≤50MA 会劣化 2022 熊市覆盖（86.5% → 70.1%）。
    见 docs/trading-discipline.md 第 12.3 条——本测试防止有人「顺手」把它改掉。
    """
    assert config.TREND_MA_DAYS == 200
    assert config.TREND_FILTER_FACTOR == 0.5
    assert config.TREND_BENCHMARK == {"us_equity": "QQQ", "crypto": "BTC"}
