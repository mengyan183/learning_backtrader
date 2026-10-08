# -*- coding: utf-8 -*-
"""进化就绪度（第 14 条）。

**本模块只做「观测」，不改任何参数。** 理由见第 14.1 条：
自动「发现问题」可以，自动「改变参数」不行 —— 后者是拟合历史（第 13.1 条）。

**为什么需要它**：系统已有的自动进化（口径自动切换）是**静默**的 ——
数据没到位就回退、到位了就切换，用户看不到"还差多少"。
本模块把它**显式化**，并回答「下一次自动升级是什么时候」。

**它回答三个问题**：
  1. 每个数据源**现在**处于什么状态？（就绪 / 回退 / 缺数据）
  2. 距**下一次自动升级**还差多少？（不依赖任何人做判断）
  3. 瓶颈在**数据**还是在**算法**？（第 14.5 条：本系统当前全部在数据）
"""
import pandas as pd

from fg_system import config
from fg_system.data import loader


def shoutu_readiness(shoutu_wide=None, symbols=None):
    """逐标的的守猪待兔数据就绪度。

    返回 DataFrame（index = symbol）：

    | 列 | 含义 |
    |---|---|
    | `days` | 已积累天数 |
    | `needed` | 分位数口径所需天数（= `config.RANK_WINDOW`） |
    | `remaining` | 距分位数生效还差多少天 |
    | `mode` | **当前实际生效**的口径（`percentile` / `fixed`） |
    | `first` / `last` | 数据区间 |

    **`mode` 是"实际生效"而不是"配置值"** —— 这两者当前不同
    （配置是 `percentile`，但只有 2 天数据 ⇒ 实际回退 `fixed`）。
    把两者混为一谈会让人误以为分位数已经在用。
    """
    symbols = list(symbols) if symbols else list(config.SHOUTU_SYMBOLS)
    wide = loader.load_shoutu_fng() if shoutu_wide is None else shoutu_wide
    need = config.RANK_WINDOW
    rows = []
    for s in symbols:
        if wide is None or wide.empty or s not in wide.columns:
            col = pd.Series(dtype=float)
        else:
            col = wide[s].dropna()
        days = int(len(col))
        # 配置若不是分位数口径，则"还差多少天"没有意义（永不切换）
        pct_configured = config.SHOUTU_INDEX_MODE == "percentile"
        rows.append({
            "symbol": s,
            "days": days,
            "needed": need,
            "remaining": (max(0, need - days) if pct_configured else 0),
            "mode": ("percentile" if days >= need else "fixed")
                    if pct_configured else config.SHOUTU_INDEX_MODE,
            "first": col.index.min() if days else None,
            "last": col.index.max() if days else None,
        })
    return pd.DataFrame(rows).set_index("symbol")


def readiness(shoutu_wide=None):
    """系统整体的进化就绪度（第 14.4 条）。

    返回 dict：
      `stage`            当前阶段（第 13.0 条）
      `shoutu_mode`      **配置**的口径（未必等于实际生效口径）
      `shoutu`           逐标的就绪度 DataFrame
      `next_upgrade`     (symbol, remaining) —— 最早会自动升级的标的；无则 None
    """
    table = shoutu_readiness(shoutu_wide)
    pending = table[table["remaining"] > 0]
    next_upgrade = None
    if not pending.empty:
        s = pending["remaining"].idxmin()
        next_upgrade = (s, int(pending.loc[s, "remaining"]))
    return {
        "stage": config.STAGE,
        "shoutu_mode": config.SHOUTU_INDEX_MODE,
        "shoutu": table,
        "next_upgrade": next_upgrade,
    }
