# -*- coding: utf-8 -*-
"""C2 估值维度：ERP 股权风险溢价（2026-10-31 实现）。

【为什么用 ERP】
情绪因子测「当下恐慌」（put-call / VIX / FGI），信用因子测「融资条件」（BAA10Y），
**估值因子测「贵不贵」** —— 三者维度不同 ✓。

    ERP = 盈利收益率 − 无风险利率 = 1/PE − 10Y

ERP 高 = 股票相对债券便宜 = **贪婪**（该多配）✓

【🔴 核心纪律：月度 + available_date，禁止插值到日频】

PE / CAPE 是**月度**序列，且 **月末之后才发布** ✗。若按 `date` 对齐：

    2026-10-01 的 PE，实际 11 月才公布
    ⇒ 在 10-01 就「看到」了 11 月才有的数据 ⇒ IC 虚高 ✗（lookahead）

⇒ 本模块：

- 存 `available_date = date + 1 个月`（保守 ✓）
- 取数用 `merge_asof(direction="backward")` ✓
- **禁止** `reindex().ffill()` ✗ 和**插值** ✗ —— 插值会把月内阶梯磨成斜线、
  制造「月内分位平滑上升」的假信号 ✗

【10Y 用**月均**（2026-10-30 用户裁定）】
月度 PE 配「月末那天的 10Y」会引入**日内噪声**（月末恰是利率异动日时 ERP 被污染 ✗）
⇒ 两边都取「该月平均」✓

【分位窗口 **120 个月（10 年）**】
默认 `RANK_WINDOW=756`（3 年）对估值因子是错的 ✗ ——
月度 PE 在 756 交易日里只有 **36 个观测点**，既不够分辨率、也覆盖不了一轮估值周期 ✗。
估值因子的行业惯例就是 10 年（CAPE 本身就是 10 年平均）✓

【CAPE 只作「分歧标记」，不作主信号】
CAPE 用 10 年平均**实际**盈利 ⇒ 对盈利周期位置不敏感，
2020 疫情后 / 2023 AI 周期这种拐点会严重滞后 ✗。
⇒ 主信号用当期 PE；CAPE 只算 `|PE分位 − CAPE分位|`，
   超阈值时标记「当期盈利可能不可持续」✓（阈值**按实际分布定**，见 docs/erp-factor.md）

数据源：`Data/raw/sp500_pe.csv` / `sp500_cape.csv` / `fred_DGS10.csv`
（由 `scripts/fetch_pe_ratio.py` / `fetch_fred.py` 抓取 ✓）
"""
import os

import pandas as pd

from fg_system import config
from fg_system.factors.base import rolling_pct

#: 估值序列（月度，带 available_date ✓）
PE_FILE = "sp500_pe.csv"
CAPE_FILE = "sp500_cape.csv"
#: 10Y（日频，FRED 列名是 observation_date ✗ 不是 date）
DGS10_FILE = "fred_DGS10.csv"

#: 估值因子的分位窗口：10 年 ✓（**不用** config.RANK_WINDOW=756 ✗）
#: 🔴 单位是**行数（月）** ✗ —— 2520 是「交易日」口径，用在月度序列上会
#: 直接超过总行数 ⇒ 分位全 NaN ✗（2026-10-31 实测踩过这个坑 ✗）
ERP_WINDOW = 120
#: CAPE 分歧标记的**兜底阈值** ✓ —— 实测 P90 = **40.8**（2026-10-31）。
#: 🔴 `cape_flag()` 默认用 `div.quantile(0.90)` **动态**算 ✗ 不用这个常量 ✓；
#: 它只在「样本不足、算不出分位」时作兜底，以及给文档/报告一个参照值 ✓。
#: 为什么不是 25：实测分歧分布 P50=11.7 / P75=27.7 / P90=40.8 / P95=50.0，
#: 25 大约落在 **P70** ⇒ 会标记 **30% 的月份** ✗ 从「预警」退化成「常态」✗
CAPE_DIV_THRESHOLD = 40.8


def _raw_path(name):
    return os.path.join(config.DATA_DIR, "raw", name)


def load_monthly(path=None, value_col="pe"):
    """读月度估值 CSV ⇒ `DataFrame[date, <value_col>, available_date]` ✓。

    `available_date` 缺失 ⇒ **按 `date + 1 个月` 补齐** ✓（保守，不用 date 兜底 ✗）。
    """
    p = path or _raw_path(PE_FILE)
    if not os.path.exists(p):
        raise FileNotFoundError(
            "估值数据不存在：%s\n⇒ 先跑 `scripts/fetch_pe_ratio.py` ✓" % p)
    df = pd.read_csv(p, encoding="utf-8")
    if "date" not in df.columns:
        raise ValueError("估值数据缺 `date` 列 ✗：%s" % list(df.columns))
    if value_col not in df.columns:
        # 兼容列名就叫 value 的情况 ✓
        if "value" in df.columns:
            df = df.rename(columns={"value": value_col})
        else:
            raise ValueError("估值数据缺 `%s` 列 ✗：%s"
                             % (value_col, list(df.columns)))
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"], errors="coerce"),
        value_col: pd.to_numeric(df[value_col], errors="coerce"),
    })
    if "available_date" in df.columns:
        out["available_date"] = pd.to_datetime(df["available_date"],
                                               errors="coerce")
    out = out.dropna(subset=["date", value_col])
    # 缺 available_date ⇒ 保守补齐（**月末 + 1 个月**）✓
    # 🔴 绝不用 `date` 兜底 ✗ —— 那正是 lookahead 的来源 ✗
    if "available_date" not in out.columns:
        out["available_date"] = pd.NaT
    out["available_date"] = pd.to_datetime(out["available_date"],
                                           errors="coerce")
    miss = out["available_date"].isna()
    if miss.any():
        out.loc[miss, "available_date"] = (out.loc[miss, "date"]
                                           + pd.DateOffset(months=1))
    return out.sort_values("date").reset_index(drop=True)


def load_dgs10(path=None):
    """读 FRED 10Y ⇒ `DataFrame[date, value]` ✓（列名 `observation_date` ✗）。"""
    p = path or _raw_path(DGS10_FILE)
    if not os.path.exists(p):
        raise FileNotFoundError(
            "10Y 数据不存在：%s\n⇒ 先跑 `fetch_fred.py --series DGS10` ✓" % p)
    df = pd.read_csv(p, encoding="utf-8-sig")
    dcol = "observation_date" if "observation_date" in df.columns else "date"
    vcol = next((c for c in df.columns if c != dcol), None)
    if vcol is None:
        raise ValueError("10Y 数据只有一列 ✗：%s" % list(df.columns))
    out = pd.DataFrame({
        "date": pd.to_datetime(df[dcol], errors="coerce"),
        "value": pd.to_numeric(df[vcol], errors="coerce"),
    }).dropna()
    return out.sort_values("date").reset_index(drop=True)


def monthly_y10(dgs10):
    """日频 10Y ⇒ **月均** ✓（与月度 PE 同频；2026-10-30 用户裁定）。

    index = 每月 1 日（`resample("MS")`）✓
    """
    s = dgs10.set_index("date")["value"].sort_index()
    return s.resample("MS").mean().dropna()


def erp_monthly(pe=None, dgs10=None):
    """月度 ERP ✓ = `1/PE × 100 − 月均10Y`（单位都是 %）。

    返回 `DataFrame[date, pe, y10, erp, available_date]` ✓：
    `available_date` 取 **PE 的**（月末 + 1 个月，比 10Y 更晚 ⇒ 是真正的约束 ✓）。
    """
    pe = load_monthly(value_col="pe") if pe is None else pe
    dgs10 = load_dgs10() if dgs10 is None else dgs10

    p = pe.set_index("date").copy()
    p.index = p.index.to_period("M").to_timestamp()      # 归一到月首 ✓
    y10 = monthly_y10(dgs10)
    y10.index = y10.index.to_period("M").to_timestamp()

    out = p.join(y10.rename("y10"), how="inner")
    out["erp"] = 100.0 / out["pe"] - out["y10"]
    out = out.reset_index().rename(columns={"index": "date"})
    out = out.dropna(subset=["erp"])
    return out.sort_values("date").reset_index(drop=True)


def _align(df, target_index, value_col):
    """按 `available_date` 对齐到日频 ✓（只用 merge_asof，禁止 ffill ✗）。"""
    right = df[["available_date", value_col]].dropna().sort_values(
        "available_date").reset_index(drop=True)
    left = pd.DataFrame({"t": pd.to_datetime(pd.Index(target_index))}
                        ).sort_values("t").reset_index(drop=True)
    merged = pd.merge_asof(left, right, left_on="t",
                           right_on="available_date", direction="backward",
                           allow_exact_matches=True)
    return merged.set_index("t")[value_col]


def erp_pct(target_index=None, window=ERP_WINDOW, pe=None, dgs10=None):
    """ERP 的**滚动分位** ✓（0~1，高 = 便宜 = 贪婪）。

    窗口默认 `ERP_WINDOW=120`（10 年）✗ 不用 `config.RANK_WINDOW=756`。
    窗口不足处为 `NaN` ✓（不凑值 ✗）。
    """
    m = erp_monthly(pe=pe, dgs10=dgs10)
    pct = rolling_pct(m.set_index("available_date")["erp"].sort_index(), window)
    if target_index is None:
        return pct.rename("erp_pct")
    tmp = pct.reset_index()
    tmp.columns = ["available_date", "erp_pct"]
    return _align(tmp, target_index, "erp_pct")


def cape_divergence(target_index=None, window=ERP_WINDOW, pe=None,
                    cape=None, dgs10=None):
    """CAPE 与当期 PE 的**分位分歧** ✓（单位：百分点）。

    `|PE分位 − CAPE分位| × 100` —— 分歧大 ⇒ 当期盈利可能不可持续 ✓。
    只作**辅助标记**，不进主分数 ✗。
    """
    m = erp_monthly(pe=pe, dgs10=dgs10)
    pe_pct = rolling_pct(m.set_index("available_date")["pe"].sort_index(), window)

    cape = load_monthly(path=_raw_path(CAPE_FILE),
                        value_col="cape") if cape is None else cape
    cape_pct = rolling_pct(
        cape.set_index("available_date")["cape"].sort_index(), window)

    idx = pe_pct.index.union(cape_pct.index)
    div = (pe_pct.reindex(idx) - cape_pct.reindex(idx)).abs() * 100.0
    div = div.dropna().rename("cape_div")
    if target_index is None:
        return div
    tmp = div.reset_index()
    tmp.columns = ["available_date", "cape_div"]
    return _align(tmp, target_index, "cape_div")


def cape_flag(target_index=None, threshold=None, **kw):
    """分歧是否超阈值 ⇒ `Series[bool]` ✓（阈值默认取历史 **P90**）。

    🔴 2026-10-30 用户裁定：**阈值按实际分布定** ✗ 不写死数字 ✓
    （分歧幅度随盈利波动率变化：2010 年代小、2020-22 大 ✗）
    """
    div = cape_divergence(target_index=target_index, **kw)
    thr = (div.quantile(0.90) if threshold is None else float(threshold))
    return (div > thr).rename("cape_div_flag")
