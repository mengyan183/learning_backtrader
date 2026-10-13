# -*- coding: utf-8 -*-
"""A3b BH-FDR（Benjamini-Hochberg 错误发现率控制，规划 v2.0 A3b）。

用于「一组并列假设各自检验」的场景：从 N 次检验里挑出「校正后仍成立」的
假设。与 A3a Deflated Sharpe（从 N 次尝试里择优）**不可互相替代**。

实现：标准 BH 步骤——
  1. p 值升序 p_(1) ≤ ... ≤ p_(m)；
  2. 阈值序列 t_k = (k/m) × alpha；
  3. 取最大 k 使 p_(k) ≤ t_k，拒绝前 k 个最小 p 值。

N 的来源：`evolution/attempts-ledger.jsonl`（A3c 台账，MT-04）。历史尝试
**不可枚举**（台账只对未来生效）⇒ 现阶段只对**台账内已登记**的检验做校正。

用法：
    rejected = bh_fdr(p_values, alpha=0.05)   # bool 数组，保持原输入顺序
"""
import numpy as np


def bh_fdr(p_values, alpha=0.05):
    """BH 校正。返回与输入同序的 bool 数组（True=校正后仍显著）。

    输入含 NaN 时按「缺失」处理（不参与排序、不拒绝，位置输出 False）。
    """
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    out = np.zeros(n, dtype=bool)
    if n == 0:
        return out
    finite = np.isfinite(p)
    idx = np.flatnonzero(finite)
    if len(idx) == 0:
        return out
    sp = p[idx]
    order = np.argsort(sp)          # 升序排序（保持原位置索引 idx）
    sorted_p = sp[order]
    m = len(sorted_p)
    thresholds = (np.arange(1, m + 1) / m) * alpha
    below = sorted_p <= thresholds
    if below.all():
        k = m
    else:
        k = int(np.argmax(~below))  # 第一个不满足的位置 = 拒绝个数上限
    out[idx[order[:k]]] = True
    return out
