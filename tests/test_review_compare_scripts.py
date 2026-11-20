# -*- coding: utf-8 -*-
"""第 12.58 / 12.59 条 A/B 脚本的守卫（2026-11-20 三轮评审后补）。

为什么要有：这两个脚本会**直接决定**规则是否采纳，
若它们本身口径写错（例如冷却函数被污染、限幅后空洞被填平），
结论会静默反向 ⇒ 必须有能咬人的行为断言 ✓
"""
import numpy as np
import pandas as pd

from fg_system import config
from fg_system.signal import legacy
from fg_system.signal import portfolio as sig
from scripts import cooldown_compare as cdc
from scripts import putcall_ffill_compare as pfc


def test_cooldown_gap_is_trading_days():
    """周五→周三 = 3 个交易日；周五→下周五 = 5 个交易日。

    v1（legacy）与 v2（portfolio）必须一致 —— 否则两轨执行口径会分叉 ✗
    """
    assert sig.cooldown_gap("2024-01-05", "2024-01-10") == 3
    assert sig.cooldown_gap("2024-01-05", "2024-01-12") == 5
    assert legacy.cooldown_gap("2024-01-05", "2024-01-10") == 3


def test_cooldown_unit_changes_ops():
    """同一条信号：自然日放行、交易日挡住 ⇒ 操作次数必须不同。

    这是第 12.59 条的**核心断言** —— 若两种口径算出一样的操作数，
    说明脚本没真正切换口径（例如 patch 未生效）✗
    """
    idx = pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"])
    target = pd.Series([0.5, 0.5, 0.5, 0.0], index=idx)
    old = cdc._simulate(target, cdc._gap_calendar)
    new = cdc._simulate(target, cdc._gap_trading)
    assert old["ops"] == 2, "自然日：01-10 距 01-05 满 5 天 ⇒ 应放行"
    assert new["ops"] == 1, "交易日：01-10 距 01-05 仅 3 天 ⇒ 应挡住"
    assert "2024-01-10" not in old["blocked_dates"]
    assert "2024-01-10" in new["blocked_dates"]


def test_simulate_restores_gap_fn():
    """模拟必须恢复原函数，不能污染生产口径。"""
    before = sig.cooldown_gap
    idx = pd.to_datetime(["2024-01-05", "2024-01-10"])
    cdc._simulate(pd.Series([0.5, 0.0], index=idx), cdc._gap_calendar)
    assert sig.cooldown_gap is before


def test_limited_raw_nan_after_long_gap(monkeypatch):
    """限幅后：超过 limit 的空洞必须留 NaN（不是被 ffill 填平）。

    这是第 12.58 条的**核心断言** —— 若限幅没生效，空洞会被填平，
    脚本就会把「因子被删除」误报成「无影响」✗
    """
    monkeypatch.setattr(config, "RANK_WINDOW", 3)
    idx = pd.date_range("2024-01-01", periods=12, freq="B")
    vals = [0.9, 1.0, 0.8] + [np.nan] * 6 + [1.1, 1.2, 1.3]
    wide = pd.DataFrame({("PUT_CALL", "ratio"): vals}, index=idx)
    out = pfc._limited_raw(5)(None, wide)
    assert pd.isna(out.iloc[8]), "第 6 个缺失日已超限 ⇒ 必须保持 NaN"
    assert pd.notna(out.iloc[-1]), "空洞后重新积累满窗口 ⇒ 必须有值"


def test_limited_raw_missing_column():
    """缺 PUT_CALL 列 ⇒ 全 NaN（不崩、不猜）。"""
    wide = pd.DataFrame({"x": [1.0, 2.0]},
                        index=pd.date_range("2024-01-01", periods=2))
    out = pfc._limited_raw(5)(None, wide)
    assert out.isna().all()
