# -*- coding: utf-8 -*-
"""`base.orthogonalize`：滚动回归取残差，**无前视**（2026-10-29）。

【为什么】C1_BAA10Y 与 `fed` 因子的 Spearman 相关 **+0.604** 偏高 ✗ ——
与美联储因子中度重复，直接进回测裁判很可能得出「无增量贡献」✗。
用户裁定：**先做 fed 正交化再跑裁判** ✓。

🔴 这类「滚动回归」最容易犯的错是**用含当天的窗口估 β** ✗ ——
当天的 y 自己参与估参 ⇒ 残差被系统性压小 ⇒ IC 虚高 ✗（正是本仓库最怕的 lookahead）。
本模块的 β 一律 `shift(1)`，只用 **t-1 及之前** 的信息 ✓。
"""
import importlib.util
import os

import numpy as np
import pandas as pd

from fg_system import config
from fg_system.factors import base as fbase


def _synth(n=400, seed=0, scale=0.1):
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    x = pd.Series(rng.normal(size=n), index=idx)
    noise = pd.Series(rng.normal(scale=scale, size=n), index=idx)
    return idx, x, noise


def test_removes_the_linear_component():
    """`y = 2x + 噪声` ⇒ 残差应≈噪声，且与 x 相关≈0 ✓。"""
    _, x, noise = _synth()
    y = 2.0 * x + noise

    r = fbase.orthogonalize(y, x, window=120).dropna()

    assert len(r) > 200, "残差样本太少 ✗"
    assert abs(r.corr(x.reindex(r.index))) < 0.1, "正交化后仍与 x 强相关 ✗"
    assert (r - noise.reindex(r.index)).abs().mean() < 0.05, "残差没回到噪声 ✗"


def test_residual_is_pure_subtraction_no_self_fit():
    """**当天自己不许参与估 β** ✓ —— 改 `y_t` 一个点，残差必须只变那么多。

    `shift(1)` 下：`β_t` 来自窗口 `[t-w, t-1]`，与 `y_t` 无关
    ⇒ `resid_t = y_t − β_t·x_t` 对 `y_t` 的导数**恰为 1** ✓。
    不 `shift` 时：`y_t` 进了自己的窗口 ⇒ β 跟着动 ⇒ 导数 ≠ 1 ✗（自拟合 ✗）。
    """
    _, x, noise = _synth(n=300, seed=1)
    y = 2.0 * x + noise

    r1 = fbase.orthogonalize(y, x, window=60)
    y2 = y.copy()
    y2.iloc[200] += 1.0             # 只改一个点
    r2 = fbase.orthogonalize(y2, x, window=60)

    delta = r2.iloc[200] - r1.iloc[200]
    assert abs(delta - 1.0) < 1e-9, \
        "改 y_t 后残差变化 %.6f ≠ 1.0 ⇒ β 用到了当天的 y（自拟合）✗" % delta


def test_future_perturbation_does_not_move_past():
    """改**未来**的 x ⇒ 过去的残差必须一模一样 ✓（更弱的通用前视检查）。"""
    _, x, noise = _synth(n=300, seed=1)
    y = 2.0 * x + noise

    r1 = fbase.orthogonalize(y, x, window=60)
    x2 = x.copy()
    x2.iloc[200:] += 5.0
    r2 = fbase.orthogonalize(y, x2, window=60)

    assert abs(r1.iloc[150] - r2.iloc[150]) < 1e-12, \
        "改了未来的 x，过去的残差却变了 ⇒ 有前视 ✗"


def test_warmup_is_nan_not_zero():
    """窗口不足处必须是 NaN ✓ —— 补 0 会造出假的「无相关」✗。"""
    _, x, noise = _synth(n=300, seed=2)
    y = 2.0 * x + noise

    r = fbase.orthogonalize(y, x, window=120)

    assert r.iloc[:20].isna().all(), "预热期没有 NaN ✗"
    assert r.iloc[-50:].notna().all(), "尾部仍有 NaN ✗"


def _load_eval():
    spec = importlib.util.spec_from_file_location(
        "eval_baa10y", os.path.join(config.ROOT, "scripts", "eval_baa10y.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eval_fmt_handles_none():
    """**守卫**：样本不足时 `ic` 字段是 `None` ⇒ 打 `—` 而不是崩 ✓。

    2026-10-29 Mac 实测：正交化后只剩 16 天 ⇒ `screen_report` 把
    `rank_ic_mean/rank_icir/pearson_icir` 全给 `None` ✗ ⇒
    `{v:+.3f}` 抛 `TypeError: unsupported format string passed to NoneType` ✗
    ⇒ 整条评测崩掉，只剩一行「样本不足」，什么都没拿到 ✗。
    """
    ev = _load_eval()
    assert ev._fmt(None) == "—"
    assert ev._fmt(0.5) == "+0.500"
    assert ev._fmt(None, "+.2f", 100) == "—"
    assert ev._fmt(0.1234, "+.2f", 100) == "+12.34"


def test_constant_x_gives_nan_not_crash():
    """x 恒定 ⇒ 方差 0 ⇒ β 无定义 ⇒ 残差 NaN，但**不能崩** ✓。"""
    idx = pd.date_range("2020-01-01", periods=120, freq="B")
    x = pd.Series(1.0, index=idx)
    y = pd.Series(np.arange(120.0), index=idx)

    r = fbase.orthogonalize(y, x, window=60)

    assert len(r) == 120
    assert r.isna().all(), "x 恒定时应全 NaN（除以 0 已挡住）✗"
