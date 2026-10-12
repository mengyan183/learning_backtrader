# -*- coding: utf-8 -*-
"""参数合法性校验（`config.validate()`）的**非法参数**用例。

设计动机：`tests/test_config.py` 只断言「当前值等于多少」——它证明的是**数值没被改**，
不是「改坏了会被拦住」。本文件用 `monkeypatch.setattr` **临时**改坏某个参数再调
`validate()`，断言**必须抛 ValueError 且报错含字段名**，从而把「错误参数静默运行」
变成「错误参数在入口处就崩」。

约束：**只 monkeypatch，绝不改真实 config 文件**；测试后 monkeypatch 自动还原。
"""
import pytest

from fg_system import config


# ---------------------------------------------------------------- 合法配置

def test_current_config_is_valid():
    """当前生产配置必须一次通过校验（若有失败，说明配置本身不合法，须上报）。"""
    assert config.validate() is None  # 不抛异常即为通过


# ---------------------------------------------------------------- 非法：权重

def test_weights_not_normalized_rejected(monkeypatch):
    """权重之和 != 1 必须被拒（含字段名 WEIGHTS）。"""
    bad = dict(config.WEIGHTS)
    bad["vix"] = 0.90  # 六因子版和变成 1.63（旧五因子版为 1.60）
    monkeypatch.setattr(config, "WEIGHTS", bad)
    expected_sum = sum(bad.values())
    with pytest.raises(ValueError) as ei:
        config.validate()
    msg = str(ei.value)
    assert "WEIGHTS" in msg
    # 报错须带实际值：解析报文里的数字，确认 ≈ 实际和（浮点表示允许尾数）
    import re
    nums = [float(x) for x in re.findall(r"\d+\.\d+", msg)]
    assert any(abs(n - expected_sum) < 1e-3 for n in nums), msg


def test_weight_negative_rejected(monkeypatch):
    """单个权重为负必须被拒。"""
    bad = dict(config.WEIGHTS)
    bad["term"] = -0.15
    bad["fed"] = 0.45  # 保持和为 1，隔离「非负」这一条
    monkeypatch.setattr(config, "WEIGHTS", bad)
    with pytest.raises(ValueError) as ei:
        config.validate()
    msg = str(ei.value)
    assert "WEIGHTS" in msg
    assert "term" in msg


# ---------------------------------------------------------------- 非法：档位边界

def test_zone_edges_not_increasing_rejected(monkeypatch):
    """ZONE_EDGES 非严格递增必须被拒（含字段名与实际值）。"""
    monkeypatch.setattr(config, "ZONE_EDGES", [20, 60, 40, 80])
    with pytest.raises(ValueError) as ei:
        config.validate()
    msg = str(ei.value)
    assert "ZONE_EDGES" in msg


def test_zone_edges_out_of_range_rejected(monkeypatch):
    """ZONE_EDGES 必须落在 0-100（索引刻度）。越界必须被拒。"""
    monkeypatch.setattr(config, "ZONE_EDGES", [20, 40, 60, 120])
    with pytest.raises(ValueError) as ei:
        config.validate()
    msg = str(ei.value)
    assert "ZONE_EDGES" in msg
    assert "120" in msg


# ---------------------------------------------------------------- 非法：饱和度 / 折扣系数

def test_zone_saturation_out_of_range_rejected(monkeypatch):
    """ZONE_SATURATION 是核心仓比例，必须在 0-1。"""
    monkeypatch.setattr(config, "ZONE_SATURATION", [1.00, 0.75, 0.50, 0.25, 1.50])
    with pytest.raises(ValueError) as ei:
        config.validate()
    msg = str(ei.value)
    assert "ZONE_SATURATION" in msg
    assert "1.5" in msg


def test_zone_saturation_length_mismatch_rejected(monkeypatch):
    """ZONE_SATURATION 长度必须 = len(ZONE_EDGES)+1（5 档 = 4 边界）。"""
    monkeypatch.setattr(config, "ZONE_SATURATION", [1.00, 0.50, 0.00])
    with pytest.raises(ValueError) as ei:
        config.validate()
    msg = str(ei.value)
    assert "ZONE_SATURATION" in msg


def test_trend_filter_factor_out_of_range_rejected(monkeypatch):
    """趋势折扣系数必须在 0-1。"""
    monkeypatch.setattr(config, "TREND_FILTER_FACTOR", 1.50)
    with pytest.raises(ValueError) as ei:
        config.validate()
    assert "TREND_FILTER_FACTOR" in str(ei.value)


# ---------------------------------------------------------------- 非法：仓位上限 / 佣金

def test_core_plus_ammo_over_total_rejected(monkeypatch):
    """核心仓 + 弹药仓 > 100% 必须被拒（含两个字段名）。"""
    monkeypatch.setattr(config, "CORE_CAP", 0.90)
    monkeypatch.setattr(config, "AMMO_CAP", 0.60)
    with pytest.raises(ValueError) as ei:
        config.validate()
    msg = str(ei.value)
    assert "CORE_CAP" in msg and "AMMO_CAP" in msg


def test_commission_positive_rejected(monkeypatch):
    """佣金必须为正（0 会让回测低估成本，静默偏乐观）。"""
    monkeypatch.setattr(config, "COMMISSION", 0.0)
    with pytest.raises(ValueError) as ei:
        config.validate()
    msg = str(ei.value)
    assert "COMMISSION" in msg
    assert "0" in msg


# ---------------------------------------------------------------- 非法：估值门 / 市场比例

def test_market_core_ratio_not_normalized_rejected(monkeypatch):
    """MARKET_CORE_RATIO 之和 != 1 必须被拒。"""
    monkeypatch.setattr(config, "MARKET_CORE_RATIO",
                        {"us_equity": 0.80, "crypto": 0.50})
    with pytest.raises(ValueError) as ei:
        config.validate()
    assert "MARKET_CORE_RATIO" in str(ei.value)


def test_crypto_weights_not_normalized_rejected(monkeypatch):
    """CRYPTO_WEIGHTS 之和 != 1 必须被拒。"""
    monkeypatch.setattr(config, "CRYPTO_WEIGHTS",
                        {"crypto_fng": 0.50, "crypto_price": 0.70})
    with pytest.raises(ValueError) as ei:
        config.validate()
    assert "CRYPTO_WEIGHTS" in str(ei.value)


# ---------------------------------------------------------------- 非法：档位（弹药）与贪婪分档

def test_drawdown_batches_not_increasing_rejected(monkeypatch):
    """DRAWDOWN_BATCHES 必须严格递增（触发点）。"""
    monkeypatch.setattr(config, "DRAWDOWN_BATCHES", [0.40, 0.20, 0.60])
    with pytest.raises(ValueError) as ei:
        config.validate()
    assert "DRAWDOWN_BATCHES" in str(ei.value)


def test_crypto_greed_reduce_mismatch_rejected(monkeypatch):
    """CRYPTO_GREED_REDUCE 长度必须与 CRYPTO_GREED_TIERS 一致。"""
    monkeypatch.setattr(config, "CRYPTO_GREED_REDUCE", [0.5, 0.0])
    with pytest.raises(ValueError) as ei:
        config.validate()
    assert "CRYPTO_GREED_REDUCE" in str(ei.value)


# ---------------------------------------------------------------- 非法：阈值 / 窗口正数

def test_split_deviation_threshold_out_of_range_rejected(monkeypatch):
    """拆股偏离阈值是比例，必须在 (0, 1)。"""
    monkeypatch.setattr(config, "SPLIT_DEVIATION_THRESHOLD", 1.20)
    with pytest.raises(ValueError) as ei:
        config.validate()
    assert "SPLIT_DEVIATION_THRESHOLD" in str(ei.value)


def test_rank_window_non_positive_rejected(monkeypatch):
    """滚动窗口必须为正整数。"""
    monkeypatch.setattr(config, "RANK_WINDOW", 0)
    with pytest.raises(ValueError) as ei:
        config.validate()
    assert "RANK_WINDOW" in str(ei.value)


def test_extreme_triggers_out_of_range_rejected(monkeypatch):
    """极贪触发线必须在 0-100。"""
    monkeypatch.setattr(config, "EXTREME_GREED_TRIGGER", 150)
    with pytest.raises(ValueError) as ei:
        config.validate()
    assert "EXTREME_GREED_TRIGGER" in str(ei.value)
