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


def icir(ic_series: pd.Series) -> dict | None:
    """由 IC 序列计算汇总统计。"""
    ic = ic_series.dropna()
    if len(ic) == 0:
        return None
    std = float(ic.std())
    return {
        "ic_mean": float(ic.mean()),
        "ic_std": std,
        "icir": float(ic.mean() / std) if std > 0 else 0.0,
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
        result[h] = {"stats": icir(ic), "ic": ic}
    return result


def window_stats(eval_result: dict, horizon: int, recent: int = 120) -> dict:
    """对指定 horizon 的滚动 IC 再切近窗统计（用于漂移检测）。"""
    ic = eval_result[horizon]["ic"].dropna()
    if len(ic) == 0:
        return {"stats": None, "recent_stats": None}
    recent_ic = ic.iloc[-recent:] if len(ic) >= recent else ic
    return {"stats": icir(ic), "recent_stats": icir(recent_ic)}
