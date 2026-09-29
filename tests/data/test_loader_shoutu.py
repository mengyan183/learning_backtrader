# -*- coding: utf-8 -*-
"""守猪待兔贪恐指数读取与映射测试（第 12.26 条）。"""
import os

import pandas as pd
import pytest

from fg_system import config
from fg_system.data import loader


def test_load_shoutu_fng_missing_file_returns_empty(tmp_path):
    """**缺文件必须返回空表而不是报错** —— 系统其余部分不依赖它。"""
    out = loader.load_shoutu_fng(str(tmp_path / "nope.csv"))
    assert isinstance(out, pd.DataFrame) and out.empty


def test_load_shoutu_fng_pivots_to_wide(tmp_path):
    p = tmp_path / "s.csv"
    pd.DataFrame({
        "date": ["2026-09-22"] * 3 + ["2026-09-21"] * 2,
        "symbol": ["GDXU", "YINN", "CONL", "GDXU", "YINN"],
        "value": [-83.0, -41.0, 26.0, -80.0, -45.0],
    }).to_csv(p, index=False)
    w = loader.load_shoutu_fng(str(p))
    assert list(w.columns) == ["CONL", "GDXU", "YINN"]
    assert w.index.is_monotonic_increasing
    assert w.loc[pd.Timestamp("2026-09-22"), "GDXU"] == pytest.approx(-83.0)


def test_load_shoutu_fng_empty_file(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("date,symbol,value\n", encoding="utf-8")
    assert loader.load_shoutu_fng(str(p)).empty


# ---------------------------------------------------------------- 映射（先验）

def test_mapping_lands_on_zone_edges():
    """**核心先验**：用户的贪婪线 60 / 恐惧线 −60 必须精确落在 zone 边界 80 / 20。

    若此测试失败，说明映射公式被改坏了——两套口径的同构关系就断了。
    """
    s = pd.Series([config.SHOUTU_GREED_LINE, config.SHOUTU_FEAR_LINE])
    out = loader.shoutu_to_system_scale(s)
    assert out.iloc[0] == pytest.approx(config.ZONE_EDGES[3])   # 60 -> 80
    assert out.iloc[1] == pytest.approx(config.ZONE_EDGES[0])   # -60 -> 20


def test_mapping_endpoints():
    s = pd.Series([-100.0, 0.0, 100.0])
    out = loader.shoutu_to_system_scale(s)
    assert list(out) == pytest.approx([0.0, 50.0, 100.0])


def test_mapping_rejects_out_of_range():
    """越界**必须报错**，不能静默截断——否则会把口径错误伪装成极值信号。"""
    with pytest.raises(loader.DataQualityError):
        loader.shoutu_to_system_scale(pd.Series([120.0]))
    with pytest.raises(loader.DataQualityError):
        loader.shoutu_to_system_scale(pd.Series([-101.0]))


def test_mapping_tolerates_nan():
    out = loader.shoutu_to_system_scale(pd.Series([float("nan"), 0.0]))
    assert pd.isna(out.iloc[0]) and out.iloc[1] == pytest.approx(50.0)


def test_real_shoutu_file_parses_and_is_in_range():
    """**守卫**：真实的 `Data/raw/shoutu_fng.csv` 必须可解析且在量程内。"""
    if not os.path.exists(config.SHOUTU_FNG_PATH):
        pytest.skip("真实守猪待兔文件不存在")
    w = loader.load_shoutu_fng()
    assert not w.empty, "真实文件必须至少有一行"
    loader.shoutu_to_system_scale(w.stack())      # 越界会抛异常
