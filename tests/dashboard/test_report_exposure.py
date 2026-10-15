# -*- coding: utf-8 -*-
"""跨平台口径修正：`_account_exposure` / `_deviation_line`（方案 C，只报事实）。

背景（用户 2026-09-22 真实数据）：持仓分**两个平台**——富途（stock，已用融资）
+ OKX（crypto，有现金）。此前 `_deviation_line` **跨平台混算** ✗：分子为
**两平台市值合计**、分母为**富途净值** ⇒ 偏高（120.6% ✗，应为 102.6% ✓）。

本文件用 09-22 那组真实数字锁住「分平台 + 合计」口径。
"""
import numpy as np
import pandas as pd

from fg_system.dashboard import report

# ---- 2026-09-22 真实快照（用户实测） -------------------------------------
STOCK_MV = 18187.07      # 富途持仓市值合计
CRYPTO_MV = 2554.03      # OKX 持仓市值合计
STOCK_NET = 17202.17     # 富途净值（cash = -981.66 ⇒ 已用融资）
CRYPTO_NET = 3012.19     # OKX 净值（有现金）
MODEL_DATE = "2026-10-14"
SNAP_DATE = "2026-09-22"


def _features(target=0.45):
    """模型目标仓位序列，模型数据日 = 2026-10-14（与持仓快照日不同 ✓）。"""
    idx = pd.to_datetime(["2026-10-13", MODEL_DATE])
    return pd.DataFrame({"target_position": [target - 0.01, target]}, index=idx)


def _positions(crypto_mv=CRYPTO_MV):
    return pd.DataFrame([
        {"date": SNAP_DATE, "account": "stock", "symbol": "TQQQ",
         "market_value": STOCK_MV},
        {"date": SNAP_DATE, "account": "crypto", "symbol": "BTC-USDT",
         "market_value": crypto_mv},
    ])


def _accounts():
    return pd.DataFrame([
        {"date": SNAP_DATE, "account": "stock",
         "net_value": STOCK_NET, "cash": -981.66},
        {"date": SNAP_DATE, "account": "crypto",
         "net_value": CRYPTO_NET, "cash": CRYPTO_NET},
    ])


# ---- 用例 1：两平台各一行 + 合计 = Σmv/Σnet（容差 0.1） -------------------
def test_deviation_line_two_platforms_and_combined_total():
    line = report._deviation_line(_features(), _positions(), None, _accounts())
    # 合计 = (18187.07 + 2554.03) / (17202.17 + 3012.19) = 102.6%
    assert "合计 102.6%" in line
    assert "富途 105.7%" in line
    assert "OKX 84.8%" in line
    # 混算的旧值 120.6% 绝不能出现
    assert "120.6" not in line


def test_account_exposure_ratios():
    exp = report._account_exposure(_accounts(), _positions())
    assert abs(exp["stock"]["ratio"] * 100 - 105.7) < 0.1
    assert abs(exp["crypto"]["ratio"] * 100 - 84.8) < 0.1
    assert exp["stock"]["mv"] == STOCK_MV
    assert exp["crypto"]["net"] == CRYPTO_NET


# ---- 用例 2：富途 cash = -981.66 ⇒ 渲染串含「含融资」 ---------------------
def test_deviation_line_marks_margin_on_negative_cash():
    line = report._deviation_line(_features(), _positions(), None, _accounts())
    assert "含融资" in line
    assert "-981.66" in line


# ---- 用例 3：market_value 有 NaN ⇒ 该平台「数据不全」且不崩 ---------------
def test_nan_market_value_flags_account_instead_of_silent_skip():
    """锁住「不静默跳过 ✗」：NaN 会让该平台判为数据不全，
    **不得**用 sum() 默认 skipna 把 NaN 丢掉而得出偏小的分子 ✗。"""
    pos = _positions(crypto_mv=float("nan"))
    exp = report._account_exposure(_accounts(), pos)
    assert exp["crypto"]["mv"] is None
    assert exp["crypto"]["ratio"] is None
    line = report._deviation_line(_features(), pos, None, _accounts())
    assert isinstance(line, str) and line          # 不崩 ✓
    assert "OKX 数据不全" in line
    # 该平台的 NaN 未被静默计入合计（合计退回仅富途完整数据）
    assert "合计 105.7%" in line


# ---- 用例 4：只有富途（无 crypto 行）⇒ 正常渲染、不崩 ---------------------
def test_only_stock_platform_renders():
    pos = pd.DataFrame([
        {"date": SNAP_DATE, "account": "stock", "symbol": "TQQQ",
         "market_value": STOCK_MV},
    ])
    acc = pd.DataFrame([
        {"date": SNAP_DATE, "account": "stock",
         "net_value": STOCK_NET, "cash": -981.66},
    ])
    line = report._deviation_line(_features(), pos, None, acc)
    assert isinstance(line, str)
    assert "富途 105.7%" in line
    assert "合计 105.7%" in line
    assert "OKX" not in line


# ---- 用例 5：两个日期都在 --------------------------------------------------
def test_both_dates_present():
    line = report._deviation_line(_features(), _positions(), None, _accounts())
    assert MODEL_DATE in line      # 模型数据日
    assert SNAP_DATE in line       # 持仓快照日


# ---- 用例 6：无祈使句（只报事实） -----------------------------------------
def test_no_imperative_wording():
    line = report._deviation_line(_features(), _positions(), None, _accounts())
    for w in ("应", "该", "建议", "必须", "减仓", "加仓", "清仓", "止损"):
        assert w not in line, "出现祈使词：%s" % w


# ---- 补齐：全部平台数据不全 ⇒ 退回「暂不比对」（不崩） ---------------------
def test_all_accounts_incomplete_falls_back():
    pos = _positions(crypto_mv=float("nan"))
    acc = pd.DataFrame(columns=["date", "account", "net_value", "cash"])
    line = report._deviation_line(_features(), pos, None, acc)
    assert "暂不比对" in line


# ---- 补齐：逐标的占比分母用「所属平台」净值（BTC 不是 14.8%） --------------
def test_per_symbol_ratio_uses_own_account_net(monkeypatch):
    """`_holdings_block` 逐标的占比：BTC 属于 OKX ⇒ 分母应为 OKX 净值
    （2554.03 / 3012.19 = 84.8% ✓），而非富途净值的 14.8% ✗。"""
    latest = _positions()
    acc = _accounts()
    exp = report._account_exposure(acc, latest)
    # BTC 行所属平台 = crypto ⇒ 用 crypto net
    btc = latest[latest["symbol"] == "BTC-USDT"].iloc[0]
    btc_net = exp[str(btc["account"]).strip()]["net"]
    assert abs(btc["market_value"] / btc_net * 100 - 84.8) < 0.1
    # 反证：旧口径（一律除富途 net）会得到 14.8%
    assert abs(btc["market_value"] / STOCK_NET * 100 - 14.8) < 0.1
