# -*- coding: utf-8 -*-
"""MT-76 供数测试：fetch_baa10y_avail.py 的 available_date 不变量（防 lookahead）。

核心不变量（供评测用，非生产权重）：
- available_date 恒 = date + lag_days（自然日），且 available_date > date（绝不把未发布值提前）；
- 升序、无空值、value 可转 float。
"""
import os
import sys

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from scripts import fetch_baa10y_avail as fb


class TestBuildRows:
    def test_available_date_equals_plus_lag_and_never_past(self):
        rows = [("2026-10-21", 1.44), ("2026-10-23", 1.47), ("2026-10-22", 1.46)]
        built = fb.build_rows(rows, lag_days=5)
        dates = [b[0] for b in built]
        assert dates == sorted(dates)            # 输出升序（输入乱序也排好）
        for d, v, avail in built:
            lag = (pd.Timestamp(avail) - pd.Timestamp(d)).days
            assert lag == 5
            assert pd.Timestamp(avail) > pd.Timestamp(d)   # 🔴 不允许 available_date <= date

    def test_missing_value_filtered_and_float(self):
        rows = [("2026-10-21", 1.44), ("2026-10-22", "."), ("2026-10-23", 1.47)]
        # build_rows 假定上游已过滤 "."；这里只校验合法值转 float、无 NaN
        built = fb.build_rows([r for r in rows if r[1] != "."], lag_days=3)
        assert len(built) == 2
        assert all(isinstance(v, float) for _, v, _ in built)
        assert all(pd.notna(v) for _, v, _ in built)

    def test_custom_lag(self):
        built = fb.build_rows([("2026-01-01", 2.0)], lag_days=4)
        assert built[0][2] == "2026-01-05"


class TestRealFile:
    """真实供数文件（联网跑过 fetch_baa10y_avail.py 后存在）；缺失则跳过，不阻塞。"""

    def test_real_file_invariants(self):
        p = os.path.join(REPO, "Data", "raw", "fred_baa10y.csv")
        if not os.path.isfile(p):
            pytest.skip("fred_baa10y.csv 未下载（需先联网跑供数脚本）")
        df = pd.read_csv(p)
        assert list(df.columns) == ["date", "value", "available_date"]
        d, a = pd.to_datetime(df.date), pd.to_datetime(df.available_date)
        assert (a > d).all()                     # 🔴 每行 available_date 都晚于观测日
        assert d.is_monotonic_increasing
        assert not d.duplicated().any()
        assert df.value.notna().all()
        assert df.value.between(0, 15).all()     # Baa 利差合理区间
