# -*- coding: utf-8 -*-
"""B1：回撤预算 → 仓位上限 的显式映射曲线（只答「余量还剩多少」）。

依据（规划 v2.0 §方向 B「B1」+ 团队评审 C7 + `config.py` 第 12.7 条）：

  - 数据源（**离线、只读**）：
      `CORE_CAP` / `AMMO_CAP`（`fg_system/config.py`）
      + 第 12.7 条「`CORE_CAP` × `AMMO_CAP` 组合级 30 格矩阵」的**组合最大回撤**。
    矩阵原始表在 `docs/trading-discipline.md` 第 12.7 条，每格为「组合最大回撤 / 年化」；
    本模块**只取回撤，丢弃年化**（见下）。

  - ⚠️ **结构性防护（第 12.7 条明令：「不按矩阵挑 Calmar / 年化最高的格子」）**：
    曲线**禁止输出** Calmar / 年化 / Sortino / Sharpe / 年化波动 等「效率」列
    —— **只留回撤 / CVaR 尾部指标**。这是把「先验上限」变成「可验证约束」，
    **只回答「余量还剩多少」，不回答「更好的组合是什么」**。
    守卫：`tests/test_budget_curve_no_efficiency_cols.py`。

  - 产物带 `OOS_WARNING`（口径为历史路径拟合，OOS 稳定性未验证）。
  - 产物**禁止**作为 `evolve_propose` 输入（否则「余量」会被反向用来调参）。
"""
import pandas as pd

from fg_system import config
from fg_system import risk

# 回撤预算（-40%，见 config.py 第 12.7 条推导与 tests/test_config.py 护栏）。
BUDGET = 0.40

# CVaR 置信水平：CVaR95 ⇒ 尾部 5%（alpha=0.05）；CVaR99 ⇒ 尾部 1%（alpha=0.01）。
# 语义与 `risk.cvar(returns, alpha)` 一致（alpha = 尾部比例）。
CVAR_ALPHAS = {"cvar95": 0.05, "cvar99": 0.01}

# 第 12.7 条「组合级 30 格矩阵」的**组合最大回撤**（只取回撤列，年化列已丢弃）。
# 单位：负值（回撤）。来源：docs/trading-discipline.md 第 12.7 条。
GRID_DRAWDOWN = {
    0.35: {0.12: -0.2489, 0.15: -0.2724, 0.20: -0.3110, 0.25: -0.3490, 0.30: -0.3866},
    0.40: {0.12: -0.2692, 0.15: -0.2925, 0.20: -0.3310, 0.25: -0.3687, 0.30: -0.4061},
    0.45: {0.12: -0.2897, 0.15: -0.3127, 0.20: -0.3509, 0.25: -0.3884, 0.30: -0.4252},
    0.50: {0.12: -0.3098, 0.15: -0.3328, 0.20: -0.4025, 0.25: -0.4420, 0.30: -0.4445},
    0.55: {0.12: -0.3298, 0.15: -0.3525, 0.20: -0.4168, 0.25: -0.4553, 0.30: -0.4636},
    0.70: {0.12: -0.3824, 0.15: -0.4066, 0.20: -0.4454, 0.25: -0.4821, 0.30: -0.5168},
}

OOS_WARNING = (
    "历史路径拟合：本曲线源自 2016-2026 全样本的组合级 30 格矩阵（第 12.7 条），"
    "OOS 稳定性未单独验证，样本长度下多数格子低置信。曲线**只回答「余量还剩多少」**，"
    "**不回答「更好的组合是什么」**；**禁止**据此挑 Calmar/年化最高的格子。"
)


def _tail_cvar():
    """在「30 格矩阵的组合回撤分布」上求 CVaR95 / CVaR99（复用 risk.cvar）。"""
    dist = pd.Series([d for row in GRID_DRAWDOWN.values() for d in row.values()])
    return {name: risk.cvar(dist, alpha=a) for name, a in CVAR_ALPHAS.items()}


def build_curve():
    """构建「回撤预算 → 仓位上限」曲线产物（**无效率列**）。

    返回 dict：
      grid          每格 {core_cap, ammo_cap, drawdown, margin_pp,
                         cvar95, cvar99}
      budget        回撤预算（正数，如 0.40）
      tail          30 格回撤分布上的 CVaR95/CVaR99
      OOS_WARNING   OOS 口径警示
      scope         声明「只答余量、不答更优组合」
      forbidden_input_to  声明禁止作为 evolve_propose 输入
    """
    tail = _tail_cvar()
    grid = []
    for core_cap in sorted(GRID_DRAWDOWN):
        for ammo_cap in sorted(GRID_DRAWDOWN[core_cap]):
            dd = GRID_DRAWDOWN[core_cap][ammo_cap]
            margin_pp = (BUDGET + dd) * 100.0   # 预算 - 实际回撤（pp）；负=击穿
            grid.append({
                "core_cap": core_cap,
                "ammo_cap": ammo_cap,
                "drawdown": dd,
                "margin_pp": round(margin_pp, 2),
                "cvar95": tail["cvar95"],
                "cvar99": tail["cvar99"],
            })

    selected = {"core_cap": config.CORE_CAP, "ammo_cap": config.AMMO_CAP}
    selected_margin = None
    for p in grid:
        if p["core_cap"] == config.CORE_CAP and p["ammo_cap"] == config.AMMO_CAP:
            selected_margin = p["margin_pp"]
            break

    return {
        "budget": BUDGET,
        "tail": tail,
        "selected": dict(selected, margin_pp=selected_margin),
        "grid": grid,
        "OOS_WARNING": OOS_WARNING,
        "scope": {
            "answers": "只回答「余量还剩多少」（当前参数相对 -40% 回撤预算的余量）",
            "does_not_answer": "不回答「更好的组合是什么」——禁止据此挑最高效的格子",
            "source": "docs/trading-discipline.md 第 12.7 条组合级 30 格矩阵（只取回撤列）",
        },
        "forbidden_input_to": ["evolve_propose"],
    }
