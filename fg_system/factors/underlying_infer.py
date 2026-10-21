# -*- coding: utf-8 -*-
"""杠杆 ETF 的**底层自动推断**（β 回归）。

【为什么需要】
`config.SIGNAL_UNDERLYING_MAP` 是**手工登记**的 ✓ —— 每加一只新标的都要改代码 ✗，
对「查一个标的」这种动作**不可接受** ✗（2026-10-21 用户反馈 ✗）。

【做法】
对目标标的与**候选池**（`fg_system/data/underlying_candidates.csv`，~48 个常用
无杠杆 ETF ✓）逐一做 OLS 回归：

    r_target = α + β × r_candidate

选 **R² 最高**且 **β 落在合理区间**（2x/3x 杠杆 ✓）的候选 ✓。

【为什么不违反「禁用杠杆 ETF 价格」铁律】
杠杆 ETF 的价格**只用于推断映射** ✓ —— 推断出底层之后，**算分仍走底层** ✓。
（铁律的本意是「不用杠杆价格算情绪分」✗，因为波动率衰减会被误读成恐惧 ✓。）

【已知局限（必须在输出里透出 ✗）】
- **只能验证，不能发现** ✗：若真底层不在候选池里 ⇒ 一定失败 ✓（会返回空 ✓）。
- 短样本（< 60 日）⇒ R² 不稳 ✓ ⇒ 拒绝 ✓。
- 反向标的（如 `SQQQ`）⇒ **β ≈ −3** ✓ ⇒ 由 `beta < 0` 识别 ✓，
  但**分数方向**要调用方处理 ✗（本模块只报 `direction` ✓，不改分 ✗）。
"""
import os

import numpy as np
import pandas as pd

#: 候选池路径（**随代码入库** ✓ —— 不是 `Data/` 下的运行时数据 ✓）
CANDIDATES_CSV = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "data", "underlying_candidates.csv")

#: 至少多少个**重叠交易日**才可信 ✓（少于则 R² 无意义 ✗）
MIN_OVERLAP = 60

#: 接受推断的最低 R² ✓（0.90 已很严 ✓：实测 TQQQ/QQQ ≈ 0.99 ✓）
MIN_R2 = 0.90

#: 杠杆倍数区间 ✓ —— 2x / 3x / 反向（负）✓
BETA_RANGES = ((-3.5, -1.5, "反向"), (1.5, 2.5, "2x"), (2.5, 3.5, "3x"),
               (0.5, 1.5, "1x"))


def load_candidates(path=None):
    """读候选池 ⇒ `{symbol: name}` ✓（顺序稳定 ✓）。"""
    p = path or CANDIDATES_CSV
    if not os.path.exists(p):
        return {}
    d = pd.read_csv(p, dtype={"symbol": str})
    return {str(r["symbol"]).strip(): str(r.get("name", "")).strip()
            for _, r in d.iterrows() if str(r["symbol"]).strip()}


def _returns(close):
    """日简单收益率 ✓（去掉首行 NaN ✓）。"""
    s = pd.Series(close).astype(float).sort_index()
    return s.pct_change().dropna()


def _beta_range(beta):
    for lo, hi, label in BETA_RANGES:
        if lo <= beta <= hi:
            return label
    return None


def infer(target_close, candidates):
    """推断底层 ✓。返回**按 R² 降序**的列表（可能为空 ✗）。

    :param target_close: 目标标的的收盘价 Series（索引为日期 ✓）
    :param candidates:   `{symbol: 收盘价 Series}` ✓
    :returns: `[{symbol, beta, r2, n, direction, leverage}, ...]` ✓
              其中 `direction` ∈ `正向` / `反向` ✓、`leverage` ∈ `2x`/`3x`/… ✓
    """
    rt = _returns(target_close)
    if rt.empty:
        return []
    out = []
    for sym, close in candidates.items():
        rc = _returns(close)
        if rc.empty:
            continue
        # 按**日期交集**对齐 ✓（不能按位置 ✗）
        joined = pd.concat([rt.rename("t"), rc.rename("c")], axis=1,
                           join="inner").dropna()
        if len(joined) < MIN_OVERLAP:
            continue
        x = joined["c"].to_numpy()
        y = joined["t"].to_numpy()
        var = float(np.var(x))
        if var <= 0:                      # 候选无波动 ⇒ 无法回归 ✗
            continue
        beta = float(np.cov(x, y, ddof=0)[0, 1] / var)
        alpha = float(y.mean() - beta * x.mean())
        resid = y - (alpha + beta * x)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
        lev = _beta_range(beta)
        out.append({"symbol": sym, "beta": round(beta, 3),
                    "r2": round(r2, 4), "n": int(len(joined)),
                    "direction": "反向" if beta < 0 else "正向",
                    "leverage": lev})
    out.sort(key=lambda d: d["r2"], reverse=True)
    return out


def pick(target_close, candidates, min_r2=MIN_R2):
    """从 `infer()` 结果里挑**唯一可信**的底层 ✓；没有 ⇒ `None` ✗。

    判据（缺一不可 ✗）：① `r2 >= min_r2` ✓；② `leverage` 落在已知区间 ✓
    （1x/2x/3x/反向 ✓ —— 用来排除「碰巧相关」的噪声 ✗）。
    """
    for cand in infer(target_close, candidates):
        if cand["r2"] >= min_r2 and cand["leverage"]:
            return cand
    return None
