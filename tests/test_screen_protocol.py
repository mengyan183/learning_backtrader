# -*- coding: utf-8 -*-
"""R1.1 因子评测协议测试：fg_system/factors/protocol.py + scripts/factor_screen.py 因子构造。

纪律：
- **绝不读真实 `Data/`** —— 全部用内存 DataFrame 造数（同 test_factor_screen_extend）。
- 不调用写文件的路径（不跑 factor_screen.main() 全流程；只测纯函数与构造函数）。
- 覆盖：IC 双口径、无前视分层分桶、分层单调、多空净值、含成本双口径、
  门槛判定三态、报告字段齐全、空输入防御、确定性、因子构造函数。

`scripts/` 不是包内模块，用 importlib 加载（同 tests/test_screen_yinn_momentum.py）。
"""
import importlib.util
import pathlib

import numpy as np
import pandas as pd
import pytest

from fg_system.factors import protocol as fp

_PATH = (pathlib.Path(__file__).resolve().parent.parent
         / "scripts" / "factor_screen.py")
_spec = importlib.util.spec_from_file_location("factor_screen", _PATH)
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)


def _mk_series(n=500, seed=7, drift=0.0004, vol=0.01):
    """人造日频序列：带漂移的随机游走（确定性 seed）。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = 100 * np.exp(np.cumsum(rets))
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(close, index=idx)


def _mk_signal(n=500, seed=3):
    """人造信号：缓慢均值回归序列（与收益存在单调关系时用）。"""
    rng = np.random.default_rng(seed)
    x = pd.Series(np.cumsum(rng.normal(0, 1, n)), dtype=float)
    x = x.rolling(20).mean().dropna()
    idx = pd.date_range("2024-01-01", periods=len(x), freq="B")
    return x.set_axis(idx)


# ---------------------------------------------------------------- IC 双口径

def test_ic_pearson_matches_pandas():
    """Pearson IC = pandas rolling corr（Pearson 默认）。"""
    sig = _mk_signal(300)
    close = _mk_series(300)
    fwd = fp.forward_returns(close, (5,))["fwd_5"]
    got = fp.ic_pearson(sig, fwd, window=60)
    df = pd.concat([sig.rename("s"), fwd.rename("t")], axis=1).dropna()
    exp = df["s"].rolling(60).corr(df["t"])
    pd.testing.assert_series_equal(got.dropna(), exp.dropna(), check_names=False)


def test_ic_spearman_equals_rank_pearson():
    """RankIC（Spearman）= 对齐去重后 rank 的 Pearson（与实现同口径，先对齐再 rank）。"""
    sig = _mk_signal(300)
    close = _mk_series(300)
    fwd = fp.forward_returns(close, (5,))["fwd_5"]
    r = fp.ic_spearman(sig, fwd, window=60)
    df = pd.concat([sig.rename("s"), fwd.rename("t")], axis=1).dropna()
    exp = df["s"].rank().rolling(60).corr(df["t"].rank())
    pd.testing.assert_series_equal(r.dropna(), exp.dropna(), check_names=False)


def test_ic_stats_shape():
    """ic_stats 返回字段齐全；空序列返回 None。"""
    st = fp.ic_stats(pd.Series([0.1, 0.2, -0.1, 0.3, 0.0, 0.2]))
    assert set(st) == {"ic_mean", "ic_std", "icir", "ic_positive_ratio", "n"}
    assert st["n"] == 6
    assert fp.ic_stats(pd.Series(dtype=float)) is None


# ---------------------------------------------------------------- 分层（无前视纪律）

def test_rolling_bucket_no_future_leak():
    """分桶只用截至当日数据：把未来值替换为极端值，当日桶不变。"""
    n = 300
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    x = pd.Series(np.sin(np.arange(n) / 20.0), index=idx)
    before = fp.rolling_quantile_bucket(x, window=120, n_buckets=5)
    # 篡改 t=200 之后的所有值（把未来变成极端）
    x2 = x.copy()
    x2.iloc[200:] = 1e6
    after = fp.rolling_quantile_bucket(x2, window=120, n_buckets=5)
    # t < 200 的桶不受未来篡改影响（除前 119 日窗口不足为 NaN）
    pd.testing.assert_series_equal(
        before.iloc[120:200], after.iloc[120:200], check_names=False)


def test_rolling_bucket_ranges():
    """桶取值 1..5；窗口不足为 NaN；波动序列覆盖 5 桶（单调序列会偏聚尾桶，属正常）。"""
    rng = np.random.default_rng(11)
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    x = pd.Series(np.sin(np.arange(200) / 8.0) + rng.normal(0, 0.15, 200), index=idx)
    b = fp.rolling_quantile_bucket(x, window=60, n_buckets=5)
    valid = b.dropna()
    assert valid.between(1, 5).all()
    assert b.iloc[:59].isna().all()  # 前 window-1 日为 NaN
    assert int(valid.nunique()) == 5  # 波动信号覆盖全部 5 桶


def _mk_ls_data(n=500, seed=5):
    """人造「信号领先收益」数据：sig 波动，未来 5 日收益与当前信号正相关。

    close 的日收益 = 0.02×sig.shift(5) + 噪声 ⇒ bucket 高（信号当前高分位）时
    未来 5 日收益期望更高（正相关，无前视：t 日信号只影响 t+5 之后收益）。
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    sig = pd.Series(np.sin(np.arange(n) / 12.0) + rng.normal(0, 0.2, n), index=idx)
    rets = 0.02 * sig.shift(5).fillna(0.0) + rng.normal(0.0, 0.005, n)
    close = 100 * np.exp(np.cumsum(rets))
    return sig, close


def test_bucket_means_monotonic_artificial():
    """人造正相关数据 → 顶底差为正、单调性接近 1。"""
    sig, close = _mk_ls_data(n=800)
    layers = fp.bucket_forward_stats(sig, close, horizons=(5,), n_buckets=5, window=200)
    h5 = layers[5]
    assert h5["top_minus_bottom"] > 0
    assert h5["monotonic_spearman"] > 0.8


def test_monotonicity_spearman_metric():
    """单调性 = 桶均值与组号 Spearman（>0 = 分层有效）。"""
    means = [0.01, 0.02, 0.03, 0.04, 0.05]
    s = pd.Series(means)
    corr = s.rank().corr(pd.Series([1, 2, 3, 4, 5]).rank())
    assert abs(corr - 1.0) < 1e-9


# ---------------------------------------------------------------- 多空 + 含成本

def test_long_short_nav_basic():
    """人造正相关数据 → 顶桶做多/底桶做空的多空净值 > 1。"""
    sig, close = _mk_ls_data()
    buckets = fp.rolling_quantile_bucket(sig, window=120, n_buckets=5)
    fwd = fp.forward_returns(close, (5,))["fwd_5"]
    ls = fp.long_short_nav(buckets, fwd, 5, fee=0.0, n_buckets=5)
    assert ls is not None
    assert ls["nav_final"] > 1.0
    assert ls["n_periods"] >= 2
    assert set(ls) == {"nav_final", "nav_final_net", "annualized", "annualized_net",
                       "max_dd", "max_dd_net", "n_periods", "fee"}


def test_nav_with_cost_reduces_final():
    """含成本口径：fee>0 时净值终值 ≤ 无成本净值终值。"""
    sig, close = _mk_ls_data()
    buckets = fp.rolling_quantile_bucket(sig, window=120, n_buckets=5)
    fwd = fp.forward_returns(close, (5,))["fwd_5"]
    no_cost = fp.long_short_nav(buckets, fwd, 5, fee=0.0, n_buckets=5)
    costly = fp.long_short_nav(buckets, fwd, 5, fee=0.01, n_buckets=5)
    assert costly["nav_final_net"] <= no_cost["nav_final_net"] + 1e-12
    assert costly["fee"] == 0.01


def test_long_short_nav_direction_flip():
    """逆向因子的多空腿翻转：同一数据 direction=逆向 的净值终值 ≠ 正向（做反方向）。"""
    sig, close = _mk_ls_data()
    buckets = fp.rolling_quantile_bucket(sig, window=120, n_buckets=5)
    fwd = fp.forward_returns(close, (5,))["fwd_5"]
    pos = fp.long_short_nav(buckets, fwd, 5, fee=0.0, n_buckets=5, direction="正向")
    rev = fp.long_short_nav(buckets, fwd, 5, fee=0.0, n_buckets=5, direction="逆向")
    # 人造数据信号与未来收益正相关：正向腿赚钱，逆向腿亏钱（净值 < 1）
    assert pos["nav_final"] > 1.0
    assert rev["nav_final"] < 1.0


def test_long_short_nav_insufficient_returns_none():
    """样本不足（<2 个有效调仓点）返回 None，不抛异常。"""
    idx = pd.date_range("2024-01-01", periods=12, freq="B")
    sig = pd.Series(np.linspace(0, 1, 12), index=idx)
    close = _mk_series(12)
    buckets = fp.rolling_quantile_bucket(sig, window=10, n_buckets=5)
    fwd = fp.forward_returns(close, (5,))["fwd_5"]
    assert fp.long_short_nav(buckets, fwd, 5) is None


# ---------------------------------------------------------------- 门槛判定

def test_verdict_pass():
    """|ICIR| ≥ 0.5 且 n ≥ 60 且近窗无衰减 → 通过。"""
    stats = {20: {"icir": -0.6, "n": 120}}
    recent = {20: {"icir": -0.7}}
    v = fp.verdict(stats, recent)
    assert v["status"] == "通过"
    assert v["best_horizon"] == 20


def test_verdict_accumulating():
    """n < 60 → accumulating。"""
    stats = {20: {"icir": 0.8, "n": 30}}
    v = fp.verdict(stats, {})
    assert v["status"] == "accumulating"


def test_verdict_fail_decay():
    """近窗衰减（近窗 |ICIR| < 全窗一半）→ 未达门槛。"""
    stats = {20: {"icir": -0.6, "n": 120}}
    recent = {20: {"icir": -0.1}}
    v = fp.verdict(stats, recent)
    assert v["status"] == "未达门槛"


# ---------------------------------------------------------------- 报告骨架与确定性

def test_screen_report_shape_and_deterministic():
    """screen_report 返回字段齐全；同输入两次输出一致（确定性）。"""
    sig = _mk_signal(400)
    close = _mk_series(400)
    r1 = fp.screen_report(sig, close, factor_id="T-1", target="SPY", direction="逆向")
    r2 = fp.screen_report(sig, close, factor_id="T-1", target="SPY", direction="逆向")
    assert r1 == r2
    for key in ("factor_id", "target", "direction", "sample_start", "sample_end",
                "n_days", "ic", "recent", "layers", "long_short", "verdict"):
        assert key in r1
    assert set(r1["ic"]) == {5, 10, 20, 40}
    h = r1["ic"][5]
    for key in ("pearson_ic_mean", "pearson_icir", "rank_ic_mean", "rank_icir", "n"):
        assert key in h


def test_screen_report_empty_signal():
    """空信号/空 close → 骨架（n_days=0，verdict=None），不抛异常。"""
    r = fp.screen_report(pd.Series(dtype=float), _mk_series(100), factor_id="T-2")
    assert r["n_days"] == 0 and r["verdict"] is None
    r2 = fp.screen_report(_mk_signal(100), pd.Series(dtype=float), factor_id="T-3")
    assert r2["n_days"] == 0


# ---------------------------------------------------------------- 因子构造函数（scripts/factor_screen.py）

def test_factor_constructors_shapes():
    """四个因子构造函数：正常输入返回日频 Series；缺列/空输入返回空 Series。"""
    idx = pd.date_range("2024-01-01", periods=100, freq="B")
    ref = pd.Series(100.0, index=idx)
    shoutu = pd.DataFrame({"date": idx[:50], "symbol": ["A"] * 50, "value": np.linspace(-60, 60, 50)})
    s7 = fs.factor_f007_market_temperature(shoutu, ref.index)
    assert isinstance(s7, pd.Series) and len(s7.dropna()) > 0
    assert fs.factor_f007_market_temperature(None, ref.index).empty

    funding = pd.DataFrame({"date": idx[:5], "funding_btc": [0.01] * 5})
    s9 = fs.factor_f009_funding(funding)
    assert len(s9) == 5
    assert fs.factor_f009_funding(pd.DataFrame({"date": idx[:5]})).empty

    news = pd.DataFrame({"date": idx[:60], "mkt_score": np.linspace(-1, 1, 60)})
    s10 = fs.factor_f010_news(news, ref.index)
    assert len(s10.dropna()) > 0
    assert fs.factor_f010_news(pd.DataFrame({"date": idx[:60]}), ref.index).empty

    pc = pd.DataFrame({"date": idx[:80], "total_ratio": np.linspace(0.6, 1.4, 80)})
    s11 = fs.factor_f011_putcall(pc)
    assert len(s11) == 80
    assert fs.factor_f011_putcall(pd.DataFrame({"date": idx[:5]})).empty
