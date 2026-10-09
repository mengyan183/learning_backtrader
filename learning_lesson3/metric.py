# -*- coding: utf-8 -*-
# 导入backtrader
import datetime

import backtrader as bt
import backtrader.indicators as btind  # 导入策略分析模块
import pandas as pd

'''
bt两种不同获取指标方式
1：通过datafeeds模块导入已经计算好的指标（例如 lesson2中的新增pb、pe指标）
2：编写策略时调用indicators指标模块临时计算指标（例如 5日均线和布林带）

注意点：
1：只有在编写策略时，才会涉及到指标计算和使用，主要在_init_()和next()方法中使用
2：前置初始化指标，_init_函数每个策略只会加载一次，next函数在回测过程中会持续循环调用，因此建议指标计算放到_init_中，next中只使用指标
3：使用indicators模块计算指标默认是对 self datas 数据对象中的第一张表中的第一条line（close）计算指标
4：函数简写形式（SMA\EMA）

bt中运算符优化
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
        self.sma5_1 = btind.SimpleMovingAverage(period=5)  # 指定第一个数据表格 5日均线
        self.sma5_2 = btind.SMA(self.data, period=5)  # 指定第一个数据表格 5日均线
        self.sma5_3 = btind.SMA(self.data.close, period=5)  # 指定第一个数据表格的close列 5日均线
        self.sma5_4 = btind.SMA(self.datas[0].lines[0], period=5)  # 详细写法 5日均线

        self.sma5 = btind.SMA(period=5)  # 5日均线
        self.sma10 = btind.SMA(period=10)  # 10日均线
        self.buy_sig = self.sma5 > self.sma10  # 5日均线上穿10日均线

    # 在next中直接使用 init 中计算好的指标
    def next(self):
        print("===========================")
        print("stock", self.datas[0]._name)
        # 获取该行数据时间
        print("datatime", self.datas[0].datetime.date(0))
        # 打印 当日、昨日、前日的均线
        print("sma5_1", self.sma5_1.get(ago=0, size=3))
        print("sma5_2", self.sma5_2.get(ago=0, size=3))
        print("sma5_3", self.sma5_3.get(ago=0, size=3))
        print("sma5_4", self.sma5_4.get(ago=0, size=3))

        # 数据索引简写
        # 不进行具体运算时，不带索引得到的依旧是line对象
        print("close", self.data.close[0], self.data.close)
        print("sma5", self.sma5[0], self.sma5)
        print("sma10", self.sma10[0], self.sma10)
        print("bug_sig", self.buy_sig[0], self.buy_sig)

        # 但在具体使用的时候，不带索引默认会返回索引0位置的数据进行运算
        if self.data.close > self.sma5:
            print('------收盘价上穿5日均线------')
        if self.data.close[0] > self.sma10:
            print('------收盘价上穿10日均线------')
        if self.buy_sig:
            print("buy")
            self.buy()


daily_price = pd.read_csv("../Data/daily_price.csv", parse_dates=['datetime'],
                          date_format='%Y-%m-%d')


# 数据新增指标(新增line)
class PandasData_more(bt.feeds.PandasData):
    lines = ('pe', 'pb')  # 要新增的字段
    # 设置 新增字段的索引位置
    params = (
        ('pe', -1)  # -1表示自动按照列名匹配数据
        , ('pb', -1)
    )


trade_info = pd.read_csv("../Data/trade_info.csv", parse_dates=['trade_date'],
                         date_format='%Y-%m-%d')


def get_data(code, start_date, end_date):
    for stock in daily_price['sec_code'].unique():
        if code != stock:
            continue
        # 日期对齐
        # 获取所有的日期
        date_df = pd.DataFrame(daily_price['datetime'].unique(), columns=['datetime'])
        # 获取原始数据
        df = daily_price.query(f"sec_code=='{stock}'")[
            ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
        # 使用时间字段作为关联字段，获取该股票的每个交易日的数据
        merge_data = pd.merge(date_df, df, how='left', on='datetime')
        # 索引优化，提高效率
        merge_data = merge_data.set_index('datetime')
        # 补齐该股票不存在交易日的数据
        # 数据补齐
        # 行情数据缺失：在补齐交易日过程中，会使得补充的交易日缺失行情数据，需对缺失数据进行填充。比如将缺失的 volume 填充为 0，表示股票无法交易的状态；将缺失的高开低收做前向填充；将上市前缺失的高开低收填充为 0 等
        # 值为空 补齐0
        merge_data.loc[:, ['volume', 'openinterest']] = merge_data.loc[:, ['volume', 'openinterest']].fillna(0)
        # 使用前一个非空的值
        merge_data.loc[:, ['open', 'high', 'low', 'close']] = merge_data.loc[:,
                                                              ['open', 'high', 'low', 'close']].ffill()
        # 依旧为空，补齐为0
        merge_data.loc[:, ['open', 'high', 'low', 'close']] = merge_data.loc[:,
                                                              ['open', 'high', 'low', 'close']].fillna(0)

        # 为原始数据新增字段以及值
        merge_data['pe'] = 2
        merge_data['pb'] = 3
        expend_daily_price = PandasData_more(dataname=merge_data, fromdate=start_date,
                                             todate=end_date)
        return expend_daily_price
    return None


cerebro = bt.Cerebro()
st_date = datetime.datetime(2019, 1, 2)
end_date = datetime.datetime(2019, 3, 2)
datafeed1 = get_data('600466.SH', st_date, end_date)
if datafeed1 is None:
    raise Exception("not found data")
datafeed2 = get_data('603228.SH', st_date, end_date)
if datafeed2 is None:
    raise Exception("not found data")

cerebro.adddata(datafeed1, name='600466.SH')
cerebro.adddata(datafeed2, name='603228.SH')
cerebro.addstrategy(MyStrategy)
rasult = cerebro.run()
