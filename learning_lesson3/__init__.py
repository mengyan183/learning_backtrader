# -*- coding: utf-8 -*-
# 导入backtrader
import datetime

import backtrader as bt
import backtrader.indicators as btind  # 导入策略分析模块
import pandas as pd
import tushare as ts

'''
bt两种不同获取指标方式
1：通过datafeeds模块导入已经计算好的指标（例如 lesson2中的新增pb、pe指标）
2：编写策略时调用indicators指标模块临时计算指标（例如 5日均线和布林带）

注意点：
1：只有在编写策略时，才会涉及到指标计算和使用，主要在_init_()和next()方法中使用
2：前置初始化指标，_init_函数每个策略只会加载一次，next函数在回测过程中会持续循环调用，因此建议指标计算放到_init_中，next中只使用指标
3：使用indicators模块计算指标默认是对 self datas 数据对象中的第一张表中的第一条line（close）计算指标
4：函数简写形式（SMA\EMA）
'''


class MyStrategy(bt.Strategy):

    # 前置计算指标
    def __init__(self):
        sma1 = btind.SimpleMovingAverage(self.data)  # 简单移动均线
        ema1 = btind.ExponentialMovingAverage()  # 指数移动均线
        close_over_sma = self.data.close > sma1
        close_over_ema = self.data.close > ema1
        sma_ema_diff = sma1 - ema1
        # 生成交易信号
        self.buy_sig = bt.And(close_over_sma, close_over_ema, sma_ema_diff > 0)

        # 函数简写
        self.sma1 = btind.SimpleMovingAverage(period=5)  # 指定第一个数据表格 5日均线
        self.sma2 = btind.SMA(self.data, period=5)  # 指定第一个数据表格 5日均线
        self.sma3 = btind.SMA(self.data.close, period=5)  # 指定第一个数据表格的close列 5日均线
        self.sma4 = btind.SMA(self.datas[0].lines[0], period=5)  # 详细写法 5日均线

    # 在next中直接使用 init 中计算好的指标
    def next(self):
        # 获取该行数据时间
        print("datatime", self.datas[0].datetime.date(0))
        # 打印 当日、昨日、前日的均线
        print("sma1", self.sma1.get(ago=0, size=3))
        print("sma2", self.sma2.get(ago=0, size=3))
        print("sma3", self.sma3.get(ago=0, size=3))
        print("sma4", self.sma4.get(ago=0, size=3))

        if self.buy_sig:
            self.buy()


# 使用akshare获取数据

# stock_zh_a_spot_em_df = ak.stock_zh_a_spot_em()
# print(stock_zh_a_spot_em_df)

# 使用Tushare获取数据，要严格保持OHLC的格式
ts.set_token("2ceccad6454e441f5572b4f11dc3f0cd7374c2c0a20aed49823ae8a0")
pro = ts.pro_api("2ceccad6454e441f5572b4f11dc3f0cd7374c2c0a20aed49823ae8a0")


def get_data_bytushare(code, start_date, end_date):
    df = ts.pro_bar(ts_code=code, adj='qfq', start_date=start_date, end_date=end_date, freq='M')
    df = df[['trade_date', 'open', 'high', 'low', 'close', 'vol']]
    df.columns = ['trade_date', 'open', 'high', 'low', 'close', 'volume']
    df.trade_date = pd.to_datetime(df.trade_date)
    df.index = df.trade_date
    df.sort_index(inplace=True)
    df.fillna(0.0, inplace=True)
    return df


# 恒瑞医药
data1 = get_data_bytushare('000001.SZ', '20251201', '20260101')
print(data1)
# 贵州茅台
data2 = get_data_bytushare('600519.SH', '20200101', '20211015')

cerebro = bt.Cerebro()
st_date = datetime.datetime(2019, 1, 2)
end_date = datetime.datetime(2021, 1, 28)
datafeed1 = bt.feeds.PandasData(dataname=data1, fromdate=st_date, todate=end_date)
cerebro.adddata(datafeed1, name='600466.SH')
datafeed2 = bt.feeds.PandasData(dataname=data2, fromdate=st_date, todate=end_date)
cerebro.adddata(datafeed2, name='603228.SH')
cerebro.addstrategy(MyStrategy)
rasult = cerebro.run()
