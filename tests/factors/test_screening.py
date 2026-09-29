# -*- coding: utf-8 -*-
"""因子筛选工具测试（第 13.4 条取证工具）。

重点验证：工具能**同时**识别「方向正确」与「方向相反」两种情况——
只会给出正面结论的工具没有否证能力，等于没做检验。
"""
import pathlib

import numpy as np
import pandas as pd
import pytest

import fg_system
from fg_system.factors import screening


# ---------------------------------------------------------------- 未来收益

def test_forward_return_horizon_1():
    close = pd.Series([100.0, 110.0, 121.0, 133.1])
    fr = screening.forward_return(close, 1)
    assert fr.iloc[0] == pytest.approx(0.10)
    assert fr.iloc[1] == pytest.approx(0.10)
    assert np.isnan(fr.iloc[-1]), "最后一天没有未来收益"


def test_forward_return_horizon_2():
    close = pd.Series([100.0, 110.0, 121.0])
    fr = screening.forward_return(close, 2)
    assert fr.iloc[0] == pytest.approx(0.21)
    assert np.isnan(fr.iloc[1]) and np.isnan(fr.iloc[2])


def test_forward_return_rejects_non_positive_horizon():
    with pytest.raises(ValueError):
        screening.forward_return(pd.Series([1.0, 2.0]), 0)


# ---------------------------------------------------------------- 分组

def test_bucket_table_orders_low_factor_first():
    """组 0 必须是**最恐惧**（因子值最低）的那一组。"""
    f = pd.Series(np.linspace(0.0, 0.99, 100))
    r = pd.Series(np.linspace(0.0, 1.0, 100))
    tbl = screening.bucket_table(f, r, n_buckets=5)
    assert list(tbl.index) == [0, 1, 2, 3, 4]
    assert tbl["n"].sum() == 100
    assert tbl["mean"].is_monotonic_increasing, "因子升序 → 组均值应升序"


def test_bucket_table_clips_factor_of_exactly_one():
    """raw 恰为 1.0 时必须落在最后一组，不能越界成组号 5。"""
    f = pd.Series([0.5, 1.0, 1.0])
    r = pd.Series([0.0, 0.0, 0.0])
    tbl = screening.bucket_table(f, r, n_buckets=5)
    assert list(tbl.index) == [0, 1, 2, 3, 4]
    assert tbl.loc[4, "n"] == 2


def test_bucket_table_empty_input():
    tbl = screening.bucket_table(pd.Series([], dtype=float), pd.Series([], dtype=float))
    assert tbl.empty
    assert list(tbl.columns) == ["n", "mean", "median", "win_rate"]


def test_bucket_table_drops_nan_pairs():
    f = pd.Series([0.1, np.nan, 0.9])
    r = pd.Series([0.0, 0.5, np.nan])
    tbl = screening.bucket_table(f, r, n_buckets=5)
    assert tbl["n"].sum() == 1, "任一侧 NaN 都必须剔除"


# ---------------------------------------------------------------- IC

def test_spearman_ic_is_negative_for_reverse_relationship():
    f = pd.Series(np.linspace(0.0, 1.0, 200))
    r = -f * 0.3
    assert screening.spearman_ic(f, r) == pytest.approx(-1.0)


def test_spearman_ic_is_positive_for_same_direction():
    f = pd.Series(np.linspace(0.0, 1.0, 200))
    assert screening.spearman_ic(f, f * 0.3) == pytest.approx(1.0)


def test_spearman_ic_nan_when_sample_too_small():
    f = pd.Series([0.1, 0.2, 0.3])
    assert np.isnan(screening.spearman_ic(f, f, min_n=60))


# ---------------------------------------------------------------- 完整筛选

def _reverse_factor(n=500):
    """构造一个**方向正确**的因子：因子越高（越贪婪）→ 未来收益越低。"""
    f = pd.Series(np.linspace(0.0, 1.0, n))
    return f, -0.20 * f


def test_screen_detects_correct_direction():
    f, r = _reverse_factor()
    out = screening.screen(f, r, n_buckets=5)
    assert out["ic"] == pytest.approx(-1.0)
    assert out["mono"] == pytest.approx(1.0), "组均值必须完全单调递减"
    # spread 不是 0.20 而是 0.16：组 0 的因子均值是 0.1（不是 0）、组 4 是 0.9
    # （不是 1），故 0.2 × (0.9 − 0.1) = 0.16。分组是**区间**不是端点。
    assert out["spread"] == pytest.approx(0.16, abs=0.01), "最恐惧组 − 最贪婪组 > 0"
    assert out["hit"] == pytest.approx(1.0), "恐惧日必须全部优于贪婪日"
    assert out["n"] == 500


def test_screen_detects_inverted_direction():
    """**否证能力测试**：方向相反的因子必须被判为不合格。"""
    f = pd.Series(np.linspace(0.0, 1.0, 500))
    r = +0.20 * f                       # 贪婪 → 高未来收益（与先验相反）
    out = screening.screen(f, r, n_buckets=5)
    assert out["ic"] == pytest.approx(1.0)
    assert out["spread"] < 0, "反向因子的 spread 必须为负"
    assert out["hit"] == pytest.approx(0.0)


def test_screen_flags_degenerate_factor():
    """**退化检测**：因子塌缩到单一分组时，`ic` 再显著也不可信，必须显式标记。

    真实触发场景：`rolling_pct` 作用在**单调趋势**的比价水平上 → 恒 0/1
    （实测 `fxi_rel_spy` 的 `spread` 因此为 NaN）。
    """
    f = pd.Series([0.0] * 400 + [1.0] * 400)      # 只有两端，中间三组为空
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.05, 800))
    out = screening.screen(f, r, n_buckets=5)
    assert out["degenerate"] is True
    assert (out["occupancy"] == 0).sum() == 3, "中间三组应为空"
    assert np.isnan(out["spread"]), "组为空时 spread 无定义"


def test_screen_not_degenerate_for_continuous_factor():
    f = pd.Series(np.linspace(0.0, 0.999, 500))
    out = screening.screen(f, -f * 0.2, n_buckets=5)
    assert out["degenerate"] is False
    assert (out["occupancy"] > 0).all()


def test_screen_gives_no_edge_for_noise():
    rng = np.random.default_rng(0)
    f = pd.Series(rng.uniform(0, 1, 3000))
    r = pd.Series(rng.normal(0, 0.05, 3000))
    out = screening.screen(f, r, n_buckets=5)
    assert abs(out["ic"]) < 0.06, "纯噪声不应产生明显 IC"
    assert abs(out["hit"] - 0.5) < 0.08, "纯噪声的 hit 应接近 0.5"


# ---------------------------------------------------------------- 红线守卫

def test_screening_is_not_imported_by_production_modules():
    """⚠️ 第 10 条红线：`screening` 含**前视偏差**（`shift(-h)`），

    一旦被生产模块（factors / signal / backtest / pipeline）导入，就意味着
    未来收益可能进入仓位决策。此测试把该红线**固化**为可执行断言。
    """
    root = pathlib.Path(fg_system.__file__).parent
    offenders = []
    for p in root.rglob("*.py"):
        if p.name == "screening.py" or "__pycache__" in str(p):
            continue
        text = p.read_text(encoding="utf-8")
        if "factors.screening" in text or "factors import screening" in text:
            offenders.append(str(p.relative_to(root)))
    assert offenders == [], "生产模块不得导入 screening：%s" % offenders
