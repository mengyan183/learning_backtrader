# -*- coding: utf-8 -*-
"""`fg_system/factors/underlying_infer.py` —— 杠杆 ETF 底层自动推断（β 回归）。

要求（2026-10-21 方案 B ✓）：
- **纯函数** ✓ 不联网 ✗（网络在调用方 ✓）
- **只能验证、不能发现** ✗ ⇒ 底层不在候选池 ⇒ 返回 `None` ✓（必须明确 ✗）
- **反向**标的（`SQQQ`）⇒ `beta < 0` ⇒ `direction="反向"` ✓
- 样本不足（< 60 日 ✓）⇒ 拒绝 ✗
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors import underlying_infer as ui


def _series(seed, n=300, drift=0.0005, vol=0.01):
    """造一段几何随机游走收盘价 ✓。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.Series(100 * np.cumprod(1 + rets), index=idx)


def _leveraged(base, k=3.0, seed=7, noise=0.0):
    """把底层收益率放大 k 倍 ⇒ 模拟 3x 杠杆 ETF ✓（可加噪声 ✓）。"""
    r = base.pct_change().fillna(0.0)
    rng = np.random.default_rng(seed)
    r2 = k * r + (rng.normal(0, noise, len(r)) if noise else 0.0)
    return base.iloc[0] * (1 + r2).cumprod()


def test_infer_finds_3x_underlying():
    """3x 杠杆 ⇒ 必须推出 β≈3、R²≈1 ✓。"""
    base = _series(1)
    target = _leveraged(base, 3.0)
    res = ui.infer(target, {"QQQ": base, "SPY": _series(2)})
    assert res and res[0]["symbol"] == "QQQ"
    assert res[0]["beta"] == pytest.approx(3.0, abs=0.15)
    assert res[0]["r2"] > 0.99
    assert res[0]["leverage"] == "3x"
    assert res[0]["direction"] == "正向"


def test_infer_finds_2x_and_1x():
    base = _series(3)
    two = ui.infer(_leveraged(base, 2.0), {"FXI": base})
    assert two[0]["leverage"] == "2x"
    one = ui.infer(_leveraged(base, 1.0), {"IWM": base})
    assert one[0]["leverage"] == "1x"


def test_infer_detects_inverse():
    """反向标的（如 SQQQ）⇒ β < 0 ✓、`direction="反向"` ✓。"""
    base = _series(4)
    inv = _leveraged(base, -3.0)
    res = ui.infer(inv, {"QQQ": base})
    assert res[0]["beta"] < 0
    assert res[0]["direction"] == "反向"
    assert res[0]["leverage"] == "反向"


def test_pick_returns_none_when_underlying_absent():
    """🔴 **只能验证、不能发现** ✗：真底层不在候选池 ⇒ `pick()` 必须 **None** ✓（不得瞎猜 ✗）。

    注意 `infer()` 本身会返回**所有**够样本的候选（按 R² 降序 ✓），
    拒绝逻辑在 `pick()`（`r2 >= 0.90` ✓ + 杠杆倍数已知 ✓）——
    随机游走之间总会有一点相关 ✓，所以不能靠「`infer()` 为空」判定 ✗。
    """
    target = _leveraged(_series(5), 3.0)
    cands = {"SPY": _series(6), "GLD": _series(7)}
    assert ui.pick(target, cands) is None


def test_infer_rejects_short_sample():
    """重叠 < 60 日 ⇒ 拒绝 ✗（R² 无意义 ✓）。"""
    base = _series(8, n=40)
    assert ui.infer(_leveraged(base, 3.0), {"QQQ": base}) == []


def test_pick_requires_high_r2_and_known_leverage():
    """`pick()` 必须同时满足 R² 高 ✓ + 杠杆倍数已知 ✓。"""
    base = _series(9)
    ok = ui.pick(_leveraged(base, 3.0), {"QQQ": base})
    assert ok and ok["symbol"] == "QQQ"

    # 纯噪声 ⇒ 相关性低 ⇒ 不得被选中 ✗
    rng = np.random.default_rng(11)
    noise = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 300)),
                      index=base.index)
    assert ui.pick(noise, {"QQQ": base}) is None


def test_candidates_csv_loads():
    """候选池必须能读出来 ✓ 且非空 ✓（`EWY` 在里面 ✓ —— 这是 `KORU` 的关键 ✓）。"""
    cands = ui.load_candidates()
    assert len(cands) >= 30
    assert "EWY" in cands
    assert "QQQ" in cands and "SPY" in cands

# ------------------------------------- 真实数据回归（2026-10-21 实测通过 ✓）
def _real_prices():
    import os
    from fg_system import config
    p = os.path.join(config.RAW_DIR, "prices.csv")
    if not os.path.exists(p):
        pytest.skip("prices.csv 不存在")
    d = pd.read_csv(p, dtype={"symbol": str}, parse_dates=["date"])
    return {s: d[d["symbol"] == s].set_index("date")["close"].sort_index()
            for s in d["symbol"].unique()}


@pytest.mark.parametrize("lev,expect", [
    ("TQQQ", "QQQ"),      # 3x 纳指 ✓（实测 β=2.956, R²=0.9979 ✓）
    ("YINN", "FXI"),      # 3x 中国大盘 ✓（实测 β=2.934, R²=0.9911 ✓）
    ("SOXL", "SOXX"),     # 3x 半导体 ✓（实测 β=2.947, R²=0.9946 ✓）
])
def test_real_data_recovers_known_mapping(lev, expect):
    """**用真实行情反推已登记映射** ✓ —— 这是方案 B 最重要的自测 ✓。

    若这条挂了 ✗ ⇒ 自动推断**不可信** ✗ ⇒ 必须停下来查 ✓（而不是继续上线 ✗）。
    """
    px = _real_prices()
    if lev not in px or expect not in px:
        pytest.skip("%s / %s 不在 prices.csv" % (lev, expect))
    hit = ui.pick(px[lev], {expect: px[expect]})
    assert hit is not None, "应能推断出 %s -> %s" % (lev, expect)
    assert hit["symbol"] == expect
    assert hit["r2"] >= 0.95
    assert hit["leverage"] == "3x"
