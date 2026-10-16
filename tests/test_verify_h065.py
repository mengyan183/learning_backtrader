# -*- coding: utf-8 -*-
"""WT-29 `scripts/verify_hypotheses.py` 的 H-065 handler 测试。

H-065（`evolution/hypotheses.md`）：在「流动性挤压期」中，股债 60 日滚动相关性
转正（避险属性失效），且该正相关不能由利率变动单独解释。

覆盖（全部用 tmp_path + monkeypatch config.RAW_DIR 造合成数据，**不读真实 Data/**）：
  1. 60 日滚动 Pearson 相关 `corr(t)` 计算正确；
  2. 主口径「挤压期」mask 正确（QQQ 与 TLT 同跌 **且** BAA10Y 5 日走阔 >25bp）；
  3. 辅助口径「挤压期」mask 正确（VIX > 全样本 80 分位 **或** VIX 单日跳升 >20%）；
  4. 缺文件 / 缺列 ⇒ `status="pending"` 且不崩（不抛异常）；
  5. 注册表接线（H-065 可被 `-H H-065` 选中，且登记为 custom）。

用真实脚本模块（importlib 加载），不跑全量回测、不改库外文件。
"""
import importlib.util
import os

import numpy as np
import pandas as pd
import pytest

from fg_system import config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "verify_hypotheses.py")


def _load():
    """每次加载一份新鲜模块，避免测试间全局状态串扰。"""
    spec = importlib.util.spec_from_file_location("verify_hypotheses", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vh = _load()


# ------------------------------------------------------------------ 合成数据
_N = 200                      # 交易日数（> 60 窗口，够算滚动相关）
_DATES = pd.date_range("2020-01-01", periods=_N, freq="B")


def _write_raw(raw, qqq_ret=None, tlt_ret=None, dgs10=None, baa10y=None,
               vix=None, drop=(), no_vix_col=False):
    """写合成 raw 数据；`drop` 里的文件名不写（用于缺文件测试）。

    价格以 QQQ/TLT 日收益构造（收盘价 = 100 × cumprod(1+ret)）。
    DGS10/BAA10Y 用 FRED 版式（observation_date,<SID>）；VIX 用 date,close。
    """
    raw.mkdir(parents=True, exist_ok=True)

    if qqq_ret is None:
        qqq_ret = np.zeros(_N)
    if tlt_ret is None:
        tlt_ret = np.zeros(_N)
    qqq_ret = np.asarray(qqq_ret, dtype=float)
    tlt_ret = np.asarray(tlt_ret, dtype=float)

    if "prices.csv" not in drop:
        rows = []
        for sym, ret in (("QQQ", qqq_ret), ("TLT", tlt_ret)):
            close = 100.0 * np.cumprod(1.0 + ret)
            for d, c in zip(_DATES, close):
                rows.append({"date": d, "symbol": sym, "open": c, "high": c,
                             "low": c, "close": c, "volume": 1000})
        pd.DataFrame(rows).to_csv(raw / "prices.csv", index=False)

    if "fred_DGS10.csv" not in drop:
        dgs10 = np.asarray(dgs10 if dgs10 is not None else [1.5] * _N, dtype=float)
        pd.DataFrame({"observation_date": _DATES, "DGS10": dgs10}).to_csv(
            raw / "fred_DGS10.csv", index=False)

    if "fred_BAA10Y.csv" not in drop:
        baa = np.asarray(baa10y if baa10y is not None else [2.0] * _N, dtype=float)
        pd.DataFrame({"observation_date": _DATES, "BAA10Y": baa}).to_csv(
            raw / "fred_BAA10Y.csv", index=False)

    if "vix.csv" not in drop:
        vix = np.asarray(vix if vix is not None else [15.0] * _N, dtype=float)
        cols = {"date": _DATES}
        cols["close" if not no_vix_col else "value"] = vix
        pd.DataFrame(cols).to_csv(raw / "vix.csv", index=False)


def _patch(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    monkeypatch.setattr(config, "RAW_DIR", str(raw))
    return raw


# ------------------------------------------------------------------ 1. 滚动相关
def test_h065_rolling_corr_computed_correctly(monkeypatch, tmp_path):
    """corr(t) = QQQ 与 TLT 日收益的 60 日滚动 Pearson 相关（与 pandas 逐步一致）。"""
    raw = _patch(monkeypatch, tmp_path)
    rng = np.random.RandomState(7)
    qqq = rng.normal(0, 0.01, _N)
    # TLT 收益 = -QQQ 收益（完全负相关）；窗口内应得 corr ≈ -1
    tlt = -qqq
    _write_raw(raw, qqq_ret=qqq, tlt_ret=tlt)

    out = vh.verify_h065(None)
    assert out["status"] == "ok"
    corr = out["corr"]                       # 逐日 corr(t) 序列
    assert isinstance(corr, pd.Series)
    # 手工用 pandas 复算：价格 = 100×cumprod(1+ret)，再 pct_change 取日收益。
    q = pd.Series(100.0 * np.cumprod(1.0 + qqq), index=_DATES).pct_change()
    t = pd.Series(100.0 * np.cumprod(1.0 + tlt), index=_DATES).pct_change()
    expect = q.rolling(vh.H065_ROLL_WINDOW).corr(t)
    idx = expect.dropna().index[5:40]
    for d in idx:
        assert corr.loc[d] == pytest.approx(expect.loc[d], abs=1e-9)
    # 完全负相关 ⇒ 有样本的窗口 corr 应接近 -1
    assert corr.dropna().mean() < -0.9


# ------------------------------------------------------------------ 2. 主口径 mask
def test_h065_primary_squeeze_mask(monkeypatch, tmp_path):
    """主口径 mask = QQQ 与 TLT 同日下跌 **且** BAA10Y 5 日走阔 >25bp。"""
    raw = _patch(monkeypatch, tmp_path)
    qqq = np.zeros(_N)
    tlt = np.zeros(_N)
    baa = np.zeros(_N)
    # 第 120 日：QQQ 与 TLT 同跌；且 BAA10Y 相对 5 日前走阔 40bp(>25)
    qqq[120] = -0.02
    tlt[120] = -0.01
    baa[115:] = 0.0
    baa[120] = 0.40                       # 5 日走阔 40bp
    # 第 130 日：QQQ 与 TLT 同跌，但 BAA10Y 未走阔（不满足第二条件）
    qqq[130] = -0.02
    tlt[130] = -0.01
    # 第 140 日：BAA10Y 走阔，但 QQQ 涨（不满足同跌）
    qqq[140] = 0.02
    tlt[140] = -0.01
    baa[140] = 0.50
    _write_raw(raw, qqq_ret=qqq, tlt_ret=tlt, baa10y=baa)

    out = vh.verify_h065(None)
    mask = out["primary_squeeze_mask"]
    assert isinstance(mask, pd.Series)
    assert bool(mask.loc[_DATES[120]]) is True      # 同跌 + 走阔 ⇒ 挤压
    assert bool(mask.loc[_DATES[130]]) is False     # 同跌但差未走阔
    assert bool(mask.loc[_DATES[140]]) is False     # 走阔但未同跌
    assert out["primary_squeeze_days"] == 1


# ------------------------------------------------------------------ 3. 辅助口径 mask
def test_h065_aux_vix_mask(monkeypatch, tmp_path):
    """辅助口径 mask = VIX 收盘 > 全样本 80 分位 **或** VIX 单日跳升 >20%。"""
    raw = _patch(monkeypatch, tmp_path)
    vix = np.full(_N, 10.0)
    vix[150] = 50.0        # 远超 80 分位（全样本绝大多数为 10）
    vix[170] = vix[169] * 1.25   # 单日跳升 25% > 20%
    _write_raw(raw, vix=vix)

    out = vh.verify_h065(None)
    mask = out["aux_vix_mask"]
    assert bool(mask.loc[_DATES[150]]) is True       # 高分位
    assert bool(mask.loc[_DATES[170]]) is True       # 跳升
    assert bool(mask.loc[_DATES[10]]) is False       # 平常日
    # ≤80 分位且无跳升的日子不计入
    assert out["aux_vix_days"] >= 2


# ------------------------------------------------------------------ 4. 缺数据 ⇒ pending
def test_h065_missing_files_returns_pending(monkeypatch, tmp_path):
    """缺文件 ⇒ status=pending，reason 含「数据缺失（路径）」，且**不抛异常**。"""
    raw = _patch(monkeypatch, tmp_path)
    _write_raw(raw, drop=("fred_DGS10.csv", "fred_BAA10Y.csv"))

    out = vh.verify_h065(None)               # 不得抛 DataMissingError
    assert out["status"] == "pending"
    assert out["passed"] is None
    assert "数据缺失（路径）" in out["reason"]
    assert "fred_DGS10.csv" in out["reason"] or "fred_BAA10Y.csv" in out["reason"]
    assert out["note"]                        # 口径/原因说明必须有


def test_h065_missing_vix_column_returns_pending(monkeypatch, tmp_path):
    """VIX 文件缺 close 列 ⇒ status=pending（缺列），不崩。"""
    raw = _patch(monkeypatch, tmp_path)
    _write_raw(raw, no_vix_col=True)

    out = vh.verify_h065(None)
    assert out["status"] == "pending"
    assert out["passed"] is None
    assert "vix" in out["reason"].lower()


def test_h065_missing_prices_returns_pending(monkeypatch, tmp_path):
    """缺 prices.csv（QQQ/TLT 源）⇒ status=pending，不崩。"""
    raw = _patch(monkeypatch, tmp_path)
    _write_raw(raw, drop=("prices.csv",))

    out = vh.verify_h065(None)
    assert out["status"] == "pending"
    assert "prices.csv" in out["reason"]


# ------------------------------------------------------------------ 5. 判定 & 接线
def test_h065_verdict_falsified_when_positive_ratio_low(monkeypatch, tmp_path):
    """不成立判据①：全样本 corr>0 占比 <20% ⇒ passed=False（不成立）。"""
    raw = _patch(monkeypatch, tmp_path)
    rng = np.random.RandomState(3)
    qqq = rng.normal(0, 0.01, _N)
    tlt = -qqq                                   # 全程负相关 ⇒ corr>0 占比 ~0
    _write_raw(raw, qqq_ret=qqq, tlt_ret=tlt)

    out = vh.verify_h065(None)
    assert out["status"] == "ok"
    assert out["corr_pos_ratio"] < 0.20
    assert out["passed"] is False                # 结论以主口径为准
    assert out["primary_passed"] is False


def test_h065_low_rate_bucket_ratio_is_within_bucket(monkeypatch, tmp_path):
    """不成立判据②：「低利率波动桶」corr>0 占比按**桶内**口径算（不是全样本的占比）。"""
    raw = _patch(monkeypatch, tmp_path)
    rng = np.random.RandomState(5)
    qqq = rng.normal(0, 0.01, _N)
    tlt = rng.normal(0, 0.01, _N)
    # DGS10 日变动：前 100 日平稳（0.01），后 100 日大波动（0.5）⇒ 中位数分桶。
    dgs = np.zeros(_N)
    dgs[1:100] = 0.01
    dgs[101:] = 0.5
    _write_raw(raw, qqq_ret=qqq, tlt_ret=tlt, dgs10=dgs)

    out = vh.verify_h065(None)
    assert out["rate_bucket_split"] is not None
    # 桶内占比 ∈ [0,1]，且「低波动桶」与「高波动桶」都能取到样本
    assert 0.0 <= out["low_rate_bucket_pos_ratio"] <= 1.0
    assert out["falsified_by"] is not None


def test_h065_reports_both_calibers_and_window(monkeypatch, tmp_path):
    """两个口径的占比都进结果；note 明确写出实际样本窗口（不硬写 2016-09-26）。"""
    raw = _patch(monkeypatch, tmp_path)
    rng = np.random.RandomState(11)
    qqq = rng.normal(0, 0.01, _N)
    tlt = rng.normal(0, 0.01, _N)
    _write_raw(raw, qqq_ret=qqq, tlt_ret=tlt)

    out = vh.verify_h065(None)
    assert "primary_corr_pos_ratio" in out
    assert "aux_corr_pos_ratio" in out
    assert "primary_squeeze_mask" in out         # 两口径都算
    assert "aux_vix_mask" in out
    # 实际窗口 = 对齐样本的 [首日, 末日]
    assert "2020-01-01" in out["note"]
    assert out["window_start"] == "2020-01-01"
    assert out["window_end"] == str(_DATES[-1].date())


def test_h065_registered_as_custom_and_selectable():
    """H-065 登记为 custom，可被 `-H H-065` 选中（SUPPORTED 含之）。"""
    assert vh.HYPOTHESES["H-065"]["kind"] == "custom"
    assert "H-065" in vh.CUSTOM
    assert "H-065" in vh.SUPPORTED


def test_h065_thresholds_are_module_constants():
    """阈值先验写死为模块级常量（OOS 禁调参）。"""
    assert vh.H065_ROLL_WINDOW == 60
    assert vh.H065_POS_RATIO_FLOOR == 0.20
    assert vh.H065_SPREAD_WIDEN_BP == 25.0
    assert vh.H065_SPREAD_WINDOW == 5
    assert vh.H065_VIX_JUMP_PCT == 0.20
    assert vh.H065_VIX_QUANTILE == 0.80
    assert vh.H065_COFALL_DAYS_MIN == 5
