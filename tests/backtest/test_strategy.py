# -*- coding: utf-8 -*-
"""回测策略测试（§11.2）。"""
import backtrader as bt
import pandas as pd
import pytest

from fg_system import config, shoutu_analysis
from fg_system.backtest import feed, strategy
from fg_system.signal import portfolio


def _features(n=60):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e6,
        "fg_index": 50.0, "zone": 2, "target_position": [0.0] * 30 + [0.70] * 30,
    }, index=idx)
    return df


def test_feed_exposes_target_position_line():
    data = feed.FgPandasData(dataname=_features())
    assert hasattr(data.lines, "target_position")
    assert hasattr(data.lines, "fg_index")


def test_strategy_only_reads_target_position():
    """策略执行后仓位应跟随 target_position（T 日开盘执行 T-1 信号）。"""
    cerebro = bt.Cerebro()
    cerebro.adddata(feed.FgPandasData(dataname=_features()))
    cerebro.addstrategy(strategy.FgStrategy)
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(commission=0.0003)
    result = cerebro.run()
    strat = result[0]
    assert strat.order_count >= 1
    assert strat.executed_positions, "应至少执行一次调仓"


def test_strategy_skips_nan_target():
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                       "volume": 1e6, "fg_index": float("nan"), "zone": 2,
                       "target_position": float("nan")}, index=idx)
    cerebro = bt.Cerebro()
    cerebro.adddata(feed.FgPandasData(dataname=df))
    cerebro.addstrategy(strategy.FgStrategy)
    result = cerebro.run()
    assert result[0].order_count == 0


# ---------------------------------------------------------------- 一致性（spec §7）
# spec §7 要求："有一条一致性测试断言 `replay_exit_path` 与 `FgStrategy` 的调整规则等价"。
# 下面的用例**真实跑 Cerebro + FgStrategy**（不是再调一次 next_position 的同义反复）：
# 唯一实现是 `portfolio.next_position`，但"两者共用同一函数"只是**构造保证** ——
# 若将来有人只改一边（比如在 FgStrategy 里加特判），构造保证会悄悄失效，
# 故这里用**实际仓位路径逐日比对**把它钉住。
#
# 【`_pending` 语义实测结论（探针实测，非推测）】
# 市场单在**下一根 bar 的 `notify_order` 阶段**就走到 Completed（同一根 bar 内
# Submitted→Accepted→Completed 全发生），因此 `_pending` 在该 bar 的 `next()`
# **之前**已被清零 ⇒ **不跳 bar**，策略每根 bar 都做决策 ⇒
# 与 `replay_exit_path`（每日都决策）**逐日严格相等**。
# 实测：bar 0 下单 → bar 1 notify 里 Completed → bar 1 的 next() 正常决策。


class _RecordingFg(strategy.FgStrategy):
    """**只加记录、不改决策**：`next()` 全部走父类实现，返回后追加真实仓位。

    这里不是 mock/桩 —— `super().next()` 是真正的 `FgStrategy` 决策逻辑；
    记录只是为了拿到逐 bar 的仓位路径（`executed_positions` 只记变化点，不够）。
    """

    def __init__(self):
        super().__init__()
        self.position_path = []

    def next(self):
        super().next()
        self.position_path.append(self.current_position)


def _branch_targets():
    """覆盖**全部分支**的目标序列（阈值/限幅值从 config 读，不硬编码）：

    - 限幅加仓（差 > `MAX_SINGLE_ADJUST`）⇒ 需多日才到 0.90；
    - `|差| < REBALANCE_THRESHOLD`（0.90 的阈值内微调）⇒ **不动**；
    - NaN（warmup 语义）⇒ **保持不动**；
    - 清仓（target = 0）⇒ 限幅下调；
    - 再加仓到 0.50、再清仓 ⇒ 覆盖清仓后重开。
    """
    thr = config.REBALANCE_THRESHOLD
    mx = config.MAX_SINGLE_ADJUST
    # 先定一个"远高于单次上限"的满仓目标，确认要**多日**才到位（限幅分支）。
    full = min(1.0, mx * 3.0)
    # 阈值内微调：离上一步 < thr ⇒ 不动。
    near = full - thr / 2.0
    # 目标 > 现状的加仓；target=0 的清仓（限幅下调）；清仓后重开到 mid。
    mid = min(1.0, mx * 2.0) - thr / 2.0
    return [full, full, full, full, near, float("nan"),
            0.0, mid, mid, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _targets_df(vals):
    idx = pd.date_range("2024-01-01", periods=len(vals), freq="B")
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                         "volume": 1e6, "fg_index": 50.0, "zone": 2,
                         "target_position": vals}, index=idx)


def _run_recording(vals):
    cerebro = bt.Cerebro()
    cerebro.adddata(feed.FgPandasData(dataname=_targets_df(vals)))
    cerebro.addstrategy(_RecordingFg)
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(commission=0.0003)
    return cerebro.run()[0]


def _expected_replay(vals):
    """正确实现下的期望路径（`p0` = `FgStrategy` 的初始仓位 0.0）。"""
    idx = pd.date_range("2024-01-01", periods=len(vals), freq="B")
    return shoutu_analysis.replay_exit_path(
        pd.Series(vals, index=idx), p0=0.0).tolist()


def _assert_equivalent(strat_path, expected):
    """等价断言 —— 抽成函数，好让"变异检测"用例直接复用它。"""
    assert strat_path == expected, \
        "FgStrategy 实际路径 %r != replay_exit_path %r" % (strat_path, expected)


def test_fgstrategy_position_path_equals_replay_exit_path():
    """真实跑 Cerebro + FgStrategy 的逐 bar 仓位 == `replay_exit_path`（逐日严格相等）。

    实测 `_pending` **不跳 bar**（见文件顶部说明）⇒ 用**严格相等**，不放宽。
    """
    vals = _branch_targets()
    strat = _run_recording(vals)
    assert strat.order_count >= 3, "应至少有加仓 / 清仓 / 再清仓几次调仓"
    _assert_equivalent(strat.position_path, _expected_replay(vals))


def test_equivalence_test_detects_a_wrong_rule(monkeypatch):
    """**变异验证（常驻）**：把规则换成错误实现 ⇒ 上面的等价断言**必须失败**。

    否则"等价测试"可能因为写法太弱（比较同义反复 / 放宽断言）而永远通过。
    这里用错误实现（**忽略阈值 + 不限幅**）对**正确实现的期望值**下断言，
    证明等价的"逐日相等"真的有牙齿。
    """
    vals = _branch_targets()
    expected = _expected_replay(vals)          # ⚠️ 必须在 patch **之前**算

    def wrong_next_position(current, target):
        if target != target:                   # NaN
            return current
        return max(0.0, min(1.0, target))      # 忽略阈值 + 不限幅

    monkeypatch.setattr(portfolio, "next_position", wrong_next_position)
    strat = _run_recording(vals)
    with pytest.raises(AssertionError):
        _assert_equivalent(strat.position_path, expected)
