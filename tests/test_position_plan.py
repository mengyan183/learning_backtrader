# -*- coding: utf-8 -*-
"""杠杆 ETF 建仓/加仓计划（`fg_system/position_plan.py`）。

【为什么】2026 三季度财报季复盘：杠杆 ETF 上「越跌越买」是负期望 ✗ ——
3x 从 -50% 回本要 +100%、从 -75% 要 +300% ✗。用户裁定把规则写成可执行代码，
且**浮亏过 -50% 只禁加仓、不清仓** ✓。

参数目前是**初版**，待回测确认 ⇒ 这里锁的是「规则形状」而不是具体数字。
"""
from fg_system import position_plan as pp


def test_leverage_comes_from_config_groups():
    """杠杆倍数复用 `config` 的分组 ✓ —— 两处口径不能打架 ✗。"""
    assert pp.leverage_of("YINN") == 3
    assert pp.leverage_of("GDXU") == 3
    # 2026-10-30 修正：AXTX / CRCG 名称就写着「2倍」，原来错登在 1X ✗
    assert pp.leverage_of("AXTX") == 2
    assert pp.leverage_of("CRCG") == 2
    assert pp.leverage_of("BTC-USDT") == 1
    assert pp.leverage_of("不认识的") == 1, "未知标的按无杠杆处理，不猜 ✗"


def test_gap_uses_underlying_atr_times_leverage():
    """间距 = 1.5 × ATR20(**正股**) × 杠杆 ✓（纪律 4C.4 口径）。"""
    assert round(pp.gap_pct("YINN", 0.015), 2) == 6.75     # 3x
    assert round(pp.gap_pct("AXTX", 0.08), 2) == 24.0      # 2x
    assert pp.gap_pct("YINN", None) is None, "ATR 缺失要返回 None，不能猜 ✗"


def test_blocked_when_coef_not_low_enough():
    """系数没到 -80 ⇒ 不动手 ✓。"""
    p = pp.build_plan(10000, "YINN", 0.015, -70)
    assert p["ok"] is False
    assert "未达" in p["blocked"]


def test_hard_stop_blocks_add_but_never_says_clear():
    """浮亏过 -50% ⇒ **只禁加仓**，且文案不能说「清仓」✗（用户 2026-10-30 裁定）。"""
    p = pp.build_plan(10000, "AXTX", 0.08, -90, held_value=900, pnl_pct=-78)
    assert p["ok"] is False
    assert "禁止加仓" in p["blocked"]
    assert "不清仓" in p["blocked"]
    assert "清仓" in p["blocked"] and "不清仓" in p["blocked"]


def test_first_plus_ladder_fills_single_cap_exactly():
    """首建 + 加仓档位正好填满单标的上限 ✓（6% + 3% + 3% = 12%）。"""
    p = pp.build_plan(10000, "YINN", 0.015, -85)
    total = p["first"] + sum(x["amount"] for x in p["ladder"])
    assert abs(total - p["single_cap"]) <= 1, (total, p["single_cap"])
    assert p["single_cap"] == 1200        # 10000 × 12%
    assert p["first"] == 600              # 10000 × 6%


def test_risk_limit_is_the_tighter_constraint():
    """1% 规则比 12% 更严时，以 1% 规则为准 ✓。"""
    p = pp.build_plan(10000, "AXTX", 0.08, -85, risk_limit=800)
    assert p["single_cap"] == 800


def test_already_at_cap_is_blocked():
    """已持仓超过上限 ⇒ 冻结加仓 ✓（否则与「减仓至上限」互相打架 ✗）。"""
    p = pp.build_plan(10000, "YINN", 0.015, -85, held_value=3000)
    assert p["ok"] is False
    assert "已到单标的上限" in p["blocked"]


def test_brief_line_is_readable():
    """简报行必须能直接读 ✓（含杠杆、金额、间距）。"""
    p = pp.build_plan(10000, "YINN", 0.015, -85)
    ln = pp.brief_line(p)
    assert "YINN ×3" in ln
    assert "首建 $600" in ln
    assert "6.8%" in ln or "6.75" in ln
