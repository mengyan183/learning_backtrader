# -*- coding: utf-8 -*-
"""H-068 `scripts/verify_hypotheses.py` handler 测试。

H-068（`evolution/hypotheses.md`）：流动性挤压期中股债 **5 日滚动**相关
**显著高于**非挤压期（避险属性瞬时失效）。

H-065 的三处翻车点，本测试**逐条立回归**：
  1. 🔴 **反循环定义**：挤压期 mask **不得**依赖 QQQ/TLT 方向
     （H-065 主口径含「TLT 也跌」⇒ 把结论写进自变量）⇒
     「高 VIX 但股债**同涨**」的日子**必须**判为挤压期；
  2. 🔴 **判据不与定义重叠**：判据是「挤压期 vs 非挤压期」**对比**，
     不是数挤压期内的同跌天数；
  3. 🔴 **不得以无样本口径定结论**：BAA10Y 缺 ⇒ **不影响**主判定（不 pending）。

⚠️ 样本量约定：主口径用 **VIX 80 分位** ⇒ 挤压期 ≈ 样本的 **20%**
⇒ 要满足 `H068_MIN_SQUEEZE_DAYS = 200`，合成样本须 **≥1000 日**
（真实数据 2492 日 ⇒ 挤压期 ≈450 日，与 H-065 辅助口径 445 日一致）。

覆盖（全部 tmp_path + monkeypatch config.RAW_DIR 造合成数据，**不读真实 Data/**）：
  1. 5 日滚动 Pearson 相关计算正确；
  2. 主口径 mask 正确（VIX 高分位 / 单日跳升），且**与股债方向无关**；
  3. 缺文件 / 缺列 ⇒ `status="pending"` 且不崩；BAA10Y 缺 ⇒ **不** pending；
  4. 判定：挤压期正相关显著更高 ⇒ `passed=True`；更低 ⇒ `passed=False`；
  5. 挤压期样本 < 200 ⇒ `status="insufficient"`（不硬凑）；
  6. 注册表接线（`-H H-068` 可选中）+ 阈值先验写死为模块常量。
"""
import importlib.util
import os

import numpy as np
import pandas as pd
import pytest

from fg_system import config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "verify_hypotheses.py")

_N = 1200                      # 交易日数（80 分位 ⇒ 挤压期 ~240 日 ≥ 200 下限）
_CUT = int(_N * 0.8)           # 挤压期起点（后 20%）


def _load():
    """每次加载一份新鲜模块，避免测试间全局状态串扰。"""
    spec = importlib.util.spec_from_file_location("verify_hypotheses", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vh = _load()


def _dates(n):
    return pd.date_range("2020-01-01", periods=n, freq="B")


def _graded_vix(n, lo=10.0, hi=40.0):
    """VIX 从 lo 线性升到 hi ⇒ 80 分位 ≈ lo+0.8(hi-lo) ⇒ mask ≈ **后 20%**。"""
    return np.linspace(lo, hi, n)


def _write_raw(raw, n, qqq_ret, tlt_ret, vix, baa10y=None, drop=(),
               no_vix_col=False):
    """写合成 raw 数据（价格 = 100 × cumprod(1+ret)）。"""
    raw.mkdir(parents=True, exist_ok=True)
    dates = _dates(n)
    qqq_ret = np.asarray(qqq_ret, dtype=float)
    tlt_ret = np.asarray(tlt_ret, dtype=float)

    if "prices.csv" not in drop:
        rows = []
        for sym, ret in (("QQQ", qqq_ret), ("TLT", tlt_ret)):
            close = 100.0 * np.cumprod(1.0 + ret)
            for d, c in zip(dates, close):
                rows.append({"date": d, "symbol": sym, "open": c, "high": c,
                             "low": c, "close": c, "volume": 1000})
        pd.DataFrame(rows).to_csv(raw / "prices.csv", index=False)

    if "vix.csv" not in drop:
        cols = {"date": dates}
        cols["close" if not no_vix_col else "value"] = np.asarray(vix, dtype=float)
        pd.DataFrame(cols).to_csv(raw / "vix.csv", index=False)

    if "fred_BAA10Y.csv" not in drop and baa10y is not None:
        pd.DataFrame({"observation_date": dates,
                      "BAA10Y": np.asarray(baa10y, dtype=float)}).to_csv(
            raw / "fred_BAA10Y.csv", index=False)


def _patch(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    monkeypatch.setattr(config, "RAW_DIR", str(raw))
    return raw


def _returns(seed, cut=_CUT):
    """前段 TLT=-QQQ（corr<0）、后段 TLT=QQQ（corr>0）⇒ 挤压期正相关更高。"""
    rng = np.random.RandomState(seed)
    qqq = rng.normal(0, 0.01, _N)
    tlt = np.concatenate([-qqq[:cut], qqq[cut:]])
    return qqq, tlt


# ------------------------------------------------------------------ 1. 滚动相关
def test_h068_rolling_corr_is_short_window(monkeypatch, tmp_path):
    """corr(t) = QQQ 与 TLT 日收益的 **5 日** 滚动 Pearson 相关（短窗，非 60 日）。"""
    raw = _patch(monkeypatch, tmp_path)
    rng = np.random.RandomState(7)
    qqq = rng.normal(0, 0.01, _N)
    tlt = -qqq                                # 完全负相关
    _write_raw(raw, _N, qqq, tlt, _graded_vix(_N))

    out = vh.verify_h068(None)
    assert out["status"] in ("ok", "insufficient")
    corr = out["corr"]
    assert isinstance(corr, pd.Series)
    q = pd.Series(100.0 * np.cumprod(1.0 + qqq), index=_dates(_N)).pct_change()
    t = pd.Series(100.0 * np.cumprod(1.0 + tlt), index=_dates(_N)).pct_change()
    expect = q.rolling(vh.H068_ROLL_WINDOW).corr(t)
    for d in expect.dropna().index[5:40]:
        assert corr.loc[d] == pytest.approx(expect.loc[d], abs=1e-9)
    assert corr.dropna().mean() < -0.9        # 完全负相关


# ------------------------------------------------- 2. mask 与股债方向**无关**
def test_h068_squeeze_mask_ignores_stock_bond_direction(monkeypatch, tmp_path):
    """🔴 反循环定义：VIX 高但股债**同涨**的日子也**必须**判为挤压期。

    （H-065 主口径含「QQQ 与 TLT 同日下跌」⇒ 这类日子会被排除 ⇒ 循环定义。）
    """
    raw = _patch(monkeypatch, tmp_path)
    qqq = np.zeros(_N)
    tlt = np.zeros(_N)
    vix = _graded_vix(_N)
    # 第 300 日：VIX 单日跳升 25%（> 20%）—— 但 QQQ/TLT **同时上涨**
    qqq[300] = 0.02
    tlt[300] = 0.02
    vix[300] = vix[299] * 1.25
    _write_raw(raw, _N, qqq, tlt, vix)

    out = vh.verify_h068(None)
    mask = out["squeeze_mask"]
    assert bool(mask.loc[_dates(_N)[300]]) is True      # 方向无关 ⇒ 仍是挤压期
    assert bool(mask.loc[_dates(_N)[10]]) is False      # 平常日


def test_h068_squeeze_mask_high_quantile(monkeypatch, tmp_path):
    """主口径 mask = VIX > 全样本 80 分位 **或** 单日跳升 >20%。"""
    raw = _patch(monkeypatch, tmp_path)
    qqq, tlt = _returns(17)          # 非退化收益（np.zeros ⇒ 零方差 ⇒ corr 全 NaN）
    _write_raw(raw, _N, qqq, tlt, _graded_vix(_N))

    out = vh.verify_h068(None)
    mask = out["squeeze_mask"]
    assert bool(mask.loc[_dates(_N)[0]]) is False       # 最低分位
    assert bool(mask.loc[_dates(_N)[_N - 1]]) is True   # 最高分位
    # 80 分位规则 ⇒ 挤压期 ≈ 后 20%（允许边界若干日）
    assert vh.H068_MIN_SQUEEZE_DAYS <= out["squeeze_days"] <= _N // 5 + 20


# ------------------------------------------------------- 3. 缺数据 ⇒ pending
def test_h068_missing_files_returns_pending(monkeypatch, tmp_path):
    """缺 prices.csv / vix.csv ⇒ pending，不抛异常。"""
    raw = _patch(monkeypatch, tmp_path)
    _write_raw(raw, _N, np.zeros(_N), np.zeros(_N), _graded_vix(_N),
               drop=("prices.csv",))
    out = vh.verify_h068(None)
    assert out["status"] == "pending"
    assert out["passed"] is None
    assert "数据缺失（路径）" in out["reason"]
    assert "prices.csv" in out["reason"]

    raw2 = tmp_path / "raw2"
    monkeypatch.setattr(config, "RAW_DIR", str(raw2))
    _write_raw(raw2, _N, np.zeros(_N), np.zeros(_N), _graded_vix(_N),
               drop=("vix.csv",))
    out2 = vh.verify_h068(None)
    assert out2["status"] == "pending"
    assert "vix.csv" in out2["reason"]


def test_h068_missing_vix_column_returns_pending(monkeypatch, tmp_path):
    """VIX 缺 close 列 ⇒ pending（缺列），不崩。"""
    raw = _patch(monkeypatch, tmp_path)
    _write_raw(raw, _N, np.zeros(_N), np.zeros(_N), _graded_vix(_N),
               no_vix_col=True)
    out = vh.verify_h068(None)
    assert out["status"] == "pending"
    assert "vix" in out["reason"].lower()


def test_h068_missing_baa10y_does_not_pend(monkeypatch, tmp_path):
    """🔴 反「以无样本口径定结论」：BAA10Y 缺 ⇒ **不影响**主判定（不 pending）。"""
    raw = _patch(monkeypatch, tmp_path)
    qqq, tlt = _returns(11)
    _write_raw(raw, _N, qqq, tlt, _graded_vix(_N))      # 不写 BAA10Y

    out = vh.verify_h068(None)
    assert out["status"] == "ok"                 # 主判定照跑
    assert out["aux_baa10y_days"] is None        # 辅助明细不可得
    assert out["passed"] is True


def test_h068_baa10y_present_gives_aux_detail(monkeypatch, tmp_path):
    """BAA10Y 在位 ⇒ 辅助明细列出走阔日（**不参与判定**，仅报数）。"""
    raw = _patch(monkeypatch, tmp_path)
    qqq, tlt = _returns(13)
    baa = np.zeros(_N)
    baa[_CUT + 10] = 0.40                       # 5 日走阔 40bp > 25bp
    _write_raw(raw, _N, qqq, tlt, _graded_vix(_N), baa10y=baa)

    out = vh.verify_h068(None)
    assert out["aux_baa10y_days"] == 1
    assert out["aux_baa10y_detail"][0]["date"] == str(_dates(_N)[_CUT + 10].date())
    assert out["aux_baa10y_detail"][0]["widen_bp"] == pytest.approx(40.0, abs=0.1)


# ------------------------------------------------------------------ 4. 判定
def test_h068_passed_when_squeeze_positive_ratio_higher(monkeypatch, tmp_path):
    """挤压期 corr>0 占比显著更高 ⇒ passed=True。"""
    raw = _patch(monkeypatch, tmp_path)
    qqq, tlt = _returns(3)
    _write_raw(raw, _N, qqq, tlt, _graded_vix(_N))

    out = vh.verify_h068(None)
    assert out["status"] == "ok"
    assert out["squeeze_pos_ratio"] > 0.9
    assert out["nonsqueeze_pos_ratio"] < 0.1
    assert out["p_value"] < vh.H068_ALPHA
    assert out["passed"] is True


def test_h068_falsified_when_squeeze_positive_ratio_not_higher(monkeypatch,
                                                               tmp_path):
    """挤压期 corr>0 占比**不显著更高** ⇒ passed=False（不成立）。"""
    raw = _patch(monkeypatch, tmp_path)
    qqq = np.random.RandomState(5).normal(0, 0.01, _N)
    half = _CUT // 2
    # 非挤压期：前半 TLT=+QQQ、后半 TLT=-QQQ ⇒ 正相关占比 ~50%（保证 se>0）；
    # 挤压期：TLT=-QQQ ⇒ 占比 0 ⇒ 判据「显著更高」不满足。
    tlt = np.concatenate([qqq[:half], -qqq[half:_CUT], -qqq[_CUT:]])
    _write_raw(raw, _N, qqq, tlt, _graded_vix(_N))

    out = vh.verify_h068(None)
    assert out["status"] == "ok"
    assert out["squeeze_pos_ratio"] < 0.1
    assert out["passed"] is False


# -------------------------------------------------------------- 5. 样本不足
def test_h068_insufficient_when_squeeze_days_below_floor(monkeypatch, tmp_path):
    """挤压期样本 < 200 ⇒ status=insufficient、passed=None（**不硬凑结论**）。"""
    n = 240                                     # 后 20% ⇒ 挤压期仅 ~48 日
    raw = _patch(monkeypatch, tmp_path)
    rng = np.random.RandomState(9)
    qqq = rng.normal(0, 0.01, n)
    _write_raw(raw, n, qqq, qqq, _graded_vix(n))
    out = vh.verify_h068(None)
    assert out["status"] == "insufficient"
    assert out["passed"] is None
    assert out["squeeze_days"] < vh.H068_MIN_SQUEEZE_DAYS


# --------------------------------------------------------- 6. 接线 & 常量
def test_h068_registered_as_custom_and_selectable():
    """H-068 登记为 custom，可被 `-H H-068` 选中（SUPPORTED 含之）。"""
    assert vh.HYPOTHESES["H-068"]["kind"] == "custom"
    assert "H-068" in vh.CUSTOM
    assert "H-068" in vh.SUPPORTED


def test_h068_thresholds_are_module_constants():
    """阈值先验写死为模块级常量（OOS 禁调参）；短窗 5 日 ≠ H-065 的 60 日。"""
    assert vh.H068_ROLL_WINDOW == 5
    assert vh.H068_VIX_QUANTILE == 0.80
    assert vh.H068_VIX_JUMP_PCT == 0.20
    assert vh.H068_MIN_SQUEEZE_DAYS == 200
    assert vh.H068_ALPHA == 0.05
    assert vh.H068_SPREAD_WIDEN_BP == 25.0
    assert vh.H068_ROLL_WINDOW != vh.H065_ROLL_WINDOW


def test_one_sided_two_prop_z_known_values():
    """单侧两比例 z 检验：同比例 ⇒ p≈0.5；悬殊 ⇒ p≈0；空样本 ⇒ (None,None)。"""
    z0, p0 = vh._one_sided_two_prop_z(50, 100, 50, 100)
    assert z0 == pytest.approx(0.0, abs=1e-9)
    assert p0 == pytest.approx(0.5, abs=1e-9)
    _z1, p1 = vh._one_sided_two_prop_z(100, 100, 0, 100)
    assert p1 < 1e-9
    assert vh._one_sided_two_prop_z(0, 0, 1, 10) == (None, None)
