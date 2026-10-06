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
    """转移矩阵 P → 稳态分布 π（P.T 左特征向量，迭代归一）。"""
    if P is None:
        return None
    pi = np.full(ZONES, 1.0 / ZONES)
    for _ in range(max_iter):
        pi_new = pi @ P
        if np.max(np.abs(pi_new - pi)) < tol:
            return pi_new
        pi = pi_new
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
