# -*- coding: utf-8 -*-
"""实盘快照对照测试（第 13.2 条）。

`scripts/portfolio_check.py` 不是包内模块，用 importlib 直接加载。
"""
import importlib.util
import pathlib

import pandas as pd
import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "portfolio_check.py"
_spec = importlib.util.spec_from_file_location("portfolio_check", _PATH)
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


def _snap():
    accounts = pd.DataFrame([
        {"date": "2026-09-22", "account": "stock", "net_value": 17202.17,
         "securities_mv": 18183.83, "cash": -981.66},
        {"date": "2026-09-22", "account": "crypto", "net_value": 3013.12,
         "securities_mv": None, "cash": 1832.77},
    ])
    positions = pd.DataFrame([
        {"date": "2026-09-22", "account": "stock", "symbol": "CONL",
         "notional": 3822.00},
        {"date": "2026-09-22", "account": "stock", "symbol": "GDXU",
         "notional": 5588.52},
        {"date": "2026-09-22", "account": "crypto", "symbol": "BTC",
         "notional": 2554.84},
    ])
    return accounts, positions


def test_exposure_uses_notional_not_margin():
    """**核心**：BTC 敞口必须按名义价值 2,554.84 算，不能按保证金 630.34。

    用保证金会把加密暴露从 12.6% 报成 3.1%，**严重低估杠杆**。
    """
    accounts, positions = _snap()
    nav, notional, crypto, equity, cash = pc.exposure(accounts, positions)
    assert nav == pytest.approx(20215.29)
    assert notional == pytest.approx(11965.36), "3822 + 5588.52 + 2554.84"
    assert crypto == pytest.approx(6376.84), "BTC 名义 + CONL（加密标的记在股票账户）"
    assert equity == pytest.approx(5588.52)
    assert cash == pytest.approx(851.11), "-981.66 + 1832.77"


def test_crypto_includes_conl_despite_stock_account():
    """CONL 在股票账户下，但按第 6.3 条属加密「经营 Beta 层」，必须计入加密。"""
    accounts, positions = _snap()
    _, _, crypto, equity, _ = pc.exposure(accounts, positions)
    assert crypto > 3822.00, "CONL 必须被计入加密暴露"
    assert equity == pytest.approx(5588.52), "CONL 不应留在股票暴露里"


def test_cash_can_be_negative():
    """融资账户现金为负是**正常状态**，不得被 clip 成 0——那会掩盖「在用杠杆」。"""
    accounts, positions = _snap()
    accounts.loc[1, "cash"] = 0.0
    _, _, _, _, cash = pc.exposure(accounts, positions)
    assert cash == pytest.approx(-981.66), "负现金必须如实保留"


def test_load_snapshot_picks_latest_date(tmp_path):
    ap = tmp_path / "accounts.csv"
    pp = tmp_path / "positions.csv"
    pd.DataFrame([
        {"date": "2026-08-31", "account": "stock", "net_value": 100.0,
         "securities_mv": 100.0, "cash": 0.0},
        {"date": "2026-09-22", "account": "stock", "net_value": 200.0,
         "securities_mv": 200.0, "cash": 0.0},
    ]).to_csv(ap, index=False)
    pd.DataFrame([
        {"date": "2026-09-22", "account": "stock", "symbol": "GDXU", "notional": 200.0},
    ]).to_csv(pp, index=False)

    a, p = pc.load_snapshot(accounts_path=str(ap), positions_path=str(pp))
    assert len(a) == 1 and a["net_value"].iloc[0] == 200.0, "必须取最新日期"
    assert len(p) == 1


def _snap_with_bet():
    accounts = pd.DataFrame([
        {"date": "2026-09-22", "account": "stock", "net_value": 17202.17,
         "cash": -981.66},
        {"date": "2026-09-22", "account": "crypto", "net_value": 3013.12,
         "cash": 1832.77},
    ])
    positions = pd.DataFrame([
        {"date": "2026-09-22", "account": "stock", "symbol": "GDXU",
         "notional": 5588.52, "bucket": "system"},
        {"date": "2026-09-22", "account": "crypto", "symbol": "BTC",
         "notional": 2554.84, "bucket": "system"},
        {"date": "2026-09-22", "account": "bet", "symbol": "BTC",
         "notional": 3000.0, "bucket": "bet", "margin": 1000.0},
    ])
    return accounts, positions


# ---------------------------------------------------------------- 赌注仓（第 12.24 条）

def test_exposure_excludes_bet_bucket():
    """**核心**：赌注仓不得计入系统暴露，否则会污染第 13.2 的纪律指标。"""
    a, p = _snap_with_bet()
    _, notional, _, _, _ = pc.exposure(a, p)
    assert notional == pytest.approx(5588.52 + 2554.84), "赌注仓的 3000 不得计入"


def test_bet_usage_counts_margin_not_notional():
    """上限约束的是**投入资金（保证金）**，不是名义价值。

    3x 的赌注仓名义可达保证金的 3 倍，但最大损失仍被保证金限定。
    """
    a, p = _snap_with_bet()
    margin, nav, ratio, over = pc.bet_usage(a, p)
    assert nav == pytest.approx(20215.29)
    assert margin == pytest.approx(1000.0), "必须用 margin 而非 notional(3000)"
    assert ratio == pytest.approx(1000.0 / 20215.29)
    assert over is False


def test_bet_usage_flags_over_cap():
    """超限必须被标记 —— 这是赌注仓**唯一**的系统级约束。"""
    a, p = _snap_with_bet()
    p.loc[2, "margin"] = 1500.0               # 7.42% > 5%
    margin, _, ratio, over = pc.bet_usage(a, p)
    assert ratio > pc.BET_CAP and over is True


def test_bet_usage_zero_when_no_bet_rows():
    a, p = _snap_with_bet()
    margin, _, ratio, over = pc.bet_usage(a, p[p["bucket"] == "system"])
    assert (margin, ratio, over) == (0.0, 0.0, False)


def test_bucket_column_is_optional_for_backward_compat():
    """**向后兼容**：缺 `bucket` 列时全部视为 system，不得报错或漏算。"""
    a, p = _snap_with_bet()
    # 去掉 bucket/margin 列，**同时去掉赌注仓那一行**（它靠 account=="bet" 区分；
    # 不能按 symbol 筛——赌注仓的 symbol 也是 BTC，会一起留下）。
    p = p[p["account"] != "bet"].drop(columns=["bucket", "margin"])
    _, notional, _, _, _ = pc.exposure(a, p)
    assert notional == pytest.approx(5588.52 + 2554.84)
    assert pc.bet_usage(a, p)[0] == 0.0


def test_real_snapshot_files_parse_and_are_consistent():
    """**守卫**：真实的 `Data/accounts.csv` / `positions.csv` 必须可解析且自洽。

    实测踩坑：往 `name` 里写半角逗号（`(计划投入,未建仓)`）会把 CSV 列切开，
    `pd.read_csv` 抛 `ParserError: Expected 12 fields, saw 13`。
    用 tmp_path 的测试**抓不到**这个错误（夹具是自己造的），故必须直接读真实文件。
    """
    import os
    from fg_system import config
    if not (os.path.exists(config.ACCOUNTS_PATH)
            and os.path.exists(config.POSITIONS_PATH)):
        pytest.skip("真实快照文件不存在")

    accounts, positions = pc.load_snapshot()
    assert not accounts.empty, "accounts.csv 必须至少有一行"
    assert not positions.empty, "positions.csv 必须至少有一行"
    # 赌注仓行允许 qty/notional 为空（计划投入、未建仓），但 margin 必须有值。
    if "bucket" in positions.columns:
        bet = positions[positions["bucket"] == pc.BET_BUCKET]
        if not bet.empty:
            assert bet["margin"].notna().all(), "赌注仓行必须有 margin"


def test_load_snapshot_by_explicit_date(tmp_path):
    ap = tmp_path / "accounts.csv"
    pp = tmp_path / "positions.csv"
    pd.DataFrame([
        {"date": "2026-08-31", "account": "stock", "net_value": 100.0,
         "securities_mv": 100.0, "cash": 0.0},
        {"date": "2026-09-22", "account": "stock", "net_value": 200.0,
         "securities_mv": 200.0, "cash": 0.0},
    ]).to_csv(ap, index=False)
    pd.DataFrame([
        {"date": "2026-08-31", "account": "stock", "symbol": "GDXU", "notional": 100.0},
    ]).to_csv(pp, index=False)

    a, p = pc.load_snapshot("2026-08-31", accounts_path=str(ap), positions_path=str(pp))
    assert a["net_value"].iloc[0] == 100.0
    assert len(p) == 1
