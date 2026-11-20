# -*- coding: utf-8 -*-
"""因子加权合成 fg_index（§5.4）。

🔴 **系统定位：波动率主导的逆向情绪指数**（2026-11-20 定案，第 12.56 条）

    这**不是**「六因子均衡配置」✗ —— 波动率族（`vix` .270 + `term` .135）
    占 **40.5%**，是收益的主要来源 ✓

    实测证据（同窗口 A/B + 候选评估）：
      · vol 权重 40.5% → 35% → 30% ⇒ OOS 年化 **17.22% → 13.90% → 11.81%**
        （近似线性下降，回撤无改善）✗
      · 候选替换因子（信用利差 0.47 / ERP 0.47）与 `vix` 的相关性
        **比 `term` 的 0.43 更强**，且单因子 IC 更弱（−0.18 / +0.09 vs −0.32）✗
    ⇒ 40.5% **不是配置缺陷，是本质** ✓ 预期应与机制一致 ✓

    ⚠️ 它回答「情绪在过去三年排第几」，**不回答**「绝对风险多大」✗
       —— 后者看 `absolute_index()`（固定阈值口径，输出 `fg_index_abs`）✓

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
    from fg_system.factors.putcall import PutCallFactor
    from fg_system.factors.term import TermStructureFactor
    from fg_system.factors.vix import VixFactor

    return [VixFactor(), TermStructureFactor(), PriceFactor(), BreadthFactor(),
            FedPolicyFactor(), PutCallFactor()]


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


# ---------------------------------------------------------------- R1.3 分因子独立报告
ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


def absolute_index(wide):
    """**绝对水平**指数（0-100，高分 = 贪婪）—— 不过滚动分位 ✓。

    🔴 为什么需要它（2026-11-20 评审）✗：
       `combine()` 的六个因子**全部**走 756 日滚动百分位 ⇒ `fg_index` 在
       结构上**恒为均匀分布** ✗ ⇒ 它只能回答「相对过去三年排第几」✗，
       回答不了「绝对水平高不高」✗
       （VIX 若连续三年 40，分位会自动漂回 50 ⇒ 主指数认为「平静」✗）

    这里用**固定阈值**直接映射原始值（不做任何滚动归一化）：

      · `vix`     10 → 100（极安静） / 40 → 0（极恐慌）
      · `term`    VIX/VIX3M 0.8 → 100 / 1.3 → 0（倒挂 = 恐慌）
      · `breadth` MA200 上方比例，原生 0~1 → 0~100（**本就是绝对量**）

    三个子项**等权**，缺项按剩余项归一（`DataFrame.mean` 天然跳过 NaN）✓

    ⚠️ 阈值是**判断取值**，不是优化结果 —— 改阈值等于改口径，须同步
       `docs/factor-weights-decision.md` 并重跑回测 ✓
    """
    parts = {}
    cols = wide.columns
    if ("VIX", "close") in cols:
        vix = wide[("VIX", "close")].astype(float)
        parts["vix"] = ((40.0 - vix) / 30.0 * 100.0).clip(0.0, 100.0)
        if ("VIX3M", "close") in cols:
            ratio = (vix / wide[("VIX3M", "close")].astype(float)
                     ).rolling(5).mean()
            parts["term"] = ((1.3 - ratio) / 0.5 * 100.0).clip(0.0, 100.0)
    syms = list(config.BREADTH_SYMBOLS)
    if syms and all((s, "close") in cols for s in syms):
        above = None
        for s in syms:
            px = wide[(s, "close")].astype(float)
            ma = px.rolling(200, min_periods=200).mean()
            flag = (px > ma).astype(float).where(ma.notna())
            above = flag if above is None else above + flag
        parts["breadth"] = (above / len(syms) * 100.0).clip(0.0, 100.0)
    if not parts:
        return pd.Series(np.nan, index=wide.index)
    return pd.DataFrame(parts).mean(axis=1).clip(0.0, 100.0)


def factor_zone(score):
    """单因子 0-100 分 → 档位（0 极恐 / 1 恐 / 2 中性 / 3 贪 / 4 极贪）。

    边界 = config.ZONE_EDGES = [20, 40, 60, 80]（`>=` 判定，与 pipeline/market_signal 同口径）。
    NaN → None。
    """
    if score is None or (isinstance(score, float) and score != score):
        return None
    for i, edge in enumerate(config.ZONE_EDGES):
        if score < edge:
            return i
    return len(config.ZONE_EDGES)


def factor_score_summary(row, factors=None):
    """单日因子独立报告：六因子 分 + 档位 + 方向（>50 贪婪向 / <50 恐惧向）+ 权重。

    输入：features.csv 一行（含 vix/term/price/breadth/fed/putcall）。
    输出：dict {因子名: {score, zone, zone_name, direction, weight}}。
    """
    factors = factors or ["vix", "term", "price", "breadth", "fed", "putcall"]
    out = {}
    weights = config.WEIGHTS
    for k in factors:
        v = row.get(k)
        val = float(v) if v is not None and v == v else None
        z = factor_zone(val)
        out[k] = {
            "score": None if val is None else round(val, 2),
            "zone": z,
            "zone_name": ZONE_NAMES[z] if z is not None else "—",
            "direction": ("贪婪向" if val is not None and val > 50
                          else ("恐惧向" if val is not None and val < 50
                                else ("中性" if val is not None else "—"))),
            "weight": float(weights[k]),
        }
    return out
