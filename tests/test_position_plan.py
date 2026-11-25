# -*- coding: utf-8 -*-
"""杠杆 ETF 建仓/加仓计划（`fg_system/position_plan.py`）。

🔴 **2026-11-25 用户裁定：建仓/加仓规则已废弃并删除** ✗
   `build_plan` / `brief_line` / `has_history` / `history_days` 已从模块移除
   （回测样本外全负、前后半段方向不一致、平均持仓 0.4~1.3%）
   ⇒ 原来 11 条围绕 `build_plan` 的行为测试**一并删除** ✓

⚠️ **保留的 2 条**锁的是**仍被生产使用**的部分：
   `leverage_of`（`risk.py` / 压力测试）· `gap_pct`（建仓间距）✓
"""
from fg_system import position_plan as pp


def test_leverage_comes_from_config_groups():
    """杠杆倍数复用 `config` 的分组 ✓ —— 两处口径不能打架 ✗。"""
    assert pp.leverage_of("YINN") == 3
    assert pp.leverage_of("GDXU") == 3
    assert pp.leverage_of("AXTX") == 2
    assert pp.leverage_of("CRCG") == 2
    assert pp.leverage_of("BTC-USDT") == 1
    assert pp.leverage_of("不认识的") == 1, "未知标的按无杠杆处理，不猜 ✗"


def test_gap_uses_underlying_atr_times_leverage():
    """间距 = 1.2 × ATR20(**正股**) × 杠杆 ✓（纪律 4C.4 口径）。"""
    assert round(pp.gap_pct("YINN", 0.015), 2) == 5.4      # 1.2×1.5%×3
    assert round(pp.gap_pct("AXTX", 0.08), 2) == 19.2      # 1.2×8%×2
    assert pp.gap_pct("YINN", None) is None, "ATR 缺失要返回 None，不能猜 ✗"
