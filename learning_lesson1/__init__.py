# -*- coding: utf-8 -*-
# 导入backtrader
import datetime

import backtrader as bt
import pandas as pd

# 实例化 cerebro
from backtrader import Order

cerebro = bt.Cerebro()

# 导入数据
daily_price = pd.read_csv("../Data/daily_price.csv", parse_dates=['datetime'],
                          date_format='%Y-%m-%d')
trade_info = pd.read_csv("../Data/trade_info.csv", parse_dates=['trade_date'],
                         date_format='%Y-%m-%d')

# # 该段代码生成的数据运行会报错
# # AttributeError: 'int' object has no attribute 'to_pydatetime'
# # 根据股票代码分组，循环导入
# for stock in daily_price['sec_code'].unique():
#     # 日期对齐
#     # 根据 daily_price 行/字段结构构建空的df
#     empty_df = pd.DataFrame(index=daily_price.index.unique())
#     # 根据股票代码获取对应的数据
#     stock_data = daily_price.query(f"sec_code=='{stock}'")[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
#     # empty_df left join stock_data on index
#     # 各股交易日不统一：上市日期不一致、退市日期不一致、回测区间内出现停牌等，都会使得不同股票各自的交易日数量不统一，所以要以回测区间内所有交易日为基础，对每只股票缺失的交易日进行补齐
#     # 所以要使用left join，补齐全部要分析的交易日数据
#     merge_data = pd.merge(empty_df, stock_data, left_index=True, right_index=True, how='left')
#     # 数据补齐
#     # 行情数据缺失：在补齐交易日过程中，会使得补充的交易日缺失行情数据，需对缺失数据进行填充。比如将缺失的 volume 填充为 0，表示股票无法交易的状态；将缺失的高开低收做前向填充；将上市前缺失的高开低收填充为 0 等
#     # 值为空 补齐0
#     merge_data.loc[:, ['volume', 'openinterest']] = merge_data.loc[:, ['volume', 'openinterest']].fillna(0)
#     # 使用前一个非空的值
#     merge_data.loc[:, ['open', 'high', 'low', 'close']] = merge_data.loc[:, ['open', 'high', 'low', 'close']].ffill()
#     # 依旧为空，补齐为0
#     merge_data.loc[:, ['open', 'high', 'low', 'close']] = merge_data.loc[:, ['open', 'high', 'low', 'close']].fillna(0)
#     # 生成要送给cerebros的数据
#     feeds_pandas_data = bt.feeds.PandasData(dataname=merge_data, fromdate=datetime.datetime(2019, 1, 2),
#                                             todate=datetime.datetime(2021, 1, 28))
#     # 将数据送给cerebro,数据名称和股票名称对齐
#     cerebro.adddata(feeds_pandas_data, name=stock)
#     print(f"{stock} done")

# 按股票代码，依次循环传入数据
for stock in daily_price['sec_code'].unique():
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
    merge_data.loc[:, ['open', 'high', 'low', 'close']] = merge_data.loc[:, ['open', 'high', 'low', 'close']].ffill()
    # 依旧为空，补齐为0
    merge_data.loc[:, ['open', 'high', 'low', 'close']] = merge_data.loc[:, ['open', 'high', 'low', 'close']].fillna(0)
    # 生成要送给cerebros的数据
    feeds_pandas_data = bt.feeds.PandasData(dataname=merge_data, fromdate=datetime.datetime(2019, 1, 2),
                                            todate=datetime.datetime(2021, 1, 28))
    # 将数据送给cerebro,数据名称和股票名称对齐
    cerebro.adddata(feeds_pandas_data, name=stock)
    print(f"{stock} done")

print("All stock Done !")

# 配置回测条件
# 需要使用cerebro.broker
# 初始资金
cerebro.broker.setcash(100000000.0)
# 设置佣金(交易手续费),双边各 0.0003
cerebro.broker.setcommission(commission=0.0003)
# 设置滑点(挂单价格和实际成交价格的差异),双边各 0.0001
cerebro.broker.set_slippage_perc(perc=0.0001)

# 配置策略分析模块和观测模块，为回测结果增加统计指标
# 收益率时序数据
cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='pnl')
# 年化收益率
cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='_AnnualReturn')
# 夏普比率
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='_SharpeRatio')
# 回撤
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='_DrawDown')

'''
_init_ 函数只在回测过程中初始化时条用一次
next 函数会在每个交易日依次循环调用

为了提高执行效率，对于策略中依赖的数据放到init中计算生成，避免重复计算
对于复杂的选股策略，建议参考文本的方式，提前确定好调仓日期、成分、权重，再将结果导入到bt中计算

bt默认情况下在t日运行下单函数，t+1日以开盘价成交

bt相关api含义
self.close 平仓
self.buy 买入、做多
self.sell 卖出、做空
self.cancel 取消订单
self.order_target_percent 按照持仓百分比下单，多退少补，对于股票当前无持仓或持有多单（仓位>0）时
，如果目标占比大于当前持仓占比，则会生成多单买入不够的部分
，如果目标占比小于当前持仓占比，则会生成空单卖出不够的部分
'''


# 编写交易策略
# 自定义策略，继承bt.Strategy实现
class MyStrategy(bt.Strategy):

    # 交易记录日志（可省略，默认不输出结果）
    def log(self, txt, dt=None, doprint=False):
        if self.params.printlog or doprint:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()},{txt}')

    '''
    回测日志打印
    notify_order 订单日志
    notify_trade 交易日志
    notify_cashvalue 资金信息
    notify_store 交易事件
    '''

    def notify_order(self, order: Order):
        # 跳过未处理的订单
        if order.status in [Order.Submitted, Order.Accepted]:
            pass
        if order.status in [Order.Completed, Order.Canceled, Order.Margin]:
            if order.isbuy():
                self.log(
                    'BUY EXECUTED, ref:%.0f，Price: %.2f, Cost: %.2f, Comm %.2f, Size: %.2f, Stock: %s' %
                    (order.ref,  # 订单编号
                     order.executed.price,  # 成交价
                     order.executed.value,  # 成交额
                     order.executed.comm,  # 佣金
                     order.executed.size,  # 成交量
                     order.data._name))  # 股票名称
            if order.issell():
                self.log('SELL EXECUTED, ref:%.0f, Price: %.2f, Cost: %.2f, Comm %.2f, Size: %.2f, Stock: %s' %
                         (order.ref,
                          order.executed.price,
                          order.executed.value,
                          order.executed.comm,
                          order.executed.size,
                          order.data._name))

    # 构建交易函数，策略交易的主体
    def next(self):
        # 该操作是backtrader时间序列处理的核心方法之一，确保策略能准确感知回测过程中的时间维度变化。使用时需确保数据源已正确加载时间字段，且格式符合backtrader的解析要求
        # 获取当前的回测时间点
        dt = self.datas[0].datetime.date(0)
        # 判断当前回测时间是否为调仓日
        if dt in self.trade_dates:
            print("----{} 为调仓日------".format(dt))
            # 在调仓前，取消之前所有未成交也未到期的订单
            if len(self.order_list) > 0:
                for od in self.order_list:
                    self.cancel(od)
                # 重置订单列表
                self.order_list = []
            # 根据调仓日，提取最新的持仓列表
            buy_stocks_data = self.buy_stock.query(f"trade_date='{dt}'")
            long_list = buy_stocks_data['sec_code'].unique().tolist()
            print('持仓列表:', long_list)
            # 筛选要卖出的股票
            # 实际持仓列表和历史预期持仓列表取差集，得到要卖出的股票
            sell_stocks = []
            for i in self.buy_stock_pre:
                if i not in long_list:
                    sell_stocks.append(i)
            print('平仓列表:', sell_stocks)
            if len(sell_stocks) > 0:
                print('执行平仓操作')
                for stock in sell_stocks:
                    # 根据股票名称获取股票数据
                    # 由于  cerebro.adddata(feeds_pandas_data, name=stock) 使用股票名称作为数据名称，所以可以这里可以通过 self.getdatabyname(stock) 获取股票数据
                    stock_data = self.getdatabyname(stock)
                    # 判断实际仓位是否大于0
                    if self.getposition(stock_data) > 0:
                        # 增加平仓订单
                        sell_order = self.close(data=stock_data)
                        self.order_list.append(sell_order)
            # 买入此次要调仓的股票，多退少补原则
            print('----------买入要调仓的股票-------------')
            for stock in long_list:
                # 获取当前持仓权重
                stock_weight = buy_stocks_data.query(f"sec_code='{stock}'")['weight'].iloc[0]
                # 获取股票数据
                stock_data = self.getdatabyname(stock)
                # 计算订单目标比例，为避免极端场景出现，预留5%的现金仓位
                buy_order = self.order_target_percent(data=stock_data, target=stock_weight * 0.95)
                self.order_list.append(buy_order)
            # 保留本次调仓的所有股票 等价于 最新持有的股票
            self.buy_stock_pre = long_list

    def __init__(self) -> None:  # 定义自定义策略类需要的属性
        # 保留调仓列表
        self.buy_stock = trade_info
        # 读取调仓日期，每月的最后一个交易日
        # 回测时，会在这一天下单，然后在下一个交易日，以开盘价买入
        self.trade_dates = pd.to_datetime(self.buy_stock['trade_date'].unique()).tolist()
        # 记录订单，方便调仓日对未完成订单做处理
        self.order_list = []
        # 记录上一期持仓
        self.buy_stock_pre = []


# 将策略添加到cerebro中
cerebro.addstrategy(MyStrategy)

# 打印初始化资金
print('start portfolio value: %.2f' % cerebro.broker.getvalue())
# 启动回测
result = cerebro.run()
# 获取回测结果
strat = result[0]
# 返回日度收益率序列
daily_return = pd.Series(strat.analyzers.pnl.get_analysis())
# 打印评价指标
print("--------------- AnnualReturn -----------------")
print(strat.analyzers._AnnualReturn.get_analysis())
print("--------------- SharpeRatio -----------------")
print(strat.analyzers._SharpeRatio.get_analysis())
print("--------------- DrawDown -----------------")
print(strat.analyzers._DrawDown.get_analysis())
# 打印回测完成后的资金
print('final portfolio value: %.2f' % cerebro.broker.getvalue())
