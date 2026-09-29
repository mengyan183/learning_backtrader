# -*- coding: utf-8 -*-
"""CF2 BTC 价格因子（先验权重 50%，§5.2）。

四个子项等权（与 v1 F3 结构对称）：动量(20/60日)、RSI(14)、距 52 周回撤（反转）、
20 日已实现波动率（反转）。

**红线（v1 §4.5 约束 1）**：输入必须是 **BTC 现货**，禁止使用 BITX/MSTX 等
杠杆 ETF 自身价格——杠杆 ETF 含年化数十个百分点的波动率拖累，会把产品损耗
系统性误读为「恐惧」，产生持续的错误买入信号。
"""
import numpy as np

from fg_system import config
from fg_system.factors.base import Factor, rolling_pct
from fg_system.factors.price import drawdown_52w, rsi

BTC_COLUMN = ("BTC", "close")


class CryptoPriceFactor(Factor):
    name = "crypto_price"
    market = "crypto"

    def raw(self, wide):
        if BTC_COLUMN not in wide.columns:
            raise ValueError(
                "CF2 必须使用 BTC 现货（%s），当前列: %s" % (BTC_COLUMN, list(wide.columns)))
        btc = wide[BTC_COLUMN]
        w = config.RANK_WINDOW

        mom = (rolling_pct(btc.pct_change(20), w)
               + rolling_pct(btc.pct_change(60), w)) / 2.0      # 正向
        strength = rolling_pct(rsi(btc), w)                     # 正向
        dd = 1.0 - rolling_pct(drawdown_52w(btc), w)            # 反转
        vol = btc.pct_change().rolling(20).std() * np.sqrt(252)
        calm = 1.0 - rolling_pct(vol, w)                        # 反转
        return (mom + strength + dd + calm) / 4.0
