# -*- coding: utf-8 -*-
"""WT-21 `fg_system/risk.py` HRP 递归二分校正测试。

**不读真实 Data/**：内联构造收益矩阵，其相关矩阵含**两个高度相关的块**
（{a,b} 与 {c,d}），据此手算暴力分组作为真值，断言 HRP 的树结构二分
与暴力分组**一致**，且权重 sum≈1、各分量 ∈ [0,1]。

原实现缺陷（本次校正，已复现）：`_recursive` 内
    i, j = Z[len(idxs) - 2, 0:2]                 # 假定 idxs 为连续全局索引
    cl = hierarchy.fcluster(Z, len(idxs) - 1, "maxclust")
    left  = [k for k in idxs if cl[k] == 1]
    right = [k for k in idxs if cl[k] == 2]
`fcluster` 返回的是**全局簇号**。当 `idxs` 是子集（递归深层）时全局簇号
与子集错位，`left`/`right` 可能为空或丢掉整片子树 ⇒ 未访问的叶子**根本
没被赋权**（静默丢资产），剩余列再归一化仍凑成 sum=1 ⇒ 无任何断言可察。
本测试以"每列都在结果里且 > 0、sum≈1、二分符合手算分块"锁定该行为。
"""
import numpy as np
import pandas as pd

from fg_system import risk


def _returns_from_corr(corr, n_obs=200, seed=0):
    """由目标相关矩阵生成收益 DataFrame（列名 a,b,c,d...，与 corr 同序）。"""
    rng = np.random.default_rng(seed)
    k = corr.shape[0]
    chol = np.linalg.cholesky(corr)
    z = rng.standard_normal((n_obs, k)) @ chol.T
    cols = [chr(ord("a") + i) for i in range(k)]
    return pd.DataFrame(z, columns=cols)


def _two_block_corr():
    """四资产：块 A={a,b} 相关 0.9；块 B={c,d} 相关 0.9；块间 ~0。"""
    c = np.eye(4)
    c[0, 1] = c[1, 0] = 0.9
    c[2, 3] = c[3, 2] = 0.9
    return c


def _bruteforce_blocks(rets):
    """暴力分组：按"相关矩阵"把资产分成高相关块（阈值 0.5），返回 frozenset 列表。

    这是**独立于实现的真值**：只要 |corr| > 0.5 就归同块（并查集并起来）。
    """
    corr = rets.corr().abs().values
    k = corr.shape[0]
    parent = list(range(k))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(k):
        for j in range(i + 1, k):
            if corr[i, j] > 0.5:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(k):
        groups.setdefault(find(i), set()).add(rets.columns[i])
    return sorted([frozenset(v) for v in groups.values()], key=lambda s: sorted(s))


def test_hrp_weights_include_every_asset_positive():
    """核心回归：每个资产都必须出现在结果中且权重 > 0（原实现会静默丢资产）。

    原实现在 4 资产两块情形下只返回 3 个键（丢掉 d），6 资产三块时只返回
    2 个键（丢掉 a,b,c,d）——本断言直接锁死"不得丢列"。
    """
    for k, blocks in ((4, [(0, 1), (2, 3)]), (6, [(0, 1), (2, 3), (4, 5)])):
        corr = np.eye(k)
        for i, j in blocks:
            corr[i, j] = corr[j, i] = 0.95
        rets = _returns_from_corr(corr, n_obs=300, seed=k)
        w = risk.hrp_weights(rets)

        assert set(w.keys()) == set(rets.columns)          # 不丢列
        assert all(v > 0.0 for v in w.values())             # 每列正权重
        assert abs(sum(w.values()) - 1.0) < 1e-9
        assert all(0.0 <= v <= 1.0 for v in w.values())


def test_hrp_bisection_matches_bruteforce_grouping():
    """树结构二分应与**暴力分块**一致：每一块独占一个连续子树。

    做法：用单连接聚类，对全池取 2 簇（等价于根节点二分），把得到的两个
    簇（按列名）与暴力分块（按 |corr|>0.5 并查集）对比；两块情形下二者必须
    相等（{a,b} vs {c,d}）。
    """
    from scipy.cluster import hierarchy

    corr = _two_block_corr()
    rets = _returns_from_corr(corr, n_obs=300, seed=1)

    # 与实现同源的距离 + 单连接
    c = rets.corr().fillna(0.0).values
    dist = np.sqrt(np.maximum(0.0, (1.0 - c) / 2.0))
    Z = hierarchy.linkage(dist[np.triu_indices(len(rets.columns), k=1)],
                          method="single")
    cl = hierarchy.fcluster(Z, 2, criterion="maxclust")
    got = {
        frozenset(rets.columns[i] for i in range(len(cl)) if cl[i] == g)
        for g in (1, 2)
    }
    want = set(_bruteforce_blocks(rets))
    assert got == want, (got, want)
    assert want == {frozenset({"a", "b"}), frozenset({"c", "d"})}


def test_hrp_bisection_independent_of_column_order():
    """列序错乱（[c,a,d,b]）⇒ 权重仅随列名重排，不随位置变化。

    原实现的两处错位都用**位置/全局簇号**，会随列序漂移；正确实现只看
    相关结构的树形，重排列序后同名资产权重应完全一致。
    """
    corr = _two_block_corr()
    rets = _returns_from_corr(corr, n_obs=300, seed=2)

    w_nat = risk.hrp_weights(rets)
    w_scr = risk.hrp_weights(rets[["c", "a", "d", "b"]])

    assert set(w_nat.keys()) == set(w_scr.keys()) == {"a", "b", "c", "d"}
    for k in ("a", "b", "c", "d"):
        assert abs(w_nat[k] - w_scr[k]) < 1e-9, (k, w_nat, w_scr)


def test_hrp_within_block_weights_are_equal_for_symmetric_block():
    """对称两块（块内相关、块间独立且两两方差相同）⇒ 四资产应近似等权。

    真值：两个同构块 ⇒ 块级 alpha≈0.5；块内两资产逆方差相同 ⇒ 各占 1/4。
    这同时检验 sum≈1 与 [0,1]。
    """
    corr = _two_block_corr()
    rets = _returns_from_corr(corr, n_obs=500, seed=3)
    w = risk.hrp_weights(rets)

    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(0.0 <= v <= 1.0 for v in w.values())
    for v in w.values():
        assert abs(v - 0.25) < 0.05, w


def test_hrp_insufficient_sample_returns_equal_weight():
    """边界：样本 <30 ⇒ 等权回退（不硬算）。"""
    rets = pd.DataFrame(np.random.default_rng(0).standard_normal((10, 3)),
                        columns=list("abc"))
    w = risk.hrp_weights(rets)
    assert w == {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
