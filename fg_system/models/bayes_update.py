# -*- coding: utf-8 -*-
"""贝叶斯假说信心更新（数学模型落地 4/4，Beta-Bernoulli）。

用途：H 假说（evolution/hypotheses.md）的观察证据以"成功/失败计数"
形式累积（如 H-002 现金<0 天数 3/5）。本模块把计数转成 Beta 后验，
输出后验均值与 95% 置信区间，作为假说"信心"的量化依据——
替代"感觉接近结论"的主观判断。

纪律：只计算信心，不判决假说（LLM 永不判决 / 回测+数据裁判唯一）；
人工在信心足够时按 hypotheses 状态机迁移状态。
"""
import numpy as np
from math import lgamma


def beta_moments(a, b):
    """Beta(a,b) 均值 + 95% 区间（无 scipy：用正则化不完全 Beta 数值近似）。"""
    mean = a / (a + b)
    lo, hi = _beta_ppf(0.025, a, b), _beta_ppf(0.975, a, b)
    return mean, lo, hi


def _beta_logpdf(x, a, b):
    return (lgamma(a + b) - lgamma(a) - lgamma(b)
            + (a - 1) * np.log(x) + (b - 1) * np.log1p(-x))


def _beta_ppf(q, a, b, n=8000):
    """数值求 Beta 分位：等距网格 → PDF → 梯形 CDF → 插值（无 scipy 依赖）。"""
    xs = np.linspace(1e-9, 1 - 1e-9, n)
    pdf = np.exp(_beta_logpdf(xs, a, b) - _beta_logpdf(xs, a, b).max())
    dx = xs[1] - xs[0]
    cdf = np.cumsum(pdf) * dx
    cdf /= cdf[-1]
    return float(np.interp(q, cdf, xs))


def update(successes, trials, prior_a=1.0, prior_b=1.0):
    """Beta-Bernoulli：新观测 (successes/trials) → 后验 Beta(a',b')。"""
    a2 = prior_a + successes
    b2 = prior_b + (trials - successes)
    mean, lo, hi = beta_moments(a2, b2)
    return {"posterior_a": round(float(a2), 3),
            "posterior_b": round(float(b2), 3),
            "posterior_mean": round(float(mean), 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "successes": int(successes), "trials": int(trials)}


def parse_hypothesis_counts(hypotheses_md_path):
    """从 hypotheses.md 备注列提取 "X/N" 观察计数（如 '3/20'、'3/3'）。
    返回 {H-xxx: {"successes": X, "trials": N}}。散文格式，提取失败跳过。"""
    import re
    from pathlib import Path
    p = Path(hypotheses_md_path)
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| H-"):
            continue
        cols = [c.strip() for c in line.split("|")]
        hid = cols[1] if len(cols) > 1 else ""
        note = cols[-2] if len(cols) > 2 else ""  # 行尾 | 后是空串，备注在倒数第二列
        # 只认"观察点/天数/累计 X/N"语境的计数，避免把分箱区间(40-50/50-55)、
        # 日期(09-25/09-29)、列号(第 5/6 列)误当观察证据
        m = re.findall(r"(?:观察点|天数|累计)\D{0,6}?(\d+)\s*/\s*(\d+)", note)
        if hid.startswith("H-") and m:
            s, t = 0, 0
            for a, b in m:
                s, t = s + int(a), t + int(b)
            out[hid] = {"successes": s, "trials": t, "note_snippet": note[:80]}
    return out
