# -*- coding: utf-8 -*-
"""因子加权合成 fg_index（§5.4）。

    fg_index = Σ(wᵢ × scoreᵢ) / Σwᵢ      —— 仅对当日**有效**的因子求和

- 任一因子当日为 NaN 时，从分子分母中同时剔除，按剩余有效权重重新归一化。
- 有效因子数 < MIN_VALID_FACTORS 时返回 NaN（避免单因子主导）。
- 禁止使用任何全样本统计量（如全期均值/标准差）做归一化。

关于「是否需要二次归一化」：4 个因子的 score 各自近似均匀分布时，加权平均后的
fg_index 标准差约为 100×0.289×sqrt(Σwᵢ²) ≈ 14.7，落在 [0,20] 与 [80,100] 的概率
各约 2%（10 年约各 50 天）——极端档位稀有但确实会发生，因此**不做二次拉伸**，
warmup 只需 756 交易日。
"""
import numpy as np
import pandas as pd

from fg_system import config


def build_factors(market="us_equity"):
    """按市场构造因子实例。

    market="us_equity" → v1 四因子（保持 v1 的无参调用兼容）
    market="crypto"    → CF1 贪恐 + CF2 BTC 价格
    """
    return build_factors_for(market)


def build_factors_for(market):
    """按市场构造因子实例（显式版本，供 v2 调用）。"""
    if market == "crypto":
        from fg_system.factors.crypto_fng import CryptoFngFactor
        from fg_system.factors.crypto_price import CryptoPriceFactor

        return [CryptoFngFactor(), CryptoPriceFactor()]

    from fg_system.factors.breadth import BreadthFactor
    from fg_system.factors.fed import FedPolicyFactor
    from fg_system.factors.price import PriceFactor
    from fg_system.factors.term import TermStructureFactor
    from fg_system.factors.vix import VixFactor

    return [VixFactor(), TermStructureFactor(), PriceFactor(), BreadthFactor(),
            FedPolicyFactor()]


def weights_for(market):
    """该市场的因子权重表。"""
    if market == "crypto":
        return config.CRYPTO_WEIGHTS
    return config.WEIGHTS


def factor_scores(wide, factors=None, market="us_equity"):
    """各因子 0-100 分数矩阵（列 = 因子名）。"""
    factors = factors or build_factors_for(market)
    return pd.DataFrame({f.name: f.score(wide) for f in factors})


def combine(scores, factors=None, market="us_equity", min_valid=None):
    """加权合成指数，缺失因子按剩余权重重新归一化（§5.4）。

    v1 调用方式 `combine(scores, factors=build_factors())` 行为完全不变
    （market 默认 us_equity）。
    """
    if factors is None:
        factors = [type("F", (), {"name": c})() for c in scores.columns]
    weight_table = weights_for(market)
    weight = pd.Series({f.name: weight_table[f.name] for f in factors}, dtype=float)

    min_valid = config.MIN_VALID_FACTORS if min_valid is None else min_valid

    valid = scores.notna()
    weights = valid.mul(weight, axis=1)
    weight_sum = weights.sum(axis=1)

    weighted = (scores.fillna(0.0) * weights).sum(axis=1)
    out = weighted / weight_sum.replace(0.0, np.nan)

    too_few = valid.sum(axis=1) < min_valid
    out[too_few] = np.nan
    return out.clip(lower=0.0, upper=100.0)


def build_index(scores, market="us_equity", min_valid=None):
    """市场感知的统一入口：加权合成 + 平滑。"""
    return smooth(combine(scores, market=market, min_valid=min_valid))


def smooth(fg_index, days=None):
    """可选平滑（v1 默认 SMOOTHING_DAYS = 1，即不平滑，避免引入滞后削弱极端规则时效性）。"""
    days = days or config.SMOOTHING_DAYS
    if days <= 1:
        return fg_index
    return fg_index.rolling(days, min_periods=days).mean()
