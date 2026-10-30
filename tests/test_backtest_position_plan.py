# -*- coding: utf-8 -*-
"""`scripts/backtest_position_plan.py` 的模拟逻辑（2026-10-30）。

【为什么】回测脚本本身也会错 ✗ —— 如果「加仓/止损/卖出」的判定写反了，
跑出来的结论会误导参数选择 ✗。这里用**合成行情**把四条关键行为钉死 ✓。
"""
import importlib.util
import os

import pandas as pd

from fg_system import config


def _load_bt():
    spec = importlib.util.spec_from_file_location(
        "backtest_position_plan",
        os.path.join(config.ROOT, "scripts", "backtest_position_plan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk(days=80, start_px=100.0, step=-1.0):
    """造一段单调下跌的行情 + 恒为 -90 的系数 ✓（`fixed` 间距，不依赖 ATR）。"""
    dates = pd.date_range("2026-01-01", periods=days, freq="D")
    px = start_px + step * pd.Series(range(days), index=dates)
    px = px.clip(lower=5.0)
    rows = [{"date": d, "symbol": "YINN", "open": v, "high": v, "low": v,
             "close": v} for d, v in px.items()]
    st = [{"date": d, "symbol": "YINN", "value": -90.0} for d in dates]
    return pd.DataFrame(rows), pd.DataFrame(st)


def test_builds_then_stops_at_single_cap():
    """跌够就加仓，但**到单标的上限就停** ✓ —— 不许无限加 ✗。"""
    bt = _load_bt()
    px, st = _mk()
    v = {"single_cap": 0.12, "first": 0.06, "adds": (0.03, 0.03),
         "entry": -80.0, "hard_stop": None, "atr_k": 0.0,
         "gap_mode": "fixed", "gap_fixed": 10.0}

    r = bt._simulate(px, st, "YINN", v)

    assert r is not None
    # 首建 + 2 档 = 3 次买入，之后到上限就停 ✓
    assert r["n_buys"] == 3, "应买入 3 次（首建+2 档），实际 %d ✗" % r["n_buys"]
    assert r["max_held_pct"] <= 12.5, \
        "持仓超过单标的上限（%.1f%%）✗" % r["max_held_pct"]


def test_hard_stop_blocks_further_adds():
    """浮亏过 `hard_stop` ⇒ **禁止加仓** ✓（不清仓 ✓）。"""
    bt = _load_bt()
    px, st = _mk()
    v = {"single_cap": 0.20, "first": 0.06,
         "adds": (0.03, 0.03, 0.03, 0.03), "entry": -80.0,
         "hard_stop": -0.10, "atr_k": 0.0,
         "gap_mode": "fixed", "gap_fixed": 10.0}

    r = bt._simulate(px, st, "YINN", v)

    # 首建后价格继续跌 ⇒ 很快触发 -10% 硬线 ⇒ 只有首建那一次买入 ✓
    assert r["n_buys"] == 1, "硬止损没拦住加仓（买了 %d 次）✗" % r["n_buys"]


def test_sells_when_coef_reaches_sell_line():
    """系数 ≥ 卖出线 ⇒ 清仓 ✓（卖出后持仓归零）。"""
    bt = _load_bt()
    px, st = _mk()
    # 后半段系数拉高到 90 ⇒ 必然超过 3x 的卖出线 50 ✓
    st.loc[st.index[40:], "value"] = 90.0
    v = {"single_cap": 0.12, "first": 0.06, "adds": (0.03, 0.03),
         "entry": -80.0, "hard_stop": None, "atr_k": 0.0,
         "gap_mode": "fixed", "gap_fixed": 10.0}

    r = bt._simulate(px, st, "YINN", v)

    assert r["n_ops"] > r["n_buys"], "没有卖出记录 ✗"
    assert r["final_eq"] > 0


def test_gap_controls_add_spacing():
    """间距越大 ⇒ 加仓次数越少 ✓（间距是「别买太密」的旋钮）。"""
    bt = _load_bt()
    px, st = _mk(days=120, step=-0.8)
    base = {"single_cap": 0.30, "first": 0.06,
            "adds": (0.03, 0.03, 0.03, 0.03), "entry": -80.0,
            "hard_stop": None, "atr_k": 0.0, "gap_mode": "fixed"}

    near = bt._simulate(px, st, "YINN", dict(base, gap_fixed=5.0))
    far = bt._simulate(px, st, "YINN", dict(base, gap_fixed=25.0))

    assert near["n_buys"] > far["n_buys"], \
        "间距 25%% 的加仓次数（%d）应少于 5%%（%d）✗" % (far["n_buys"], near["n_buys"])


def test_variants_are_defined():
    """四个变体必须齐全 ✓ —— A 初版 / B 保守 / C 激进 / D 对照。"""
    bt = _load_bt()
    assert set(bt.VARIANTS) == {"A_初版", "B_保守", "C_激进", "E_候选", "D_对照"}
    # 2026-10-30：AXTX / CRCG 无服务端历史 ⇒ 默认排除 ✓
    assert "AXTX" not in bt.SYMBOLS and "CRCG" not in bt.SYMBOLS
    for v in bt.VARIANTS.values():
        assert "single_cap" in v and "first" in v and "entry" in v
