# -*- coding: utf-8 -*-
"""S-4 守卫：`without_trend` 的 blocked 掩码必须与**已 shift** 的 target_position 对齐。

背景（团队评审 2026-10-12）：
- `pipeline.py:114` 把 `target_position` 整体 `shift(1)`（T 日执行 T-1 收盘信号）
- `pipeline.py:673` 的 `trend_blocked` **未** shift
⇒ 原实现 `blocked = out["trend_blocked"]` 直接对齐 ⇒ **错位一天**：
用 T 日的阻断标记去还原「代表 T-1 信号」的仓位，归因表系统性偏移，
而 `verdict()` 据此判断趋势过滤是否有用、进而决定是否回退核心仓上限。

修法：`blocked = out["trend_blocked"].shift(1)`。
本测试若把 shift 去掉会立刻失败（判别力来自"打折仓位落在被阻断信号的后一天"）。
"""
import pandas as pd
import pytest

from fg_system import config
from fg_system.backtest import attribution


def test_blocked_mask_aligns_with_shifted_target():
    """D2 信号被阻断 ⇒ 打折仓位出现在 **D3**（因 target_position 已 shift(1)），
    还原也必须作用在 D3，而不是 D2。"""
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    f = pd.DataFrame({
        # D3 = 0.25 即「D2 被阻断后打折执行」的结果（0.5 × FACTOR）
        "target_position": [0.5, 0.5, 0.25, 0.5, 0.5],
        "trend_blocked": [False, True, False, False, False],   # D2 信号被阻断
    }, index=idx)

    out = attribution.without_trend(f)

    assert out.loc[idx[2], "target_position"] == pytest.approx(0.5), (
        "被阻断信号对应的执行日（D3）未被还原 ⇒ blocked 与 target_position 错位")
    assert out.loc[idx[1], "target_position"] == pytest.approx(0.5), (
        "信号日（D2）本身不该被改动")


def test_no_block_column_returns_copy_unchanged():
    """没有 trend_blocked 列时原样返回（既有契约）。"""
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    f = pd.DataFrame({"target_position": [0.5, 0.5, 0.5]}, index=idx)
    out = attribution.without_trend(f)
    assert list(out["target_position"]) == [0.5, 0.5, 0.5]


def test_restore_is_capped_at_one():
    """还原值上限 1.0（既有契约）。"""
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    f = pd.DataFrame({
        "target_position": [0.5, 0.5, 0.9],       # D3 已 shift 后的值
        "trend_blocked": [True, False, False],    # D1 阻断 ⇒ 作用于 D2
    }, index=idx)
    out = attribution.without_trend(f)
    assert out.loc[idx[1], "target_position"] <= 1.0 + 1e-12
    assert out.loc[idx[1], "target_position"] == pytest.approx(
        min(0.5 / config.TREND_FILTER_FACTOR, 1.0))
