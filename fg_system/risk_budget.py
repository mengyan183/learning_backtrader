# -*- coding: utf-8 -*-
"""B1：回撤预算 → 仓位上限 的显式映射曲线（只答「余量还剩多少」）。

依据（规划 v2.0 §方向 B「B1」+ 团队评审 C7 + `config.py` 第 12.7 条）：

  - 数据源（**离线、只读**）：
      `CORE_CAP` / `AMMO_CAP`（`fg_system/config.py`）
      + **真实组合级日序列** `evolution/baseline.json::portfolio.daily`
        （`date / strategy_ret / bh_portfolio_ret / strategy_nav / bh_portfolio_nav`，
         `WEIGHTING="inv_vol"`、真实轨、`shift(1)` 防前视 —— 由主线 `3a78dff`(MT-07) 交付）。
    CVaR95/CVaR99 由 `risk.cvar()` 直接作用于 `strategy_ret` 求得；
    组合级回撤序列由 `strategy_nav` / `strategy_ret` 的峰谷求得。

  - ⚠️ **已弃用：纸面矩阵数据源** ✗
    本模块**首版**曾改用 `docs/trading-discipline.md` 第 12.7 条「`CORE_CAP` ×
    `AMMO_CAP` 组合级 30 格矩阵」的**组合最大回撤**（**纸面常量** ✗）。
    该口径**不是**真实组合回撤分布 ⇒ 用户 2026-10-13 裁定走**方案 B**（真实序列 ✓）。
    实测两者**差一个数量级**：纸面 `cvar95=-0.49945` / `max_drawdown≈-0.5168` ✗
    vs 真实 `cvar95≈-0.0359` / `max_drawdown=-0.387651` ✓
    ⇒ 纸面矩阵数据源**已弃用** ✗，本模块**不再**引用它。
    且真实序列只对应**当前生产参数**一组 (`CORE_CAP`/`AMMO_CAP`) ⇒
    30 格「参数敏感性矩阵」无法从单一真实序列还原（硬凑 = 编造 ✗）
    ⇒ 曲线的「网格」改为**真实回撤事件（episode）分布**（见 `grid`）。

  - ⚠️ **结构性防护（第 12.7 条明令：「不按矩阵挑 Calmar / 年化最高的格子」）**：
    曲线**禁止输出** Calmar / 年化 / Sortino / Sharpe / 年化波动 等「效率」列
    —— **只留回撤 / CVaR 尾部指标**。这是把「先验上限」变成「可验证约束」，
    **只回答「余量还剩多少」，不回答「更好的组合是什么」**。
    守卫：`tests/test_budget_curve_no_efficiency_cols.py`。

  - 产物带 `OOS_WARNING`（口径为历史路径拟合，OOS 稳定性未验证）。
  - 产物**禁止**作为 `evolve_propose` 输入（否则「余量」会被反向用来调参）。
  - **口径自证**：`max_drawdown` 必须与 `baseline.portfolio.strategy.full.max_drawdown`
    （**-0.387651**）一致 —— 不一致即口径有差，**不得硬凑** ✗（守卫测试断言）。
"""
import json
import os

import pandas as pd

from fg_system import config
from fg_system import risk

# 回撤预算（-40%，见 config.py 第 12.7 条推导与 tests/test_config.py 护栏）。
BUDGET = 0.40

# CVaR 置信水平：CVaR95 ⇒ 尾部 5%（alpha=0.05）；CVaR99 ⇒ 尾部 1%（alpha=0.01）。
# 语义与 `risk.cvar(returns, alpha)` 一致（alpha = 尾部比例）。
CVAR_ALPHAS = {"cvar95": 0.05, "cvar99": 0.01}

# 真实组合日序列数据源（相对仓库根）。**只读**。
BASELINE_RELPATH = os.path.join("evolution", "baseline.json")

# 数据源声明（写进产物，防「数字被脱来源引用」）。
SOURCE = "evolution/baseline.json → portfolio.daily (strategy_ret / strategy_nav)"

OOS_WARNING = (
    "历史路径拟合：本曲线源自 evolution/baseline.json 的真实组合日序列"
    "（portfolio.daily，WEIGHTING=inv_vol、真实轨、shift(1) 防前视），"
    "OOS 稳定性未单独验证，样本长度下尾部估计低置信。曲线**只回答「余量还剩多少」**，"
    "**不回答「更好的组合是什么」**；**禁止**据此挑 Calmar/年化最高的格子。"
)


def _repo_root():
    """仓库根（本文件位于 <root>/fg_system/）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_portfolio_daily(path=None):
    """读真实组合日序列（`baseline.portfolio.daily`）。缺失返回 None（不抛）。"""
    p = path or os.path.join(_repo_root(), BASELINE_RELPATH)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        baseline = json.load(fh)
    daily = baseline.get("portfolio", {}).get("daily")
    return daily or None


def _drawdown_series(nav):
    """净值序列 → 逐日回撤序列（相对历史峰值，负值）。"""
    peak = nav.cummax()
    return (nav - peak) / peak


def _drawdown_episodes(dates, dd):
    """回撤序列 → 回撤事件列表（每个事件的谷底）。

    事件定义：回撤由 0 转负起（开始回撤），到再次回到 0（创新高）止。
    每行 = 事件谷底（`drawdown` 为该事件最深回撤、负值）。
    ⇒ 曲线「网格」= **真实回撤分布**（而非纸面矩阵的参数格）。
    """
    episodes = []
    start = None
    for i in range(len(dd)):
        v = float(dd.iloc[i])
        if v < 0 and start is None:
            start = i
        elif v >= 0 and start is not None:   # 回到高位（新峰）⇒ 事件结束
            episodes.append(dd.iloc[start:i])
            start = None
    if start is not None:
        episodes.append(dd.iloc[start:])

    rows = []
    for seg in episodes:
        trough = float(seg.min())
        rows.append({
            "start_date": dates.iloc[seg.index[0]],
            "end_date": dates.iloc[seg.index[-1]],
            "drawdown": trough,
        })
    return rows


def build_curve(baseline_path=None):
    """构建「回撤预算 → 仓位上限」曲线产物（**无效率列**）。

    数据源 = `evolution/baseline.json::portfolio.daily`（真实组合序列）。
    缺失真实序列时 **raise**（不静默回退纸面矩阵 ✗ —— 那正是被弃用的口径）。

    返回 dict：
      source        数据源声明（`baseline.portfolio.daily`）
      daily_points  真实序列点数（自证与序列一致）
      max_drawdown  真实组合最大回撤（与 `full.max_drawdown` 一致 —— 口径自证）
      tail          真实收益序列上的 CVaR95/CVaR99（`risk.cvar`）
      grid          真实回撤事件分布，每行 {start_date, end_date, drawdown,
                    cvar95, cvar99}
      budget        回撤预算（正数，如 0.40）
      selected      当前生产参数 {core_cap, ammo_cap, margin_pp}
      OOS_WARNING   OOS 口径警示
      scope         声明「只答余量、不答更优组合」
      forbidden_input_to  声明禁止作为 evolve_propose 输入
    """
    daily = load_portfolio_daily(baseline_path)
    if not daily or not daily.get("strategy_ret") or not daily.get("strategy_nav"):
        raise RuntimeError(
            "缺少真实组合日序列 evolution/baseline.json::portfolio.daily"
            "（需主线 MT-07 产物；**不**回退纸面矩阵 ✗）")

    ret = pd.Series(daily["strategy_ret"])
    nav = pd.Series(daily["strategy_nav"])
    dates = pd.Series(daily["date"])
    n = len(ret)

    tail = {name: risk.cvar(ret, alpha=a) for name, a in CVAR_ALPHAS.items()}
    max_dd = risk.max_drawdown(ret)

    dd = _drawdown_series(nav)
    episodes = _drawdown_episodes(dates, dd)

    grid = []
    for ep in episodes:
        grid.append({
            "start_date": ep["start_date"],
            "end_date": ep["end_date"],
            "drawdown": ep["drawdown"],
            "cvar95": tail["cvar95"],
            "cvar99": tail["cvar99"],
        })

    # 余量（pp）：预算 - 真实最大回撤；负 = 击穿预算。
    margin_pp = round((BUDGET + max_dd) * 100.0, 2)
    selected = {
        "core_cap": config.CORE_CAP,
        "ammo_cap": config.AMMO_CAP,
        "margin_pp": margin_pp,
    }

    return {
        "source": SOURCE,
        "daily_points": n,
        "max_drawdown": max_dd,
        "budget": BUDGET,
        "tail": tail,
        "selected": selected,
        "grid": grid,
        "OOS_WARNING": OOS_WARNING,
        "scope": {
            "answers": "只回答「余量还剩多少」（当前参数相对 -40% 回撤预算的余量）",
            "does_not_answer": "不回答「更好的组合是什么」——禁止据此挑最高效的格子",
            "source": SOURCE + "（真实轨；纸面矩阵数据源已弃用 ✗）",
        },
        "forbidden_input_to": ["evolve_propose"],
    }
