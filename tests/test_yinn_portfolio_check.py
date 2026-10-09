# -*- coding: utf-8 -*-
"""YINN 组合层面取证脚本测试（第 12.35 条**检验 3**，第 12.38 条口径）。

`scripts/yinn_portfolio_check.py` 不是包内模块，用 importlib 直接加载
（同 `tests/test_yinn_cost_after.py` / `tests/test_screen_yinn_momentum.py` 的做法）。

重点验证四件事：
1. **相关系数算法正确** —— 用合成数据手算可复核（构造完全同相位 / 完全反相位序列）。
2. **inv_vol 权重归一化** —— 权重和 = 1 且与波动**反比**；且必须**复用**生产函数。
3. **组合指标两种输入都算得出**（含 YINN / 不含 YINN）。
4. **缺失序列必须被显式报告**，而不是静默丢弃。
"""
import ast
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system import pipeline

_PATH = (pathlib.Path(__file__).resolve().parent.parent
         / "scripts" / "yinn_portfolio_check.py")
_spec = importlib.util.spec_from_file_location("yinn_portfolio_check", _PATH)
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


# ---------------------------------------------------------------- 合成数据工具

def _wide(close_df):
    """把「纯 close 宽表」包成 `to_wide_ohlcv` 口径的 MultiIndex 宽表。"""
    out = pd.DataFrame(index=close_df.index)
    for s in close_df.columns:
        for f in ("open", "high", "low", "close"):
            out[(s, f)] = close_df[s]
    out.columns = pd.MultiIndex.from_tuples(out.columns, names=["symbol", "field"])
    return out


# ---------------------------------------------------------------- ① 相关性算法

def test_daily_returns_is_simple_pct_change():
    """日收益 = 简单收益率，且**首日 NaN 不填充**（缺失 ≠ 0 收益）。"""
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    close = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=idx)
    r = pc.daily_returns(close)
    assert np.isnan(r["A"].iloc[0])
    assert r["A"].iloc[1] == pytest.approx(0.10)
    assert r["A"].iloc[2] == pytest.approx(0.10)


def test_correlation_perfect_same_phase_is_one():
    """完全同相位（收益同号）⇒ ρ = +1，手算可验证。"""
    idx = pd.date_range("2024-01-01", periods=6, freq="B")
    a = [100.0, 110.0, 99.0, 108.9, 98.01, 107.811]
    close = pd.DataFrame({"YINN": a, "GDXU": np.array(a)}, index=idx)
    out = pc.correlation_table(close)
    assert out["corr"].loc["YINN", "GDXU"] == pytest.approx(1.0)


def test_correlation_perfect_anti_phase_is_minus_one():
    """完全反相位（收益反号）⇒ ρ = −1。"""
    idx = pd.date_range("2024-01-01", periods=6, freq="B")
    up = np.array([100.0, 110.0, 99.0, 108.9, 98.01, 107.811])
    # 反相位：把每个收益率取负 ⇒ 价格序列 = cumprod(1 - r)
    r = pd.Series(up).pct_change().fillna(0.0).to_numpy()
    down = 100.0 * np.cumprod(1.0 - r)
    close = pd.DataFrame({"YINN": up, "CRCG": down}, index=idx)
    out = pc.correlation_table(close)
    assert out["corr"].loc["YINN", "CRCG"] == pytest.approx(-1.0)


def test_correlation_table_reports_overlap_window():
    """相关必须报告**共同重叠区间**的起止与长度（两序列日期不齐时取交集）。"""
    idx1 = pd.date_range("2024-01-01", periods=20, freq="B")
    idx2 = pd.date_range("2024-01-10", periods=20, freq="B")
    a = pd.Series(np.linspace(100, 120, 20), index=idx1)
    b = pd.Series(np.linspace(50, 60, 20), index=idx2)
    close = pd.concat([a.rename("YINN"), b.rename("AXTX")], axis=1)
    out = pc.correlation_table(close)
    common = idx1.intersection(idx2)
    assert out["start"] == common.min()
    assert out["end"] == common.max()
    assert out["n"] == len(common)


def test_correlation_is_symmetric_and_diagonal_one():
    """对角 = 1，矩阵对称。"""
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    rng = np.random.default_rng(0)
    close = pd.DataFrame(
        {s: 100.0 * np.cumprod(1.0 + rng.normal(0, 0.01, 30))
         for s in ("YINN", "GDXU", "BTC")}, index=idx)
    c = pc.correlation_table(close)["corr"]
    assert np.allclose(np.diag(c.to_numpy()), 1.0)
    assert np.allclose(c.to_numpy(), c.to_numpy().T)


# ---------------------------------------------------------------- ② inv_vol 权重

def test_inv_vol_weights_sum_to_one_and_inverse_to_vol():
    """权重和 = 1，且与「无杠杆底层」的滚动波动**反比**。

    构造两条底层序列：A 波动恒定、B 波动为 A 的 2 倍 ⇒ B 的权重应是 A 的一半。
    """
    n = 300
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    # A：固定 +1%/−1% 交替（σ 小）；B：固定 +2%/−2% 交替（σ 加倍）
    a = 100.0 * np.cumprod(1.0 + np.tile([0.01, -0.01], n // 2))
    b = 100.0 * np.cumprod(1.0 + np.tile([0.02, -0.02], n // 2))
    close = pd.DataFrame({"GDXU": a, "GDXU_UND": a, "CONL": b, "COIN": b}, index=idx)
    wide = _wide(close)
    um = {"GDXU": "GDXU_UND", "CONL": "COIN"}
    w = pc.inv_vol_weights(wide, ["GDXU", "CONL"], um)
    last = w.iloc[-1]
    assert last.sum() == pytest.approx(1.0)
    # B 波动是 A 的 2 倍 ⇒ w_B = w_A / 2 ⇒ w_A : w_B = 2 : 1
    assert last["GDXU"] / last["CONL"] == pytest.approx(2.0, rel=1e-6)


def test_inv_vol_weights_reuses_production_function():
    """**禁止重造权重规则**：必须直接调用 `pipeline.risk_weight_series`。"""
    assert pc.pipeline is pipeline, "脚本必须复用 pipeline 模块"
    assert pc.risk_weight_series is pipeline.risk_weight_series
    assert config.WEIGHTING == "inv_vol"   # 口径钉死：既有规则就是 inv_vol


def test_underlying_map_comes_from_config():
    """底层映射必须来自 `config.SIGNAL_UNDERLYING_MAP`（§4.5 约束 1 / §4C.4）。"""
    um = pc.research_underlying_map()
    assert um["YINN"] == config.SIGNAL_UNDERLYING_MAP["YINN"] == "FXI"
    assert um["GDXU"] == config.SIGNAL_UNDERLYING_MAP["GDXU"]
    assert um["CONL"] == config.SIGNAL_UNDERLYING_MAP["CONL"]
    # BTC 现货杠杆的底层就是 BTC 自身（同 `config.CRYPTO_UNDERLYING["BTC"]`）
    assert um["BTC"] == "BTC"


# ---------------------------------------------------------------- ③ 组合指标

def _portfolio_wide():
    """5 个「现有持仓」+ YINN 的合成宽表（含各自无杠杆底层），足够长以过 252 日窗口。"""
    n = 400
    idx = pd.date_range("2019-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    cols = {"GDXU": "GDXU_UND", "CONL": "COIN", "CRCG": "CRCL",
            "AXTX": "AXTI", "YINN": "FXI", "BTC": "BTC"}
    close = {}
    for i, (s, und) in enumerate(cols.items()):
        base = 100.0 * np.cumprod(1.0 + rng.normal(0.0002 * (i + 1), 0.01 * (i + 1), n))
        close[s] = base
        close[und] = base   # 底层与标的同序列即可（本测试只关心指标算得出）
    return _wide(pd.DataFrame(close, index=idx))


def test_portfolio_metrics_computable_without_yinn():
    """对照口径（不含 YINN）：指标算得出、非 NaN，且权重列**不含** YINN。"""
    wide = _portfolio_wide()
    out = pc.portfolio_metrics(wide, pc.EXISTING_HOLDINGS, pc.research_underlying_map())
    for k in ("annual_vol", "max_drawdown", "calmar"):
        assert not np.isnan(out[k]), "%s 不应为 NaN" % k
    assert "YINN" not in out["weights"].index


def test_portfolio_metrics_computable_with_yinn():
    """含 YINN 口径：指标算得出、非 NaN，且权重列**含** YINN。"""
    wide = _portfolio_wide()
    syms = pc.EXISTING_HOLDINGS + [pc.NEW_SYMBOL]
    out = pc.portfolio_metrics(wide, syms, pc.research_underlying_map())
    for k in ("annual_vol", "max_drawdown", "calmar"):
        assert not np.isnan(out[k]), "%s 不应为 NaN" % k
    assert "YINN" in out["weights"].index
    assert out["weights"].sum() == pytest.approx(1.0)


def test_with_and_without_yinn_use_the_same_window():
    """对照必须**同一段区间**（§12.38 第 3 步）⇒ 两口径的评估区间逐字相同。"""
    wide = _portfolio_wide()
    syms_no = pc.EXISTING_HOLDINGS
    syms_yes = pc.EXISTING_HOLDINGS + [pc.NEW_SYMBOL]
    a = pc.portfolio_metrics(wide, syms_no, pc.research_underlying_map())
    b = pc.portfolio_metrics(wide, syms_yes, pc.research_underlying_map())
    assert a["start"] == b["start"] and a["end"] == b["end"] and a["n"] == b["n"]


# ---------------------------------------------------------------- ④ 缺失序列显式报告

def test_missing_series_is_reported_not_dropped():
    """缺列的序列必须进 `missing` 名单，**不得**静默丢弃。"""
    wide = _portfolio_wide()
    # 人为去掉 BTC 的 close 列
    bad = wide.drop(columns=[("BTC", "close")])
    miss = pc.missing_series(bad, ["GDXU", "CONL", "CRCG", "AXTX", "YINN", "BTC"])
    assert "BTC" in miss
    assert "YINN" not in miss


def test_missing_series_flags_short_history():
    """有列但**可用区间不足**（全是 NaN 或有效点太少）也必须被报为缺失。"""
    wide = _portfolio_wide()
    wide[("BTC", "close")] = np.nan   # 列在，但无有效数据
    miss = pc.missing_series(wide, ["GDXU", "BTC"], min_points=2)
    assert "BTC" in miss


def test_none_missing_on_healthy_table():
    """健康表 ⇒ 缺失名单为空（避免把正常情况误报成缺失）。"""
    wide = _portfolio_wide()
    assert pc.missing_series(wide, ["GDXU", "GPT", "BTC"]) == ["GPT"]


# ---------------------------------------------------------------- 可直接运行

def test_script_injects_repo_root_before_importing_fg_system():
    """**实测踩到的坑**：`py -3.10 scripts/xxx.py` 时 sys.path[0] 是 `scripts/`、
    **不含仓库根** ⇒ `from fg_system import config` 直接 ModuleNotFoundError。

    用 **AST 断言**而非"某字符串出现过"（§12.27-①）：顺序错了照样会崩。
    """
    tree = ast.parse(_PATH.read_text(encoding="utf-8"))
    syspath, fg = [], []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "insert"
                and ast.unparse(node.func.value) == "sys.path"):
            syspath.append(node.lineno)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("fg_system"):
            fg.append(node.lineno)
        if isinstance(node, ast.Import) and any(
                a.name.startswith("fg_system") for a in node.names):
            fg.append(node.lineno)
    assert syspath, "脚本必须把仓库根注入 sys.path"
    assert fg, "脚本必须导入 fg_system"
    assert min(syspath) < min(fg), "sys.path 注入必须在 fg_system 导入**之前**"


def test_script_reconfigures_stdout_to_utf8():
    """Windows 默认 cp936 会把 `⇒` / `ρ` 写成 `??` ⇒ 必须重配 stdout。"""
    src = _PATH.read_text(encoding="utf-8")
    assert "reconfigure" in src and "utf-8" in src


# ---------------------------------------------------------------- 两两相关（各自最大重叠）

def test_pairwise_correlation_uses_each_pairs_own_overlap():
    """**核心**：两两 ρ 必须用**每对各自**的重叠区间，而不是全体交集。

    实测动机：`AXTX` 只有 108 行 ⇒ 全体交集被压到 103 日；若两两也按全体交集算，
    `GDXU`–`YINN` 就白白丢掉 1356 个交易日。这里构造「A 长 B 长 C 短」，
    断言 `A`–`B` 的 `n` 等于两者重叠（**远大于**全体交集）。
    """
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    close = pd.DataFrame({
        "A": np.linspace(100.0, 130.0, 300),
        "B": np.linspace(50.0, 70.0, 300),
        "C": [np.nan] * 250 + list(np.linspace(10.0, 12.0, 50)),
    }, index=idx)
    t = pc.pairwise_correlation(close)
    row = t[(t["left"] == "A") & (t["right"] == "B")].iloc[0]
    assert row["n"] == 300, "A–B 必须用它们自己的重叠（300），不是全体交集（50）"
    short = t[(t["left"] == "A") & (t["right"] == "C")].iloc[0]
    assert short["n"] == 50, "A–C 只重叠 50 日"
    assert np.isfinite(short["rho"])


def test_pairwise_correlation_rho_matches_direct_computation():
    """两两 ρ 必须等于直接对重叠区间的日收益算 Pearson（不得有隐藏重采样）。"""
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    rng = np.random.default_rng(7)
    a = 100 * np.cumprod(1 + rng.normal(0, 0.01, 60))
    b = 100 * np.cumprod(1 + rng.normal(0, 0.01, 60))
    close = pd.DataFrame({"A": a, "B": b}, index=idx)
    got = pc.pairwise_correlation(close).iloc[0]["rho"]
    want = pc.daily_returns(close).corr().loc["A", "B"]
    assert got == pytest.approx(want)


def test_pairwise_correlation_short_overlap_is_nan_not_zero():
    """重叠 < 2 点 ⇒ ρ 必须是 **NaN**（不是 0）—— 0 会被读成「无相关」这个结论。"""
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    close = pd.DataFrame({"A": np.arange(10.0) + 100,
                          "B": [np.nan] * 9 + [10.0]}, index=idx)
    row = pc.pairwise_correlation(close).iloc[0]
    assert row["n"] == 1
    assert np.isnan(row["rho"])


# ---------------------------------------------------------------- 数据可用性 / 退化判定

def test_underpowered_series_flags_short_history():
    """有效点数 < σ 窗口的标的必须被点名（它们是 inv_vol 退化为等权的根因）。"""
    wide = _portfolio_wide()
    weak = pc.underpowered_series(wide, ["GDXU", "BTC"], window=10 ** 6)
    assert weak == ["GDXU", "BTC"]
    assert pc.underpowered_series(wide, ["GDXU"], window=2) == []


def test_underpowered_series_reports_missing_column():
    """没有该列（不是「短」而是「无」）也必须被点名，不得静默跳过。"""
    wide = _portfolio_wide()
    assert "NOPE" in pc.underpowered_series(wide, ["NOPE"], window=2)


def test_is_equal_weight_detects_degenerate_inv_vol():
    """`inv_vol` 退化时权重**全相等** ⇒ 必须能被识别（否则等权会被读成风险平价）。"""
    assert pc.is_equal_weight(pd.Series({"A": 0.25, "B": 0.25, "C": 0.25})) is True
    assert pc.is_equal_weight(pd.Series({"A": 0.5, "B": 0.3, "C": 0.2})) is False
    assert pc.is_equal_weight(pd.Series(dtype=float)) is False
