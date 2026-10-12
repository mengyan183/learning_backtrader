# -*- coding: utf-8 -*-
"""档位转移马尔可夫矩阵（数学模型落地 1/4）。

输入：features.csv 有效行的 zone 序列（0 极恐 ~ 4 极贪）。
输出：5×5 转移概率矩阵 P、稳态分布、自转移强度（状态延续概率）、
      当前 zone 的未来 N 日最可能档位分布。
用途：量化"连续下跌"概率、档位惯性；为 H 假说提供状态转移证据。

纯 numpy，无外部依赖。
"""
import numpy as np

ZONES = 5


def transition_matrix(zones):
    """zone 序列 → 5×5 转移计数归一化矩阵 P[i,j] = P(i→j)。"""
    zones = np.asarray(zones, dtype=int)
    n = len(zones)
    if n < 2:
        return None
    P = np.zeros((ZONES, ZONES))
    for t in range(n - 1):
        i, j = zones[t], zones[t + 1]
        if 0 <= i < ZONES and 0 <= j < ZONES:
            P[i, j] += 1
    row_sums = P.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        P = np.divide(P, row_sums, out=np.zeros_like(P), where=row_sums > 0)
    return P


def steady_state(P, max_iter=5000, tol=1e-10):
    """转移矩阵 P → 稳态分布 π（P.T 左特征向量，迭代归一）。

    **零行（无出边）按自环处理**（WT-23，2026-10-12）：`transition_matrix`
    对从未出现过的档位留下全 0 行。若直接迭代 `pi @ P`，落进这些行的概率
    质量会被**漏掉** ⇒ 返回向量 sum < 1（实测 `[0,0,1,1,2,2,2,1,0]` → 0.6、
    `P=zeros` → 全 0），**不是概率分布**；下游 `scripts/model_report.py`
    直接用它选"长期稳态最可能档位"⇒ **结论失真**。

    语义上「无出边」= 进去就出不来 ⇒ 补成自环 `P[i,i]=1` 是唯一保持概率
    守恒的解释（也是马尔可夫链吸收态的标准处理）。

    返回前统一归一，并断言 sum≈1 —— 调用方一律假定这是概率分布。
    """
    if P is None:
        return None
    Pn = np.asarray(P, dtype=float).copy()
    zero_rows = Pn.sum(axis=1) <= 0.0
    if zero_rows.any():
        Pn[zero_rows, :] = 0.0
        Pn[zero_rows, zero_rows] = 1.0
    pi = np.full(ZONES, 1.0 / ZONES)
    for _ in range(max_iter):
        pi_new = pi @ Pn
        if np.max(np.abs(pi_new - pi)) < tol:
            pi = pi_new
            break
        pi = pi_new
    total = float(pi.sum())
    if not np.isfinite(total) or total <= 0.0:
        pi = np.full(ZONES, 1.0 / ZONES)
    else:
        pi = pi / total
    assert abs(float(pi.sum()) - 1.0) < 1e-6, "steady_state 必须返回概率分布"
    return pi


def persistence(P):
    """自转移强度：P 对角线均值（档位平均惯性）。"""
    if P is None:
        return None
    return float(np.mean(np.diag(P)))


def forward_dist(P, start_zone, steps=5):
    """从 start_zone 出发，steps 步后的档位分布（行向量 × P^steps）。"""
    if P is None:
        return None
    d = np.zeros(ZONES)
    d[start_zone] = 1.0
    for _ in range(steps):
        d = d @ P
    return d


def analyze(zones, start_zone=None, horizons=(1, 5, 10)):
    """汇总：矩阵 + 稳态 + 惯性 + 前瞻分布。"""
    P = transition_matrix(zones)
    out = {
        "matrix": P.tolist() if P is not None else None,
        "steady_state": (steady_state(P).tolist() if P is not None else None),
        "persistence": persistence(P),
    }
    if start_zone is not None and P is not None:
        out["horizons"] = {}
        for h in horizons:
            d = forward_dist(P, int(start_zone), h)
            out["horizons"][h] = {"most_likely": int(np.argmax(d)),
                                  "prob": round(float(np.max(d)), 4),
                                  "dist": [round(x, 4) for x in d]}
    return out
