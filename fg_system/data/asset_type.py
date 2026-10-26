# -*- coding: utf-8 -*-
"""标的类型判定（`stock` / `option` ✓）—— 防止期权混进股票口径 ✗。

【为什么需要这个模块】

`Data/trade_log` 里混了 **17 笔期权** ✗（`buy_back 9` + `sell_short 8` ✓），
带来三层问题 ✗：

1. **混表** ✗：胜率 / 平均持仓天数被期权拉偏 ✗（期权周期短、杠杆高 ✓）。
2. **乘数** ✗（最严重 ✓）：期权 **1 张 = 100 股** ✗ ⇒
   `qty × (price − cost)` 直接套用会**低估 100 倍** ✗，而且**不报错** ✗。
3. **语义** ✗：`buy_back` / `sell_short` 是**平仓** ✗，当开仓统计会把方向算反 ✗。

【判定规则】

富途期权代码形如 `US.AAPL250117C150000` ✓
= `市场.标的` + `YYMMDD` + `C/P` + `行权价×1000` ✓
⇒ 正则 `\\d{6}[CP]\\d+$` 即可识别 ✓ —— 股票代码**不会**以「6 位数字 + C/P + 数字」结尾 ✗。

【缺列时不报错 ✗】

`classify_df()` 在**没有 `symbol` 列**时全判 `stock` ✓ ——
宁可当成股票也不抛错 ✗，避免把既有链路拖垮 ✗。
"""

import re

STOCK = "stock"
OPTION = "option"

#: 富途期权代码：`US.AAPL250117C150000` ✓（`C` = call / `P` = put ✓）
_OPT_RE = re.compile(r"\d{6}[CP]\d+$", re.IGNORECASE)


def classify(symbol):
    """单个标的 ⇒ `"stock"` 或 `"option"` ✓。"""
    s = str(symbol or "").strip()
    if not s:
        return STOCK
    return OPTION if _OPT_RE.search(s) else STOCK


def is_option(symbol):
    """是否期权 ✓。"""
    return classify(symbol) == OPTION


def classify_series(series):
    """对 `pandas.Series` 逐值分类 ✓（返回同长度 Series ✓）。"""
    return series.map(classify)


def classify_df(df, col="symbol"):
    """给 DataFrame 加（或覆盖）`asset_type` 列 ✓，**不修改入参** ✗。"""
    out = df.copy()
    if col not in out.columns:
        out["asset_type"] = STOCK
        return out
    out["asset_type"] = classify_series(out[col])
    return out
