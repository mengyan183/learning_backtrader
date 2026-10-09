# -*- coding: utf-8 -*-
import tushare as ts

with open('../Data/tstoken', 'r', encoding='utf-8') as file:
    token = file.read()  # 返回完整字符串

ts.set_token(token)
pro = ts.pro_api(token)
data1 = pro.query('stock_basic', exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
print(data1)


data = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
print(data)

df = ts.pro_bar(ts_code='000001.SZ', adj='qfq', start_date='20180101', end_date='20181011')
print(df)