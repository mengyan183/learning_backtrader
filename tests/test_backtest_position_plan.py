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


def test_load_marks_source_and_fng_wins(tmp_path, monkeypatch):
    """`_load()` 必须**标记来源**，且重叠日 fng 覆盖 history ✓。

    🔴 2026-11-24：服务端 `stock_emotion/history` 返回 `data: []`（源断）✗
       ⇒ 10-14 之后只剩 `fng`（本地 06:30 采样）✗
       ⇒ spec §5.4 明令「两口径不要混用」，但此处**被迫混用** ✗
       ⇒ 必须能追溯每一行来自哪个源，报告才能显式告警 ✓
    """
    bt = _load_bt()
    raw = tmp_path / "Data" / "raw"
    raw.mkdir(parents=True)

    pd.DataFrame({
        "date": pd.to_datetime(["2026-10-13", "2026-10-14", "2026-10-15"]),
        "symbol": ["YINN"] * 3,
        "open": [1.0] * 3, "high": [1.0] * 3, "low": [1.0] * 3,
        "close": [10.0, 11.0, 12.0], "volume": [1, 1, 1],
    }).to_csv(raw / "prices.csv", index=False)

    pd.DataFrame({
        "date": pd.to_datetime(["2026-10-13", "2026-10-14"]),
        "symbol": ["YINN", "YINN"],
        "score": [-50.0, -60.0], "price": [10.0, 11.0],
    }).to_csv(raw / "shoutu_history.csv", index=False)

    pd.DataFrame({
        "date": pd.to_datetime(["2026-10-14", "2026-10-15"]),
        "symbol": ["YINN", "YINN"],
        "value": [-70.0, -80.0], "price": [11.0, 12.0],
    }).to_csv(raw / "shoutu_fng.csv", index=False)

    monkeypatch.setattr(bt, "REPO", str(tmp_path))
    _px, st = bt._load()

    assert "src" in st.columns, "必须标记来源，否则报告无法告警 ✗"
    got = st.set_index("date")["value"].to_dict()
    srcs = st.set_index("date")["src"].to_dict()
    d13, d14 = pd.Timestamp("2026-10-13"), pd.Timestamp("2026-10-14")
    assert got[d13] == -50.0 and srcs[d13] == "history"
    assert got[d14] == -70.0 and srcs[d14] == "fng", "重叠日必须 fng 胜 ✗"
    assert srcs[pd.Timestamp("2026-10-15")] == "fng"


def test_src_stats_feeds_json():
    """`_src_stats` 必须给出每源的行数与日期范围 ✓（进 `--json`）。

    🔴 2026-11-24：口径混用若只打 stdout，JSON 被别的脚本引用时
       来源信息就丢了 ✗ ⇒ 读者无法判断是「权威日值」还是「06:30 采样」✗
    """
    bt = _load_bt()
    st = pd.DataFrame({
        "date": pd.to_datetime(["2026-10-13", "2026-10-14", "2026-10-15"]),
        "symbol": ["YINN"] * 3,
        "value": [-50.0, -70.0, -80.0],
        "src": ["history", "fng", "fng"],
    })
    s = bt._src_stats(st)
    assert s["history"]["rows"] == 1
    assert s["history"]["from"] == "2026-10-13"
    assert s["fng"]["rows"] == 2
    assert s["fng"]["to"] == "2026-10-15"

    # 无 src 列 ⇒ 空 dict（向后兼容旧调用）✓
    assert bt._src_stats(st.drop(columns=["src"])) == {}


def _mk_two_sources(tmp_path):
    raw = tmp_path / "Data" / "raw"
    raw.mkdir(parents=True)
    pd.DataFrame({
        "date": pd.to_datetime(["2026-10-13", "2026-10-14", "2026-10-15"]),
        "symbol": ["YINN"] * 3,
        "open": [1.0] * 3, "high": [1.0] * 3, "low": [1.0] * 3,
        "close": [10.0, 11.0, 12.0], "volume": [1, 1, 1],
    }).to_csv(raw / "prices.csv", index=False)
    pd.DataFrame({
        "date": pd.to_datetime(["2026-10-13", "2026-10-14"]),
        "symbol": ["YINN", "YINN"],
        "score": [-50.0, -60.0], "price": [10.0, 11.0],
    }).to_csv(raw / "shoutu_history.csv", index=False)
    pd.DataFrame({
        "date": pd.to_datetime(["2026-10-14", "2026-10-15"]),
        "symbol": ["YINN", "YINN"],
        "value": [-70.0, -80.0], "price": [11.0, 12.0],
    }).to_csv(raw / "shoutu_fng.csv", index=False)


def test_load_source_filter_keeps_overlap(tmp_path, monkeypatch):
    """`--source history` 必须**保留重叠日** ✓ —— 否则模拟不出「没有 fng 的世界」。

    🔴 若在去重**之后**过滤，重叠日（10-14）已被 fng 覆盖 ⇒
       `--source history` 会凭空少掉那天 ⇒ 对照实验的样本区间被人为截短 ✗
    """
    bt = _load_bt()
    _mk_two_sources(tmp_path)
    monkeypatch.setattr(bt, "REPO", str(tmp_path))

    _px, h = bt._load("history")
    assert set(h["src"]) == {"history"}, h["src"].tolist()
    assert len(h) == 2, "重叠日 10-14 必须保留在 history 里 ✗"

    _px, f = bt._load("fng")
    assert set(f["src"]) == {"fng"}
    assert len(f) == 2

    _px, a = bt._load("all")
    assert set(a["src"]) == {"history", "fng"}
    assert len(a) == 3, "去重后应为 3 行（10-13/14/15）✗"
