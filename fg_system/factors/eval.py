"""因子检验核心：滚动 IC / ICIR / 前瞻衰减（E4 因子引擎地基）

口径：
- 信号为日频序列（如系统 fg_index）；目标为未来 N 日收益（如 SPY）
- IC = 信号与目标收益的相关性（默认 Spearman，对单调关系稳健）
- ICIR = IC 均值 / IC 标准差（稳健性度量）；正值比 = IC>0 占比
- 前瞻收益必须严格滞后于信号（信号日期 t 对 t+1..t+N 收益），无前视偏差

用法（模块）：
    from fg_system.factors.eval import evaluate, rolling_ic, icir
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def forward_returns(close: pd.Series, horizons=(5, 10, 20, 40)) -> pd.DataFrame:
    """close(index=date) -> DataFrame(date × horizon)，列 fwd_{h} 为未来 h 交易日收益。"""
    out = pd.DataFrame(index=close.index)
    for h in horizons:
        out[f"fwd_{h}"] = close.shift(-h) / close - 1.0
    return out


def rolling_ic(signal: pd.Series, target: pd.Series, window: int = 60,
               method: str = "spearman") -> pd.Series:
    """信号与目标收益的滚动相关性，每交易日一个 IC 值（对齐去重后滚动）。

    Spearman = 对 rank 后的 Pearson 滚动相关（兼容无 method 参数的旧 pandas）。
    """
    df = pd.concat([signal.rename("sig"), target.rename("tgt")], axis=1).dropna()
    if len(df) < window + 2:
        return pd.Series(dtype=float)
    if method == "spearman":
        a, b = df["sig"].rank(), df["tgt"].rank()
    else:
        a, b = df["sig"], df["tgt"]
    return a.rolling(window).corr(b)


def _overlap(window: int, horizon: int) -> int:
    """滚动窗口与前瞻期的**重叠倍数** ✓（相邻 IC 值共享多少个观测）。"""
    return max(1, int(math.ceil(float(window) / max(1, int(horizon)))))


def icir(ic_series: pd.Series, overlap: int = 1) -> dict | None:
    """由 IC 序列计算汇总统计（先清除 ±inf——离散信号滚动相关会产生 inf，混入会污染均值）。

    🔴 2026-11-20（第 12.48 条）：**`overlap` 参数折算 ICIR** ✗
       滚动 IC 用 `window=60` + 前瞻 `horizon=20` ⇒ 相邻 IC 值**共享 40 个观测**
       ⇒ IC 序列高度自相关 ⇒ `ic.std()` 被系统性**低估** ⇒ ICIR 被放大 ✗
       实测全窗 ICIR −1.16 / 近窗 −1.95 都是放大后的值 ✗

       有效样本 ≈ `n / overlap` ⇒ 按 `1/sqrt(overlap)` 折算标准差口径 ✓
       `overlap=3` 时系数 ≈ **0.577**（ICIR 缩到原来的 57.7%）

    ⚠️ `ic_mean` / `ic_positive_ratio` / `n` **不折算** —— 均值本身无系统性偏差 ✓
    ⚠️ 同时返回 `icir_raw`，便于与历史报告对照 ✓
    """
    ic = ic_series.replace([np.inf, -np.inf], np.nan).dropna()
    if len(ic) == 0:
        return None
    std = float(ic.std())
    raw = float(ic.mean() / std) if std > 0 else 0.0
    ov = max(1, int(overlap or 1))
    return {
        "ic_mean": float(ic.mean()),
        "ic_std": std,
        "icir": raw / math.sqrt(ov),
        "icir_raw": raw,
        "overlap": ov,
        "ic_positive_ratio": float((ic > 0).mean()),
        "n": int(len(ic)),
    }


def evaluate(signal: pd.Series, close: pd.Series, horizons=(5, 10, 20, 40),
             window: int = 60) -> dict:
    """一次完整评估：{horizon: {"stats": dict, "ic": Series}}。"""
    fwd = forward_returns(close, horizons)
    result = {}
    for h in horizons:
        ic = rolling_ic(signal, fwd[f"fwd_{h}"], window=window)
        ov = _overlap(window, h)          # 第 12.48 条：重叠倍数随结果带出 ✓
        result[h] = {"stats": icir(ic, overlap=ov), "ic": ic, "overlap": ov}
    return result


def window_stats(eval_result: dict, horizon: int, recent: int = 120) -> dict:
    """对指定 horizon 的滚动 IC 再切近窗统计（用于漂移检测）。

    ⚠️ `overlap` 从 `evaluate()` 的结果里取 ✓ —— 近窗和全窗必须用**同一个**
       折算系数，否则两者不可比 ✗（第 12.48 条）
    """
    ic = eval_result[horizon]["ic"].dropna()
    if len(ic) == 0:
        return {"stats": None, "recent_stats": None}
    ov = int(eval_result[horizon].get("overlap", 1) or 1)
    recent_ic = ic.iloc[-recent:] if len(ic) >= recent else ic
    return {"stats": icir(ic, overlap=ov),
            "recent_stats": icir(recent_ic, overlap=ov)}
