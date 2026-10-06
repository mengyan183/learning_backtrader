# -*- coding: utf-8 -*-
"""极值理论 EVT（GPD/POT）极端档位阈值校准（数学模型落地 3/4）。

用途：系统档位边界 [20,40,60,80] 目前为硬编码。本模块用 fg_index 历史
尾部（POT：Peaks Over Threshold）拟合广义帕累托分布 GPD(ξ,σ)，
反推各重现水平对应的指数值，检验"20=极恐 / 80=极贪"是否与数据尾部一致。

实现：GPD 参数用概率加权矩（PWM）闭式估计（无 scipy 依赖），
重现水平 z_q = u + σ/ξ * ((q·N/Nu)^(-ξ) - 1)，q 为极值概率。

纪律：输出为"建议阈值"，不自动改 config；人工审批后才可动边界。
"""
import numpy as np
import pandas as pd


def _gpd_pwm(excess):
    """GPD 概率加权矩估计：excess（超阈值量, >0）→ (shape ξ, scale σ)。"""
    x = np.sort(np.asarray(excess, dtype=float))
    n = len(x)
    if n < 10:
        return None
    # PWM 一阶
    w = np.arange(1, n + 1) / (n + 1)
    b0 = x.mean()
    b1 = (w * x).mean()
    if b0 <= 0:
        return None
    r = b1 / b0
    shape = (b0 - 2 * b1) / (b0 - b1)  # ξ
    scale = (2 * b0 * b1) / (b0 - b1)  # σ 近似（标准 GPD PWM 公式）
    if scale <= 0 or not np.isfinite(shape):
        return None
    return shape, scale


def pot_analyze(values, tail="lower", u_quantile=0.10, returns=(1, 5, 20)):
    """POT 分析。
    values: 0-100 指数序列；tail='lower' 极恐（用 -x 转上尾）或 'upper' 极贪。
    u_quantile: 阈值分位（默认 10% 尾部）。
    returns: 重现水平（年）。
    返回: 建议阈值（1 年重现 ≈ 该尾部概率下可能见到的极端值）+ 现状对比。
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 120:
        return {"error": "样本不足"}
    if tail == "lower":
        z = -x  # 转上尾
        flip = True
    else:
        z = x
        flip = False
    u = np.quantile(z, 1 - u_quantile)
    excess = z[z > u] - u
    fit = _gpd_pwm(excess)
    if fit is None:
        return {"error": "GPD 拟合失败"}
    shape, scale = fit
    Nu = len(excess)
    # 年重现水平（约 250 交易日/年）
    out = {"tail": tail, "threshold_quantile": u_quantile,
           "u_raw": round(float(u), 2) if flip else round(float(u), 2),
           "shape_xi": round(float(shape), 4),
           "scale_sigma": round(float(scale), 4),
           "n_excess": int(Nu), "levels": {}}
    for yr in returns:
        q = 1.0 / (250.0 * yr)  # 该重现期对应的极值概率
        if abs(shape) < 1e-9:
            zq = u + scale * np.log(q * n / Nu)
        else:
            zq = u + scale / shape * (((q * n / Nu) ** (-shape)) - 1)
        val = -zq if flip else zq
        val = min(max(val, 0.0), 100.0)
        out["levels"][yr] = round(float(val), 1)
    # 与现状边界对比：建议值比现状更远离 50（更极端）→ 现状边界触发过频 → 建议收紧
    cur = 20.0 if tail == "lower" else 80.0
    lvl1 = out["levels"][1]
    out["current_boundary"] = cur
    out["suggested_boundary"] = lvl1
    if tail == "lower":
        too_frequent = lvl1 < cur
    else:
        too_frequent = lvl1 > cur
    out["verdict"] = (
        f"现状边界触发偏频（真实极端尾部更远）：建议收紧边界至 {lvl1}"
        if too_frequent else
        "现状边界与数据尾部一致或偏保守"
    )
    return out


def analyze(features_csv):
    """对 features.csv 有效 fg_index 做下尾+上尾 POT 分析。"""
    f = pd.read_csv(features_csv, parse_dates=["date"])
    vals = f.dropna(subset=["fg_index"])["fg_index"].to_numpy(dtype=float)
    lower = pot_analyze(vals, tail="lower")
    upper = pot_analyze(vals, tail="upper")
    return {"lower": lower, "upper": upper,
            "n": int(len(vals)),
            "date_range": [str(f["date"].min().date()), str(f["date"].max().date())]}
