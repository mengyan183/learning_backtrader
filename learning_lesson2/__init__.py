# -*- coding: utf-8 -*-

'''
bt 自定义策略时，使用的self.datas含义介绍

self.datas 对应的是 cerebro.feed的数据，datas可以认为是一个集合数据，每个索引位置对应的就是每次feed进来的数据

'''

# 导入backtrader
import datetime

import backtrader as bt
import pandas as pd

# 实例化 cerebro
from backtrader import Order

cerebro = bt.Cerebro()
'''
bt数据模块datafeeds
常用的数据导入包含csv和dataframe

默认导入方式：存在以下两步
1：调用feeds模块加载数据
2：将加载到的数据传递给cerebro

# 读取和导入 CSV 文件
data = bt.feeds.GenericCSVData(dataname='filename.csv', ...)
cerebro.adddata(data, name='XXX')
# 读取和导入 dataframe 数据框 - 方式1
data = bt.feeds.PandasData(dataname=df, ...)
cerebro.adddata(data, name='XXX')
# 读取和导入 dataframe 数据框 - 方式2
data = bt.feeds.PandasDirectData(dataname=df, ...)
cerebro.adddata(data, name='XXX')

'''
from_csv_data = bt.feeds.GenericCSVData(
    dataname='../Data/tqqq_history.csv'  # 数据源可以是 csv文件路径，也可以是 dataframe
    , fromdate=datetime.datetime(2016, 1, 13)  # 加载数据开始日期
    , todate=datetime.datetime(2026, 1, 12)  # 加载数据结束日期
    , nullvalue=0.0  # 数据为null时，填充默认值0.0
    , dtformat='%m/%d/%Y'  # 日期解析格式
    # 数据指标对应的 csv 列索引位置,索引从0开始,配置bt需要的字段
    , datetime=0  # 开盘日期
    , open=3  # 开盘价
    , high=4  # 最高价
    , low=5  # 最低价
    , close=1  # 收盘价
    , volume=2  # 成交量
    , openinterest=-1  # 取值为-1表示这个指标不存在
)
cerebro.adddata(from_csv_data, "tqqq_csv_data")


# 自定义读取函数加载csv数据
# 自定义读取函数的优势在于相同csv格式的数据，只需要调用该规则就可以加载数据，不需要每次重复编写规则
class My_CSVData(bt.feeds.GenericCSVData):
    params = (
        ("fromdate", datetime.datetime(2016, 1, 13))
        , ("todate", datetime.datetime(2026, 1, 12))
        , ("nullvalue", 0.0)
        , ("dtformat", '%m/%d/%Y')
        , ("datetime", 0)
        , ("open", 3)
        , ("high", 4)
        , ("low", 5)
        , ("close", 1)
        , ("volume", 2)
        , ("openinterest", -1)
    )


cerebro.adddata(My_CSVData(dataname='../Data/tqqq_history.csv'), "custom_read_tqqq_csv_data")

# 导入数据
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

    # 为原始数据新增字段以及值
    merge_data['pe'] = 2
    merge_data['pb'] = 3
    expend_daily_price = PandasData_more(dataname=merge_data, fromdate=datetime.datetime(2019, 1, 2),
                                         todate=datetime.datetime(2021, 1, 28))
    cerebro.adddata(data=expend_daily_price, name=stock)

    # 生成要送给cerebros的数据
    # feeds_pandas_data = bt.feeds.PandasData(dataname=merge_data, fromdate=datetime.datetime(2019, 1, 2),
    #                                         todate=datetime.datetime(2021, 1, 28))
    # 将数据送给cerebro,数据名称和股票名称对齐
    # cerebro.adddata(feeds_pandas_data, name=stock)
    # print(f"{stock} done")

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
        print("print lines[6] datetime")
        print(bt.num2date(self.datas[0].lines[6][0]))

        '''
        lines在next中随着回测点循环运行动态变化
        ，因此lines数据点的索引位置也是随着next的运行动态变化的，其中backwards代表的是已经回测过、处理过的数据，forwards代表的是还未回测的那部分
        
        不管是在next中还是init中，需要谨记line的索引特点，0表示最新数据位置，-n表示回首过去，n表示未来
        '''

        print(f"------------- next 的第{self.count + 1}次循环 --------------")
        print("当前时点（今日）：", 'datetime', self.data1.lines.datetime.date(0), 'close', self.data1.lines.close[0])
        print("往前推1天（昨日）：", 'datetime', self.data1.lines.datetime.date(-1), 'close', self.data1.lines.close[-1])
        print("往前推2天（前日）", 'datetime', self.data1.lines.datetime.date(-2), 'close', self.data1.lines.close[-2])
        print("前日、昨日、今日的收盘价：", self.data1.lines.close.get(ago=0, size=3))
        if len(self.data1.lines.datetime) > 0 & len(self.data1.lines.close()) > 0:
            print("往后推1天（明日）：", 'datetime', self.data1.lines.datetime.date(1), 'close', self.data1.lines.close[1])
        if len(self.data1.lines.datetime) > 1 & len(self.data1.lines.close()) > 1:
            print("往后推2天（明后日）", 'datetime', self.data1.lines.datetime.date(2), 'close', self.data1.lines.close[2])
        print("已处理的数据点：", len(self.data1))
        print("line的总长度：", self.data0.buflen())
        self.count += 1

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
        # 打印 PandasData_more 结构数据字段（包含pb、pe）
        print("self.data2.lines.getlinealiases()")
        print(self.data2.lines.getlinealiases())
        # 学习 self.datas api的用法
        print("self.datas")
        print(self.datas)
        print("self.data")
        # 获取第一个feed的数据集
        print(self.data._name, self.data)
        print("self.datas[0]")
        # 获取第一个feed的数据集 data[0]
        print(self.datas[0]._name, self.datas[0])
        print("self.data0")
        # 获取第一个feed的数据集 data0
        print(self.data0._name, self.data0)

        print("self.datas[-1]")
        # 获取最后一个导入的数据集
        print(self.datas[-1]._name, self.datas[-1])

        # 获取第一个数据集的close列
        print("self.data.lines.close")
        print(self.data.lines.close)
        # 不支持该操作
        # print("self.data.lines_close")
        # print(self.data.lines_close)
        print("self.data_close")
        print(self.data_close)
        print("self.data.close")
        print(self.data.close)

        # 打印策略本身的字段定义
        print("self.lines.getlinealiases()")
        print(self.lines.getlinealiases())
        # 打印第一个数据集的字段定义
        print("self.datas[0].lines.getlinealiases()")
        print(self.datas[0].lines.getlinealiases())

        print("SimpleMovingAverage")
        # 获取20日均线
        self.sma = bt.indicators.SimpleMovingAverage(self.datas[0].close, period=20)

        # 获取indicator的lines
        print("indicator lines aliases")
        print(self.sma.lines.getlinealiases())

        print("indicator lines")
        print(self.sma.lines)

        print("indicator lines[0]")
        print(self.sma.lines[0])

        # 记录next循环次数
        self.count = 0

        '''
        line表示时间序列中的单个数据列
        特殊的索引机制，0表示最新一条数据，支持-n 前n个值，支持n 后n个值
        
        lines是line的集合
        动态增长的特性，运行时通过next函数动态扩展
        
        len获取的是已处理的数据点数量
        buflen获得的是加载的数据总量
        '''
        print("init 索引数据查询")
        print("索引 self data1 数据集")
        # 索引0代表的是最晚导入的一条数据
        # 索引1代表的是最早插入的一条数据
        print("0 索引：", 'datetime', self.data1.lines.datetime.date(0), 'close', self.data1.lines.close[0])
        print("-1 索引：", 'datetime', self.data1.lines.datetime.date(-1), 'close', self.data1.lines.close[-1])
        print("-2 索引", 'datetime', self.data1.lines.datetime.date(-2), 'close', self.data1.lines.close[-2])
        print("1 索引：", 'datetime', self.data1.lines.datetime.date(1), 'close', self.data1.lines.close[1])
        print("2 索引", 'datetime', self.data1.lines.datetime.date(2), 'close', self.data1.lines.close[2])
        # get获取切片数据时，从0开始往前取数据不会返回任何数据
        print("从 0 开始往前取3天的收盘价：", self.data1.lines.close.get(ago=0, size=3))
        print("从-1开始往前取3天的收盘价：", self.data1.lines.close.get(ago=-1, size=3))
        print("从-2开始往前取3天的收盘价：", self.data1.lines.close.get(ago=-2, size=3))
        print("line的总长度：", self.data1.buflen())

        '''
        行是bars
        bt中没有bars的概念，bt的回测实际就是就是按照时间先后顺序依次循环遍历各个带有历史行情信息的bar，检验策略在历史行情上的表现
        '''

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
