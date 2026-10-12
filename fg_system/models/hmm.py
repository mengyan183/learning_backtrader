# -*- coding: utf-8 -*-
"""Gaussian 隐马尔可夫模型（数学模型落地 2/4，纯 numpy 实现）。

观测：features.csv 有效行的标准化因子矩阵（fg_index + vix + term + price
      + breadth，缺失行剔除；fed 列历史缺失太多暂不入观测）。
状态：K=3（恐惧 regime / 中性 regime / 贪婪 regime，按 fg_index 分位初始化）。
算法：Baum-Welch（EM：前向-后向 scaled）估计 π/A/μ/σ（对角协方差），
      Viterbi 解码得到每日最可能 regime 与"当前 regime"。

纪律：只读数据输出分析，不参与决策参数；与 markov.py 互为印证。
"""
import numpy as np
import pandas as pd

OBS_COLS = ["fg_index", "vix", "term", "price", "breadth"]


def _init_params(X, K, seed=0):
    """按 fg_index 分位初始化 + 抖动：状态 0=低(恐惧) → K-1=高(贪婪)。"""
    rng = np.random.default_rng(seed)
    T, D = X.shape
    fg = X[:, 0]
    qs = np.quantile(fg, np.linspace(0, 1, K + 1))
    pi = np.full(K, 1.0 / K)
    A = np.full((K, K), 0.8 / K)
    np.fill_diagonal(A, 0.8 + (1 - 0.8) / K)
    A = A / A.sum(axis=1, keepdims=True)
    mu, cov = np.zeros((K, D)), np.ones((K, D))
    for k in range(K):
        lo, hi = qs[k] - 1e-9, qs[k + 1] + 1e-9
        idx = np.where((fg >= lo) & (fg <= hi))[0]
        idx = idx if len(idx) else np.array([0])
        mu[k] = X[idx].mean(axis=0)
        cov[k] = X[idx].var(axis=0) + 1e-6
        mu[k] += rng.normal(0, 0.05, D)  # 抖动避免对称退化
    return pi, A, mu, cov


def _log_gauss(X, mu, cov):
    """对角高斯 log 概率：返回 T×K。"""
    T, D = X.shape
    K = mu.shape[0]
    lg = np.zeros((T, K))
    for k in range(K):
        diff = X - mu[k]
        var = cov[k]
        lg[:, k] = (-0.5 * np.sum(diff * diff / var, axis=1)
                    - 0.5 * np.sum(np.log(2 * np.pi * var)))
    return lg


def _scaled_normalize(v):
    """按和归一；和为 0 或非有限（该步无信息）⇒ 回退均匀分布。

    回退而非 0/0：否则 alpha 变 NaN 会一路污染 gamma/xi（WT-25 修复配套）。
    第二个返回值是 scale，供 loglik 累加。
    """
    s = float(v.sum())
    if not np.isfinite(s) or s <= 0.0:
        return np.full(len(v), 1.0 / len(v)), 1e-300
    return v / s, s


def _forward_backward(lg, pi, A):
    """scaled 前向-后向：返回 alpha_hat, beta_hat, gamma, xi（对数域用 scaled 简化）。

    ⚠️ **WT-25 修复（2026-10-12）**：xi 原先用
        denom = (alpha[t] * np.exp(lg[t + 1])) @ A.T @ beta[t + 1] + 1e-300
    把 `exp(lg[t+1])` 乘在**源状态 i** 上，而分子 numer[i,j] 用的是**目的状态 j**
    ⇒ denom ≠ Σnumer（两者是两个不同的量）。极可分数据下 denom 下溢为 0，
    `+1e-300` 把它兜成 1e-300 ⇒ xi 被放大 **1e300 倍**（实测层和 2.55e300，
    而 Σnumer = 2.55）。因 M-step 会重归一化，训练不崩，但**任何直接消费 xi
    的调用方都会拿到垃圾数值**。

    现按 `denom = Σ_ij numer` 归一 ⇒ 每层（t）和为 1、每个 (t,i) 行和为 1；
    denom 为 0（该转移不可能发生）时该层保持全 0，而不是放大成 1e300。
    """
    T, K = lg.shape
    # scaled forward
    alpha = np.zeros((T, K))
    alpha[0], s = _scaled_normalize(pi * np.exp(lg[0]))
    scales = [s]
    for t in range(1, T):
        alpha[t], s = _scaled_normalize((alpha[t - 1] @ A) * np.exp(lg[t]))
        scales.append(s)
    loglik = float(np.sum(np.log(np.asarray(scales))))
    # scaled backward
    beta = np.zeros((T, K))
    beta[-1] = 1.0
    for t in range(T - 2, -1, -1):
        beta[t], _ = _scaled_normalize((beta[t + 1] * np.exp(lg[t + 1])) @ A.T)
    # gamma（逐日归一；全 0 行保持全 0，不产生 NaN）
    gamma = alpha * beta
    row = gamma.sum(axis=1, keepdims=True)
    gamma = np.divide(gamma, row, out=np.zeros_like(gamma), where=row > 0)
    # xi：分子张量 → 按**其自身之和**归一（保证是概率量）
    xi = np.zeros((T - 1, K, K))
    for t in range(T - 1):
        numer = (alpha[t][:, None] * A
                 * np.exp(lg[t + 1])[None, :] * beta[t + 1][None, :])
        denom = float(numer.sum())
        if denom > 0.0 and np.isfinite(denom):
            xi[t] = numer / denom
        # denom == 0 ⇒ 该转移不可能发生 ⇒ 保持全 0（层和为 0）
    return alpha, beta, gamma, xi, loglik


def _viterbi(lg, pi, A):
    """Viterbi 解码：返回状态序列。"""
    T, K = lg.shape
    viter = np.zeros((T, K))
    back = np.zeros((T, K), dtype=int)
    viter[0] = np.log(pi + 1e-300) + lg[0]
    for t in range(1, T):
        for k in range(K):
            tmp = viter[t - 1] + np.log(A[:, k] + 1e-300)
            back[t, k] = int(np.argmax(tmp))
            viter[t, k] = tmp[back[t, k]] + lg[t, k]
    states = np.zeros(T, dtype=int)
    states[-1] = int(np.argmax(viter[-1]))
    for t in range(T - 1, 0, -1):
        states[t - 1] = back[t, states[t]]
    return states


def fit_hmm(X, K=3, max_iter=60, tol=1e-4, n_restarts=3):
    """Baum-Welch 训练（多次重启选优，规避 EM 状态坍缩）。
    X：T×D 观测（建议标准化）。返回最优 (pi,A,mu,cov,states,loglik)。"""
    T, D = X.shape
    if T < 40:
        return None
    Xs = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-9)
    best = None
    for seed in range(n_restarts):
        pi, A, mu, cov = _init_params(Xs, K, seed=seed)
        prev_ll = -np.inf
        n_iter = 0
        for n_iter in range(1, max_iter + 1):
            lg = _log_gauss(Xs, mu, cov)
            alpha, beta, gamma, xi, loglik = _forward_backward(lg, pi, A)
            # M-step
            pi = gamma[0] / gamma[0].sum()
            A = xi.sum(axis=0)
            A /= A.sum(axis=1, keepdims=True) + 1e-300
            denom = gamma.sum(axis=0)
            mu = (gamma.T @ Xs) / (denom[:, None] + 1e-300)
            for k in range(K):
                diff = Xs - mu[k]
                cov[k] = (gamma[:, k, None] * diff * diff).sum(axis=0) / (denom[k] + 1e-300)
                cov[k] += 1e-6
            if abs(loglik - prev_ll) < tol * abs(prev_ll):
                break
            prev_ll = loglik
        lg = _log_gauss(Xs, mu, cov)
        states = _viterbi(lg, pi, A)
        alive = {int(s) for s in states}
        cand = {"pi": pi, "A": A, "mu": mu, "cov": cov, "states": states,
                "loglik": float(loglik), "n_iter": int(n_iter),
                "all_alive": len(alive) == K}
        if best is None or (cand["all_alive"] and not best["all_alive"]) \
                or (cand["all_alive"] == best["all_alive"] and cand["loglik"] > best["loglik"]):
            best = cand
    return best


def load_features(repodata):
    """读 features.csv → (dates, X 观测矩阵)。观测列缺失行剔除。"""
    f = pd.read_csv(repodata / "features.csv", parse_dates=["date"])
    v = f.dropna(subset=["fg_index"]).copy()
    obs = v[OBS_COLS].dropna()
    dates = v.loc[obs.index, "date"].reset_index(drop=True)
    return dates, obs.to_numpy()


def analyze(repodata, K=3):
    """完整分析：训练 + 当前 regime + 各 regime 描述统计。"""
    dates, X = load_features(repodata)
    fit = fit_hmm(X, K=K)
    if fit is None:
        return {"error": "数据不足"}
    states = fit["states"]
    # regime → 语义（按 mu[0] 均值排序：低=恐惧 高=贪婪）
    order = np.argsort(fit["mu"][:, 0])
    label_of = {int(k): ("恐惧" if i == 0 else ("中性" if i == 1 else "贪婪"))
                for i, k in enumerate(order)}
    cur = int(states[-1])
    # 各 regime 的 fg_index 描述
    Xraw = X  # 未标准化（load 后原始值）
    desc = {}
    for k in range(K):
        idx = np.where(states == k)[0]
        desc[str(k)] = {
            "label": label_of[k],
            "n_days": int(len(idx)),
            "fg_mean": round(float(Xraw[idx, 0].mean()), 2) if len(idx) else None,
            "fg_std": round(float(Xraw[idx, 0].std()), 2) if len(idx) else None,
        }
    return {
        "dates": [str(d.date()) for d in dates],
        "states": [label_of[int(s)] for s in states],
        "current_regime": label_of[cur],
        "current_regime_key": cur,
        "regime_desc": desc,
        "loglik": fit["loglik"],
        "n_iter": fit["n_iter"],
    }
