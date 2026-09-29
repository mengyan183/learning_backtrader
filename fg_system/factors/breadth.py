# -*- coding: utf-8 -*-
"""F4 广度代理（先验权重 20%，§5.2）。

三个子项（等权）：
  ① RSP/SPY 相对强弱（等权 vs 市值权，60 日变化率）
  ② QQQ/SPY 相对强弱（成长 vs 大盘，60 日变化率）
  ③ 均线宽度：SPY/QQQ/RSP/IWM 中收盘价在 200 日均线上方的比例

前两项做滚动分位归一；第三项本身已是有界值（0~1），直接使用。
输入全部为无杠杆标的（§4.5 约束 1）。
"""
from fg_system import config
from fg_system.factors.base import Factor, rolling_pct


class BreadthFactor(Factor):
    name = "breadth"

    def raw(self, wide):
        missing = [s for s in config.BREADTH_SYMBOLS if (s, "close") not in wide.columns]
        if missing:
            raise ValueError("广度标的缺失: %s" % missing)

        spy = wide[("SPY", "close")]
        rsp = wide[("RSP", "close")]
        qqq = wide[("QQQ", "close")]
        w = config.RANK_WINDOW

        equal_vs_cap = rolling_pct((rsp / spy).pct_change(60), w)
        growth_vs_cap = rolling_pct((qqq / spy).pct_change(60), w)

        above = None
        for sym in config.BREADTH_SYMBOLS:
            s = wide[(sym, "close")]
            ma200 = s.rolling(200, min_periods=200).mean()
            flag = (s > ma200).astype(float).where(ma200.notna())
            above = flag if above is None else above + flag
        above = above / len(config.BREADTH_SYMBOLS)      # 0 ~ 1

        return (equal_vs_cap + growth_vs_cap + above) / 3.0
