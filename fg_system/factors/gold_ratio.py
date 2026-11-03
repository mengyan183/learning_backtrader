#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F-021 黄金相对强度（`GDX / GLD`）✓（2026-11-03 用户裁定要做）。

【为什么做这个而不是「全球央行购金」】

用户原提议：追踪**全球央行购买黄金**作为因子 ✗
评估后**不建议** ✗ 三条硬伤：
  ① **频率错配** ✗ —— WGC/IMF 的央行购金是**季度/年度**数据 ✗
     而系统评测是日频 5/10/20/40 ✗ 一个季度 1 个观测 ⇒ 攒 60 个要 15 年 ✗
  ② **发布滞后 2-3 个月** ✗ —— Q3 数据 12 月才出 ✗ 不可能用于当日决策 ✗
  ③ **传导链太长** ✗ —— 央行购金 → 金价 → 金矿股 → GDXU（3 倍）
     中间受**开采成本、股市 beta** 干扰 ✗（2021-2022 就是金价横盘、金矿股大跌 ✗）
⇒ 改用**日频、数据现成、与持仓直接相关**的替代：`GDX / GLD` ✓

【定义】

    ratio = GDX（金矿股 ETF）/ GLD（黄金 ETF）
    sig   = ratio 的 N 日滚动分位 ∈ [0,1]

  经济含义：
    ratio 高 ⇒ 金矿股**跑赢**金价 ⇒ 要么成本改善、要么市场给成长溢价
    ratio 低 ⇒ 金矿股**跑输**金价 ⇒ 成本压力 / 市场不信金价能持续

【方向】**待测** ✗ —— 两种理论相反，必须用数据定：
    - 动量说：跑赢会继续跑赢（经营杠杆正反馈）⇒ **正向**
    - 回归说：跑赢是透支（成本终会上升）⇒ **逆向**

  ⚠️ 所以本模块**只算信号，不预设方向** ✗
     方向由 `scripts/eval_gold_ratio.py` 的实测 IC 符号决定 ✓

【与持仓的关系】
  用户持有 `GDXU`（3 倍金矿股）✓ ⇒ 本因子**直接相关** ✓
  且 GDX/GLD 有 2524 天（2016-09 起）✓ 而 GDXU 只有 1469 天（2020-12 起）✗
  ⇒ 本因子**样本更长** ✓ 可以给 GDXU 提供更早的信号 ✓
"""
from fg_system.factors import ene as _ene

#: 滚动分位窗（约半年）✓ —— 相对强度是慢变量，120 日足够平滑 ✓
GOLD_RATIO_WINDOW = 120


def gold_ratio(prices_df, window=GOLD_RATIO_WINDOW):
    """`GDX / GLD` 的原始比值序列 ✓（对齐两个标的的交易日）。"""
    import pandas as pd

    gdx = _ene.close_series(prices_df, "GDX")
    gld = _ene.close_series(prices_df, "GLD")
    j = pd.concat([gdx.rename("gdx"), gld.rename("gld")], axis=1).dropna()
    if j.empty:
        return pd.Series(dtype=float)
    return (j["gdx"] / j["gld"]).rename("gold_ratio")


def gold_ratio_pct(prices_df, window=GOLD_RATIO_WINDOW):
    """比值在滚动窗内的**分位** ∈ [0,1] ✓（1 = 金矿股相对最强）。

    ⚠️ **不给方向** ✗ —— 返回的是「强度」，正负由调用方按实测 IC 决定 ✓
    """
    r = gold_ratio(prices_df)
    if r.empty:
        return r
    return r.rolling(window, min_periods=window).apply(
        lambda x: (x.iloc[-1] >= x).mean(), raw=False).rename("gold_ratio_pct")


def gold_ratio_z(prices_df, window=GOLD_RATIO_WINDOW):
    """比值的滚动 z-score ✓（另一种口径，供对照）。"""
    r = gold_ratio(prices_df)
    if r.empty:
        return r
    m = r.rolling(window, min_periods=window).mean()
    s = r.rolling(window, min_periods=window).std()
    return ((r - m) / s).rename("gold_ratio_z")
