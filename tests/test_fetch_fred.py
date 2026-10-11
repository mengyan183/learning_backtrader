# -*- coding: utf-8 -*-
"""FRED 免 key 接入测试（fetch_fred.py）。"""
import os
import sys

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from scripts import fetch_fred as ff


class TestMergeCsv:
    def test_new_file_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ff, "RAW", str(tmp_path))
        n = ff.merge_csv("DFF", ["observation_date,DFF",
                                 "2026-10-01,4.0", "2026-10-02,4.1"])
        assert n == 2
        out = os.path.join(str(tmp_path), "fred_DFF.csv")
        assert os.path.isfile(out)
        assert pd.read_csv(out).shape == (2, 2)

    def test_idempotent_same_date(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ff, "RAW", str(tmp_path))
        ff.merge_csv("DFF", ["observation_date,DFF", "2026-10-01,4.0"])
        n2 = ff.merge_csv("DFF", ["observation_date,DFF", "2026-10-01,4.5"])
        out = pd.read_csv(os.path.join(str(tmp_path), "fred_DFF.csv"))
        assert n2 == 1                 # 同日期覆盖不新增
        assert out.iloc[0]["DFF"] == 4.5  # 后行覆盖

    def test_missing_value_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ff, "RAW", str(tmp_path))
        ff.merge_csv("DFF", ["observation_date,DFF", "2026-10-01,.", "2026-10-02,4.1"])
        out = pd.read_csv(os.path.join(str(tmp_path), "fred_DFF.csv"))
        assert len(out) == 1


class TestRealData:
    def test_dff_file_exists_and_plausible(self):
        p = os.path.join(REPO, "Data", "raw", "fred_DFF.csv")
        assert os.path.isfile(p), "FRED DFF 未下载（需联网先跑 scripts/fetch_fred.py）"
        d = pd.read_csv(p, parse_dates=["observation_date"])
        assert len(d) > 1000                 # 官方全历史（1954 至今）
        assert d["DFF"].between(0, 25).all()  # 利率合理区间（含沃尔克时期 20%）
        assert d.observation_date.max() > pd.Timestamp("2026-10-01")

    def test_t10y2y_file_exists(self):
        p = os.path.join(REPO, "Data", "raw", "fred_T10Y2Y.csv")
        assert os.path.isfile(p)
        t = pd.read_csv(p, parse_dates=["observation_date"])
        assert len(t) > 1000
        assert t.observation_date.max() > pd.Timestamp("2026-10-01")


class TestSeriesRegistry:
    def test_known_series(self):
        assert "DFF" in ff.SERIES and "T10Y2Y" in ff.SERIES

