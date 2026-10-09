# 学习backtrader

## lesson1初识

### backtrader介绍

官网地址：[Welcome - Backtrader](https://www.backtrader.com/)



![image-20260109102129120](C:\Users\260023\AppData\Roaming\Typora\typora-user-images\image-20260109102129120.png)

![image-20260109102316199](C:\Users\260023\AppData\Roaming\Typora\typora-user-images\image-20260109102316199.png)

### 流程定义

第一步：构建策略

1：确定策略潜在的可调参数

2：计算策略中用于生成交易信号的指标

3：打印交易信息

4：编写买入、卖出交易逻辑

第二步：实例化策略化引擎cerebro，由cerebro驱动回测

1：使用datafeeds加载数据，传递给cerebro

2：将构建的策略传递给cerebro

3：添加策略分析指标和监测

4：运行cerebro.run进行回测

5：回测完成后使用cerebro.plot展示回测结果

![image-20260109112054937](C:\Users\260023\AppData\Roaming\Typora\typora-user-images\image-20260109112054937.png)

### 本地开发环境要求（windows环境示例）

`

1：python3.10版本

2：安装依赖：

pip.exe install -i https://mirrors.aliyun.com/pypi/simple/ --proxy http://10.1.82.22:3128 backtrader[plotting]
pip.exe install -i https://mirrors.aliyun.com/pypi/simple/ --proxy http://10.1.82.22:3128 pandas
pip.exe install -i https://mirrors.aliyun.com/pypi/simple/ --proxy http://10.1.82.22:3128 tushare --upgrade
python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ --proxy http://10.1.82.22:3128 pip --upgrade

3：开发工具：pycharm社区版

`

