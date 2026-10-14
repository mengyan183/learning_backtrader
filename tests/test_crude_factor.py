# -*- coding: utf-8 -*-
"""原油（大宗商品）候选因子前置：纯函数单元测试（TDD）。

覆盖 docs/notes/2026-10-14-crude-factor-preregistration.md 定义的三个传导机制代理：
  - crude_vol(close, window=20)：原油 20 日已实现波动（年化）
  - crude_equity_corr(crude_close, equity_close, window=60)：滚动相关（突变=传导机制切换）
  - crude_shock_days(crude_ret, threshold=0.05)：单日跳涨 >5% 的事件标记

纪律：全部纯计算（无 I/O、无联网），缺数据/短序列不崩。
"""
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system.factors import crude  # noqa: E402


def _series(vals, start="2020-01-01"):
    idx = pd.bdate_range(start=start, periods=len(vals))
    return pd.Series(vals, index=idx, dtype="float64")


class TestCrudeVol:
    def test_known_realized_vol_annualized(self):
        """① 常收益率序列的 crude_vol 应等于已知解析值（年化）。"""
        # 每日收益率恒为 ±r 交替：日收益样本标准差已知
        r = 0.02
        rets = [r, -r] * 20          # 40 天，20 个完整日收益
        close = [100.0]
        for x in rets:
            close.append(close[-1] * (1.0 + x))
        s = _series(close)
        vol = crude.crude_vol(s, window=20)
        # 末点：20 个日收益 [*rets[-20:]]，交替 ±r ⇒ 样本 std = r*sqrt(20/19)
        expected = r * np.sqrt(20.0 / 19.0) * np.sqrt(252.0)
        assert abs(float(vol.iloc[-1]) - expected) < 1e-9

    def test_window_default_is_20(self):
        """窗口不足 20 处应为 NaN（禁止用不足窗口凑值），第 20 个收益起有值。"""
        close = _series([100.0 + i for i in range(30)])
        vol = crude.crude_vol(close)
        assert vol.iloc[:20].isna().all()
        assert not np.isnan(float(vol.iloc[-1]))

    def test_zero_vol_when_flat(self):
        """价格恒定 ⇒ 波动为 0。"""
        close = _series([50.0] * 30)
        vol = crude.crude_vol(close, window=20)
        assert float(vol.iloc[-1]) == 0.0


class TestCrudeEquityCorr:
    def test_perfectly_correlated_close_to_one(self):
        """② 完全相关（同收益）序列的滚动相关 ≈ 1。"""
        base = [100.0]
        for x in [0.01, -0.02, 0.03, -0.01, 0.02, 0.015, -0.005, 0.02, -0.03, 0.01] * 8:
            base.append(base[-1] * (1.0 + x))
        crude_s = _series(base)
        eq_s = _series([2.0 * v for v in base])       # 同比例变动 ⇒ 收益完全相同
        corr = crude.crude_equity_corr(crude_s, eq_s, window=60)
        assert abs(float(corr.iloc[-1]) - 1.0) < 1e-9

    def test_negative_correlation(self):
        """反向同幅序列（eq 收益 = -crude 收益）⇒ 相关 ≈ -1。"""
        xs = [0.01, -0.02, 0.03, -0.01, 0.02] * 16
        crude_p = [100.0]
        eq_p = [100.0]
        for x in xs:
            crude_p.append(crude_p[-1] * (1.0 + x))
            eq_p.append(eq_p[-1] * (1.0 - x))
        corr = crude.crude_equity_corr(_series(crude_p), _series(eq_p), window=60)
        assert abs(float(corr.iloc[-1]) + 1.0) < 1e-9

    def test_window_default_is_60(self):
        """默认窗口 60：对齐后前 59 个收益点无值，第 60 个收益点起有值。"""
        n = 90
        crude_s = _series([100.0 + (i % 5) for i in range(n)])
        eq_s = _series([200.0 + (i % 7) for i in range(n)])
        corr = crude.crude_equity_corr(crude_s, eq_s)
        # pct_change 后丢首点 ⇒ 89 个收益点；rolling(60) 首个有效点在位置 59
        assert corr.iloc[:59].isna().all()
        assert not np.isnan(float(corr.iloc[-1]))


class TestCrudeShockDays:
    def test_marks_only_above_threshold(self):
        """③ 只标记单日跳涨/跳跌超 5% 的日子。"""
        ret = _series([0.01, 0.06, -0.02, 0.051, -0.052, 0.05, 0.049])
        flags = crude.crude_shock_days(ret, threshold=0.05)
        # 严格 > 0.05：索引 1(0.06)、4(-0.052)、5(0.05?) —— 0.05 不严格大于 ⇒ 不标
        assert list(flags.astype(bool)) == [False, True, False, True, True, False, False]

    def test_threshold_default_is_5pct(self):
        ret = _series([0.051, 0.049])
        flags = crude.crude_shock_days(ret)
        assert list(flags.astype(bool)) == [True, False]

    def test_output_zero_one_float(self):
        """事件标记输出为 0/1 浮点序列，便于进事件研究矩阵。"""
        ret = _series([0.06, 0.0, -0.07])
        flags = crude.crude_shock_days(ret)
        assert flags.dtype == "float64"
        assert set(np.unique(flags)).issubset({0.0, 1.0})


class TestRobustness:
    def test_empty_series_no_crash(self):
        """④ 空序列不崩，返回空序列。"""
        empty = pd.Series([], dtype="float64")
        assert crude.crude_vol(empty).empty
        assert crude.crude_shock_days(empty).empty

    def test_short_series_no_crash(self):
        """短序列（< window）返回全 NaN，不崩。"""
        short = _series([100.0, 101.0, 99.0])
        vol = crude.crude_vol(short, window=20)
        assert len(vol) == 3
        assert vol.isna().all()

    def test_none_input_is_empty(self):
        """None 输入按空序列处理，不崩。"""
        assert crude.crude_vol(None).empty
        assert crude.crude_shock_days(None).empty

    def test_corr_misaligned_index_no_crash(self):
        """两序列索引不齐时按交集对齐，不崩、返回非空或空均可解释。"""
        a = _series([100.0 + i for i in range(80)])
        b = _series([200.0 + i for i in range(80)], start="2020-02-01")
        corr = crude.crude_equity_corr(a, b, window=20)
        assert isinstance(corr, pd.Series)
