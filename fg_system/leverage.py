# -*- coding: utf-8 -*-
"""杠杆 ETF 损耗归因（§4.5）。

两个独立损耗必须分开看：
  ① 波动率拖累（数学必然）= 连续时间近似下 年化 ≈ N(N-1)/2 × σ²
  ② 产品损耗（费用 + 融资成本 + 跟踪误差）

口径（本模块的定义，必须与文档一致）：
  参照基准是「N 倍线性收益」= N × 标的累计收益（即"不懂杠杆的人以为的收益"）。
    波动率拖累 = 线性收益年化 − 每日再平衡理论收益年化
    产品损耗   = 每日再平衡理论收益年化 − 实际 ETF 收益年化
    合计       = 线性收益年化 − 实际 ETF 收益年化

  实测（2016-09 ~ 2026-09）：TQQQ 合计 20.22%/年（其中波动率拖累 12.00、产品 8.22）；
  SOXL 46.81%/年；UPRO 12.02%/年。SOXL 的波动率拖累与理论 3σ² 高度吻合
  （理论 36.3% vs 实测 37.86%），说明这是数学必然，无法通过挑选产品规避。
"""
import numpy as np
import pandas as pd

from fg_system import config


def vol_decay_rate(sigma, n=3):
    """年化波动率拖累 ≈ N(N-1)/2 × σ²。σ 为**标的**年化波动率。"""
    return n * (n - 1) / 2.0 * sigma ** 2


def _annualize(total_return, n_periods, periods_per_year=252.0):
    years = n_periods / periods_per_year
    if years <= 0:
        return float("nan")
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def decompose(und_ret, lev_ret, n=3, periods_per_year=252.0):
    """把损耗拆成波动率拖累与产品损耗（均为年化）。输入为已对齐的日收益率序列。"""
    und_ret = pd.Series(und_ret).dropna()
    lev_ret = pd.Series(lev_ret).reindex(und_ret.index).dropna()
    und_ret = und_ret.reindex(lev_ret.index)

    n_periods = len(lev_ret)
    if n_periods == 0:
        return {"sigma": float("nan"), "vol_decay_annual": float("nan"),
                "product_cost_annual": float("nan"), "total_annual": float("nan")}

    sigma = float(und_ret.std() * np.sqrt(periods_per_year))
    und_cum = float((1.0 + und_ret).prod() - 1.0)
    linear_ann = n * _annualize(und_cum, n_periods, periods_per_year)
    rebalanced_ann = _annualize(float((1.0 + n * und_ret).prod() - 1.0), n_periods,
                                periods_per_year)
    actual_ann = _annualize(float((1.0 + lev_ret).prod() - 1.0), n_periods, periods_per_year)

    return {
        "sigma": sigma,
        "vol_decay_annual": linear_ann - rebalanced_ann,
        "product_cost_annual": rebalanced_ann - actual_ann,
        "total_annual": linear_ann - actual_ann,
    }


def current_decay_rate(und_ret, sigma_window=20, n=3, product_rate=None):
    """当前损耗速率（年化）= N(N-1)/2 × σ²(近 20 日) + 产品损耗率。

    用于仪表盘观测（§4.5 约束 4：v1 只观测，不参与仓位计算）。
    """
    product_rate = product_rate or 0.0
    recent = pd.Series(und_ret).dropna().tail(sigma_window)
    if len(recent) < sigma_window:
        return float("nan")
    sigma = float(recent.std() * np.sqrt(252.0))
    return vol_decay_rate(sigma, n) + product_rate


def attribution_table(prices, symbol=None):
    """生成损耗归因表（§11.6 强制输出）。prices 为长表 date,symbol,close。"""
    rows = []
    for lev, und in config.UNDERLYING_MAP.items():
        if symbol and lev != symbol:
            continue
        a = prices[prices["symbol"] == lev].set_index("date")["close"].sort_index()
        b = prices[prices["symbol"] == und].set_index("date")["close"].sort_index()
        joined = pd.concat([a.rename("lev"), b.rename("und")], axis=1).dropna()
        if len(joined) < 200:
            continue
        out = decompose(
            joined["und"].pct_change().dropna(),
            joined["lev"].pct_change().dropna(),
            n=config.LEVERAGE_RATIO[lev],
        )
        rows.append({
            "leveraged": lev,
            "underlying": und,
            "years": len(joined) / 252.0,
            "sigma": out["sigma"],
            "vol_decay_annual": out["vol_decay_annual"],
            "product_cost_annual": out["product_cost_annual"],
            "total_annual": out["total_annual"],
        })
    return pd.DataFrame(rows)
