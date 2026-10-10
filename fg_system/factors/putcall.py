# -*- coding: utf-8 -*-
"""F-011 Put-Call 情绪因子（CBOE 总 P/C 比，§5.2 扩展，2026-10-10 提案采纳）。

方向：**逆向**——P/C 高 = 市场恐慌 = 低分（恐惧端）；P/C 低 = 贪婪 = 高分。
数据源：wide 宽表 `("PUT_CALL", "ratio")`（load_wide 从 Data/raw/putcall.csv 读入，
随 shift 整体后移 ⇒ 平移测试通过）。列 total_ratio（CBOE 总 P/C 比，B-6 链路，2006-11 起）。

归一化：滚动 RANK_WINDOW（756 日）百分位，与 vix/term/price/breadth/fed 同口径
（index.py 红线：禁止全样本统计量归一化）。
缺失日：reindex 后 ffill 前值填充（审批确认口径；同时避免 rolling.apply 遇 NaN 全灭）。

F-011 依据（evolution/factors.md，2026-10-10 实检 verified）：
  ICIR 0.94/0.97/1.33/1.51（前瞻 5/10/20/40 日），正占比 82~93%，近窗无衰减；
  与五因子同期相关 |r| 均 < 0.40（vix -0.24 / term -0.40 / price -0.31 / breadth -0.13 / fed +0.16）
  ⇒ 不构成重复计入。
"""
import pandas as pd

from fg_system import config
from fg_system.factors.base import Factor, rolling_pct


class PutCallFactor(Factor):
    """CBOE 总 Put/Call 比率 → 0-100 情绪分（逆向：高分 = 贪婪）。"""

    name = "putcall"
    COL = ("PUT_CALL", "ratio")

    def raw(self, wide):
        """缺失日前值填充 → 滚动分位（正向 P/C）→ 逆向 1-pct → 高分 = 贪婪。"""
        if self.COL not in wide.columns:
            return pd.Series(float("nan"), index=wide.index)
        s = wide[self.COL].astype(float)
        s = s.ffill()                             # 缺失日前值填充（审批口径；
                                                  #   rolling.apply 窗口含 NaN 会全灭）
        pct = rolling_pct(s, config.RANK_WINDOW)  # [0,1] 滚动分位（无 NaN 输入）
        return 1.0 - pct                          # 逆向：P/C 高 → raw 低 → 恐惧
