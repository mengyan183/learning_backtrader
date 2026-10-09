# -*- coding: utf-8 -*-
"""进化变体：adopted 假说 → 回测变体的**先验定义**（C-1）。

设计：docs/evolution-plan.md 第 ⑤ 步「变体验证」——
  新增变体 = 一个 VARIANTS 条目 + 一条等价性守卫测试；
  **先验推导，不是从回测里搜出来的**（第 8 条 / 第 13.1 条）；
  生产代码零改动（本模块只替换 features 的 target_position 列）。

**本模块只做纯计算**：不读文件、不做 I/O。编排在 scripts/evolve_variant.py。

## 变体机制
回测入口 `runner.run_single(features, symbol)` 消费 features 的
`target_position` 列（FgStrategy 唯一实现 `portfolio.next_position`）。
⇒ 变体 = 对 `target_position` 做**先验变换**后喂同一回测。

## B0 基准
`apply_variant(features, ..., "B0")` 原样返回 ⇒ 输出必须与 baseline.json
逐位一致（等价性守卫红线：默认参数逐位相同）。

## V-H7（adopted 假说 H-007 的规则化）
H-007（2026-10-08 adopted）：trend_blocked_us=True（趋势过滤阻断）组
最大回撤 -37.37% **大于**未阻断组 -34.24%（1760 日样本）。
先验规则化（非调参，固定折扣声明先验）：**阻断日 target_position × 0.5**
（阻断意味着模型认为趋势不支持，实证其回撤更大 ⇒ 更保守）。

## V-ATR（阶段 2 ①：ATR 移动止损参数化）
先验：**ATR 止损是经典风险管理手段**，与"回撤控制"目标一致；规则化为
**20 日滚动高点回撤 ≥ k×ATR(14) → 当日 target_position 归零**（移动止损）。
k 为参数（默认 2.0，网格 1.5/2.0/2.5 走阶段 2 变体，不直接改生产参数）。
要求 features 含 high/low/close 列（evolve_variant 已 join 价格列）；
缺价格列（守卫测试纯 features 场景）时返回原样（保守，不加新规则）。

## V-VOL（阶段 2 ②：波动率目标仓位 vol targeting）
先验：**波动率目标（vol targeting）是经典仓位管理手段**——把目标仓位缩放为
**min(1.0, vol_target / 滚动年化波动率)**：波动率高于目标 → 自动降仓，
波动率低于目标 → 回到原始目标仓位（封顶 1.0，不放大风险）。
vol_target 为参数（默认 0.25 年化，网格 0.20/0.25/0.30 走阶段 2 变体）。
要求 features 含 close 列（evolve_variant 已 join 价格列）；
缺价格列时返回原样（保守，不加新规则）。

## V-CORR（阶段 2 ③：杠杆ETF 相关性风险预算——有效敞口代理）
先验：**危机中杠杆 ETF 相关性趋 1（分散失效）是实证规律**；VIX 高分位
= 市场压力状态 = 杠杆簇同跌风险高企。规则化为：**VIX 滚动 1 年 80 分位以上
→ target_position × factor（默认 0.5）**——以市场波动状态代理相关性状态，
在"分散失效"窗口主动收缩有效敞口（防 YINN/GDXU 同跌）。
要求 features 含 vix 列；缺 vix 时返回原样（保守，不加新规则）。

## V-MA（阶段 2 ④：动能/均线过滤）
先验：**均线过滤防"贪婪档追高"**：价格在 MA 下方 = 中期趋势不支撑
→ 降仓；上方维持。规则化为：**close < MA(N)（默认 N=50）→ target × factor
（默认 0.5）**。要求 features 含 close 列；缺时返回原样。
"""
import numpy as np
import pandas as pd

BASELINE = "B0"
VARIANTS = {
    "V-H7": {
        "label": "趋势阻断日仓位 ×0.5（H-007 实证→先验保守）",
        "factor": 0.5,
        "basis": "H-007 adopted：阻断组回撤 -37.37% > 未阻断 -34.24%",
    },
    "V-ATR": {
        "label": "ATR 移动止损（20日高点回撤 k×ATR(14) 清仓）",
        "k": 2.0,
        "basis": "阶段 2 ①：经典风险管理手段参数化，先验非调参",
        "archived": True,   # 2026-10-09 walk-forward 20/40 窗 ⇒ 建议归档（防御降仓 OOS 不划算）
    },
    "V-VOL": {
        "label": "波动率目标仓位（vol_target/20日滚动年化波动率，封顶1.0）",
        "vol_target": 0.25,
        "basis": "阶段 2 ②：经典仓位管理手段参数化，先验非调参",
        "archived": True,   # 2026-10-09 walk-forward 22/40 窗 ⇒ 建议归档（防御降仓 OOS 不划算）
    },
    "V-CORR": {
        "label": "相关性风险预算（VIX 滚动1年80分位以上 → 仓位×0.5）",
        "factor": 0.5,
        "vix_lookback": 252,
        "vix_q": 0.80,
        "basis": "阶段 2 ③：危机中杠杆ETF相关性趋1（分散失效）实证，先验非调参",
    },
    "V-MA": {
        "label": "动能/均线过滤（close < MA50 → 仓位×0.5）",
        "factor": 0.5,
        "ma_period": 50,
        "basis": "阶段 2 ④：均线过滤防贪婪档追高，先验非调参",
    },
}
VARIANT_KEYS = (BASELINE,) + tuple(VARIANTS)


def _atr(high, low, close, period=14):
    """Wilder ATR(14)。返回与输入等长的 ATR 序列（前 period-1 日为 NaN）。"""
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()],
                   axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return atr


def _vol_target_scale(close, vol_target, period=20):
    """波动率目标缩放因子：min(1.0, vol_target / 滚动年化波动率)。

    年化波动率 = 滚动 period 日对数收益 std × sqrt(252)。
    前 period 日（NaN）按 1.0 处理（不动原始仓位，保守）。
    """
    ret = np.log(close / close.shift(1))
    vol = ret.rolling(period, min_periods=period).std() * np.sqrt(252.0)
    scale = (vol_target / vol).clip(upper=1.0)
    return scale.fillna(1.0)


def apply_variant(features, portfolio_features, variant):
    """返回**变换后**的 features 副本（只动 target_position 列）。

    - features：Data/features.csv（生产同款，含 target_position）
    - portfolio_features：Data/portfolio_features.csv（含 trend_blocked_us）
    - variant：B0（原样）、V-H7（阻断日 ×0.5）、V-ATR（ATR 移动止损）
      或 V-VOL（波动率目标仓位）

    对齐：portfolio_features 与 features 按 date 内连接；阻断标记缺失的
    交易日（如 warmup 段）按未阻断处理（不新增规则，保守）。
    """
    if variant not in VARIANT_KEYS:
        raise KeyError("未知变体 %r；可选：%s" % (variant, tuple(VARIANT_KEYS)))
    out = features.copy()
    if variant == BASELINE:
        return out

    spec = VARIANTS[variant]

    if variant == "V-H7":
        pf = portfolio_features.copy()
        if "date" in pf.columns:
            pf = pf.set_index("date")
        common = out.index.intersection(pf.index)
        blocked = pf.loc[common, "trend_blocked_us"].fillna(False).astype(bool)
        mask = out.index.isin(common[blocked.values])
        # 仅阻断日降仓；阻断列缺失日不动（保守，不加新规则）
        out.loc[mask, "target_position"] = (
            out.loc[mask, "target_position"] * spec["factor"])
        return out

    if variant == "V-ATR":
        # 缺价格列（守卫测试纯 features 场景）：返回原样，保守不加规则
        need = {"high", "low", "close"}
        if not need.issubset(out.columns):
            return out
        high, low, close = out["high"], out["low"], out["close"]
        atr = _atr(high, low, close, period=14)
        # 20 日滚动高点
        roll_high = high.rolling(20, min_periods=20).max()
        # 触发：收盘价跌破 滚动高点 - k×ATR
        stop_dist = spec["k"] * atr
        triggered = (close < roll_high - stop_dist).fillna(False)
        out.loc[triggered, "target_position"] = 0.0
        return out

    if variant == "V-VOL":
        # 缺价格列：返回原样，保守不加规则
        if "close" not in out.columns:
            return out
        scale = _vol_target_scale(out["close"], spec["vol_target"])
        out["target_position"] = (out["target_position"] * scale).clip(lower=0.0)
        return out

    if variant == "V-CORR":
        # 缺 vix 列（守卫测试纯 features 场景）：返回原样，保守不加规则
        if "vix" not in out.columns:
            return out
        vix = out["vix"]
        # VIX 滚动 1 年（252 日）80 分位；min_periods=60（早期窗口保守放宽，
        # 真实数据 2500+ 行仍以 252 日为完整窗口）；NaN 按未触发处理（保守）
        q = vix.rolling(spec["vix_lookback"], min_periods=60).quantile(
            spec["vix_q"])
        stress = (vix > q).fillna(False)
        out.loc[stress, "target_position"] = (
            out.loc[stress, "target_position"] * spec["factor"])
        return out

    if variant == "V-MA":
        # 缺 close 列：返回原样，保守不加规则
        if "close" not in out.columns:
            return out
        ma = out["close"].rolling(spec["ma_period"], min_periods=spec["ma_period"]).mean()
        below = (out["close"] < ma).fillna(False)
        out.loc[below, "target_position"] = (
            out.loc[below, "target_position"] * spec["factor"])
        return out

    raise KeyError("未知变体 %r；可选：%s" % (variant, tuple(VARIANT_KEYS)))

