# -*- coding: utf-8 -*-
"""H-069 `scripts/verify_hypotheses.py` handler 测试。

H-069（`evolution/hypotheses.md`）：流动性挤压期中股债**同日下跌**（`co_down`）
的条件概率**显著高于**非挤压期。

🔴 本条是 **「非盲登记」**（判据在已知 H-068 报数后确定）⇒ 判定**以「分段稳健」
为准**（全样本 + 中位日期前后两半段**都**显著更高才成立）。本测试重点回归该规则：

  1. 🔴 **分段稳健性**：全样本显著但**某半段不显著** ⇒ 必须 `passed=False`
     （否则非盲登记下会把「已知结果」当成验证）；
  2. 🔴 **反循环定义**：挤压期 mask **不得**依赖 QQQ/TLT 方向
     （高 VIX 但股债**同涨**的日子仍算挤压期）；
  3. 缺文件 / 缺列 ⇒ `pending`；挤压期样本不足 ⇒ `insufficient`（不硬凑）。

覆盖（tmp_path + monkeypatch config.RAW_DIR 造合成数据，**不读真实 Data/**）：
  1. `co_down` 二元指标与挤压 / 非挤压同跌率计算正确；
  2. mask 与股债方向无关；3. 缺数据 ⇒ pending；4. 两半段都显著 ⇒ passed=True；
  5. 只在半段成立 ⇒ passed=False；6. 样本不足 ⇒ insufficient；
  7. 接线 + 常量 + 非盲登记标记。
"""
import importlib.util
import os

import numpy as np
import pandas as pd
import pytest

from fg_system import config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "verify_hypotheses.py")

_N = 1200                      # 挤压期 20% ⇒ 240 日 ≥ 200 下限、每半段 ~120 ≥ 50


def _load():
    spec = importlib.util.spec_from_file_location("verify_hypotheses", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vh = _load()


def _dates(n):
    return pd.date_range("2020-01-01", periods=n, freq="B")


def _mk(n, seed, sq_frac=0.2):
    """返回 (vix, is_sq)：平滑底噪 + 随机均匀分布的挤压期（高 VIX 日）。

    ⚠️ 底噪必须**平滑**（日变动 ≪20%）—— 若用均匀随机数，会频繁触发主口径里的
    「VIX 单日跳升 >20%」规则 ⇒ mask 被灌入大量噪声日（实测 rate_sq 被稀释到
    0.58）。这里用正弦底噪 ⇒ mask ≈ 挤压期本身。
    挤压日给 VIX=60（远高于 80 分位）⇒ 挤压期在整段样本上**均匀分布**，
    保证前后两半段都有样本（分段稳健性可判）。
    """
    rng = np.random.RandomState(seed)
    vix = 14.0 + 3.0 * np.sin(np.arange(n) / 50.0)
    k = int(n * sq_frac)
    sq = rng.choice(n, size=k, replace=False)
    vix[sq] = 60.0
    return vix, np.isin(np.arange(n), sq)


def _from_codown(codown):
    """`codown[i]=True` ⇒ QQQ/TLT 当日都跌；False ⇒ 都涨。"""
    ret = np.where(np.asarray(codown, dtype=bool), -0.01, 0.01)
    return ret, ret.copy()


def _write_raw(raw, n, qqq_ret, tlt_ret, vix, drop=(), no_vix_col=False):
    raw.mkdir(parents=True, exist_ok=True)
    dates = _dates(n)
    if "prices.csv" not in drop:
        rows = []
        for sym, ret in (("QQQ", np.asarray(qqq_ret, dtype=float)),
                         ("TLT", np.asarray(tlt_ret, dtype=float))):
            close = 100.0 * np.cumprod(1.0 + ret)
            for d, c in zip(dates, close):
                rows.append({"date": d, "symbol": sym, "open": c, "high": c,
                             "low": c, "close": c, "volume": 1000})
        pd.DataFrame(rows).to_csv(raw / "prices.csv", index=False)

    if "vix.csv" not in drop:
        cols = {"date": dates}
        cols["close" if not no_vix_col else "value"] = np.asarray(vix, dtype=float)
        pd.DataFrame(cols).to_csv(raw / "vix.csv", index=False)


def _patch(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    monkeypatch.setattr(config, "RAW_DIR", str(raw))
    return raw


# ------------------------------------------------------------------ 1. 指标
def test_h069_codown_rates_computed(monkeypatch, tmp_path):
    """`co_down` 二元指标 ⇒ 挤压 / 非挤压同跌率与手工复算一致。"""
    raw = _patch(monkeypatch, tmp_path)
    vix, is_sq = _mk(_N, 7)
    qqq, tlt = _from_codown(is_sq)          # 挤压日全部同跌
    _write_raw(raw, _N, qqq, tlt, vix)

    out = vh.verify_h069(None)
    assert out["status"] == "ok"
    # 80 分位会把均匀底噪的**极值日**（~1 天）漏进 mask ⇒ 用 >= 而非 ==
    assert out["full_n_sq"] >= int(is_sq.sum())
    assert out["full_rate_sq"] > 0.98          # 挤压日几乎全部同跌
    assert out["full_rate_non"] < 0.02         # 非挤压日几乎不同跌
    assert out["full_p"] < 1e-9


# ------------------------------------------------- 2. mask 与股债方向**无关**
def test_h069_mask_ignores_direction(monkeypatch, tmp_path):
    """🔴 反循环定义：高 VIX 但股债**同涨**的日子也**必须**算作挤压期。"""
    raw = _patch(monkeypatch, tmp_path)
    vix, _is_sq = _mk(_N, 11)
    qqq = np.full(_N, 0.01)                 # 全部同涨 ⇒ co_down 恒 False
    tlt = np.full(_N, 0.01)
    _write_raw(raw, _N, qqq, tlt, vix)

    out = vh.verify_h069(None)
    mask = out["squeeze_mask"]
    assert out["full_n_sq"] > 0                      # 高 VIX 日仍被算作挤压期
    assert out["full_rate_sq"] == pytest.approx(0.0)  # 但当日并未同跌
    assert bool(mask.loc[_dates(_N)[int(np.argmax(vix))]]) is True


# ------------------------------------------------------- 3. 缺数据 ⇒ pending
def test_h069_missing_files_returns_pending(monkeypatch, tmp_path):
    raw = _patch(monkeypatch, tmp_path)
    vix, is_sq = _mk(_N, 13)
    qqq, tlt = _from_codown(is_sq)
    _write_raw(raw, _N, qqq, tlt, vix, drop=("prices.csv",))
    out = vh.verify_h069(None)
    assert out["status"] == "pending"
    assert out["passed"] is None
    assert "数据缺失（路径）" in out["reason"] and "prices.csv" in out["reason"]

    raw2 = tmp_path / "raw2"
    monkeypatch.setattr(config, "RAW_DIR", str(raw2))
    _write_raw(raw2, _N, qqq, tlt, vix, drop=("vix.csv",))
    out2 = vh.verify_h069(None)
    assert out2["status"] == "pending" and "vix.csv" in out2["reason"]


def test_h069_missing_vix_column_returns_pending(monkeypatch, tmp_path):
    raw = _patch(monkeypatch, tmp_path)
    vix, is_sq = _mk(_N, 17)
    qqq, tlt = _from_codown(is_sq)
    _write_raw(raw, _N, qqq, tlt, vix, no_vix_col=True)
    out = vh.verify_h069(None)
    assert out["status"] == "pending"
    assert "vix" in out["reason"].lower()


# ------------------------------------------------------------------ 4/5. 判定
def test_h069_passed_when_both_halves_significant(monkeypatch, tmp_path):
    """全样本 + **两个半段**都显著更高 ⇒ passed=True。"""
    raw = _patch(monkeypatch, tmp_path)
    vix, is_sq = _mk(_N, 23)
    qqq, tlt = _from_codown(is_sq)          # 挤压日 100% 同跌、非挤压 0%
    _write_raw(raw, _N, qqq, tlt, vix)

    out = vh.verify_h069(None)
    assert out["status"] == "ok"
    assert out["full_p"] < vh.H069_ALPHA
    assert out["first_half_p"] < vh.H069_ALPHA
    assert out["second_half_p"] < vh.H069_ALPHA
    assert out["passed"] is True


def test_h069_falsified_when_only_one_half_significant(monkeypatch, tmp_path):
    """🔴 分段稳健性回归：全样本显著但**前段不显著** ⇒ 必须 passed=False。

    构造：前半段同跌率与挤压无关（均 ~25%）⇒ 前段 p≈0.5；后半段挤压日 100% 同跌
    ⇒ 后段 p≈0；全样本仍显著（挤压 ~62% vs 非挤压 25%）。
    """
    raw = _patch(monkeypatch, tmp_path)
    vix, is_sq = _mk(_N, 29)
    i = np.arange(_N)
    base = (i % 4 == 0)                     # 基础 25%
    codown = np.where(i < _N // 2, base, base | is_sq)
    qqq, tlt = _from_codown(codown)
    _write_raw(raw, _N, qqq, tlt, vix)

    out = vh.verify_h069(None)
    assert out["status"] == "ok"
    assert out["full_p"] < vh.H069_ALPHA        # 全样本显著 …
    assert out["first_half_p"] >= vh.H069_ALPHA  # … 但前段不显著
    assert out["second_half_p"] < vh.H069_ALPHA
    assert out["passed"] is False               # ⇒ 分段不稳健 ⇒ 不成立


# -------------------------------------------------------------- 6. 样本不足
def test_h069_insufficient_when_squeeze_days_below_floor(monkeypatch, tmp_path):
    """挤压期 < 200 日（或半段 < 50 日）⇒ insufficient、passed=None。"""
    n = 240                                 # 20% ⇒ 48 日 < 200
    raw = _patch(monkeypatch, tmp_path)
    vix, is_sq = _mk(n, 31)
    qqq, tlt = _from_codown(is_sq)
    _write_raw(raw, n, qqq, tlt, vix)
    out = vh.verify_h069(None)
    assert out["status"] == "insufficient"
    assert out["passed"] is None
    assert out["full_n_sq"] < vh.H069_MIN_SQUEEZE_DAYS


# --------------------------------------------------------- 7. 接线 & 常量
def test_h069_registered_and_selectable():
    assert vh.HYPOTHESES["H-069"]["kind"] == "custom"
    assert "H-069" in vh.CUSTOM
    assert "H-069" in vh.SUPPORTED


def test_h069_thresholds_are_module_constants():
    """阈值先验写死；分段下限独立于全样本下限。"""
    assert vh.H069_VIX_QUANTILE == 0.80
    assert vh.H069_VIX_JUMP_PCT == 0.20
    assert vh.H069_MIN_SQUEEZE_DAYS == 200
    assert vh.H069_MIN_HALF_SQUEEZE_DAYS == 50
    assert vh.H069_ALPHA == 0.05


def test_h069_marks_nonblind_registration(monkeypatch, tmp_path):
    """🔴 非盲登记必须显式标记（结论强度降级为研究参考）。"""
    raw = _patch(monkeypatch, tmp_path)
    vix, is_sq = _mk(_N, 37)
    qqq, tlt = _from_codown(is_sq)
    _write_raw(raw, _N, qqq, tlt, vix)
    out = vh.verify_h069(None)
    assert out["nonblind_registration"] is True
    assert "非盲登记" in out["note"]
    assert "分段稳健" in out["note"]
