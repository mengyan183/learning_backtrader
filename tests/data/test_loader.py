# -*- coding: utf-8 -*-
"""数据加载测试：日期规范化、升序、缺口检测、异常跳变检测。"""
import io
import os
import re

import pandas as pd
import pytest

from fg_system import config
from fg_system.data import loader


def _write(tmp_path, text, name="prices.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_normalize_dates_handles_mm_dd_yyyy_and_sorts_ascending(tmp_path):
    """Nasdaq 原始格式 MM/DD/YYYY 且降序，必须转成 YYYY-MM-DD 升序。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/03/2024,QQQ,400,401,399,400.5,1000\n"
        "01/02/2024,QQQ,398,400,397,399.0,900\n"
    )
    # 夹具只含 QQQ，显式声明"本次不校验标的覆盖性"（覆盖性由真实数据测试负责）
    df = loader.load_prices(_write(tmp_path, csv), required_symbols=[])
    assert df["date"].is_monotonic_increasing
    assert df["date"].iloc[0] == pd.Timestamp("2024-01-02")
    assert df["date"].iloc[1] == pd.Timestamp("2024-01-03")


def test_normalize_dates_parses_ambiguous_day_correctly(tmp_path):
    """01/02/2024 必须解析为 1 月 2 日（MM/DD），不是 2 月 1 日。"""
    csv = "date,symbol,open,high,low,close,volume\n01/02/2024,QQQ,398,400,397,399.0,900\n"
    df = loader.load_prices(_write(tmp_path, csv), required_symbols=[])
    assert df["date"].iloc[0] == pd.Timestamp("2024-01-02")
    assert df["date"].iloc[0].month == 1


def test_duplicate_rows_are_dropped(tmp_path):
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/02/2024,QQQ,398,400,397,399.0,900\n"
        "01/02/2024,QQQ,398,400,397,399.0,900\n"
    )
    df = loader.load_prices(_write(tmp_path, csv), required_symbols=[])
    assert len(df) == 1


def test_split_deviation_detects_unadjusted_split(tmp_path):
    """构造未复权的 2:1 拆股（杠杆 ETF −50%，标的 0%），必须被拦截。"""
    rows = ["date,symbol,open,high,low,close,volume"]
    for i in range(3):
        rows.append("01/0%d/2024,QQQ,100,101,99,100,1000" % (i + 2))
    rows += [
        "01/02/2024,TQQQ,300,301,299,300,1000",
        "01/03/2024,TQQQ,150,151,149,150,2000",  # 拆股未复权
        "01/04/2024,TQQQ,151,152,150,151,1000",
    ]
    df = loader.load_prices(_write(tmp_path, "\n".join(rows) + "\n"), required_symbols=[])
    with pytest.raises(loader.DataQualityError, match="异常跳变"):
        loader.check_split_anomalies(df)


def test_deviation_check_handles_reverse_split(tmp_path):
    """合股（1:5，价格 ×5）方向与拆股相反，相对偏离检测必须同样拦截（§17 风险 9）。"""
    rows = ["date,symbol,open,high,low,close,volume"]
    for i in range(2):
        rows.append("01/0%d/2024,SPY,100,101,99,100,1000" % (i + 2))
    rows += [
        "01/02/2024,UPRO,10,10.1,9.9,10,1000",
        "01/03/2024,UPRO,50,50.5,49.5,50,5000",  # 1:5 合股未复权，+400%
    ]
    df = loader.load_prices(_write(tmp_path, "\n".join(rows) + "\n"), required_symbols=[])
    with pytest.raises(loader.DataQualityError, match="异常跳变"):
        loader.check_split_anomalies(df)


def test_missing_underlying_series_is_flagged(tmp_path):
    """标的序列缺失时必须显式报错，不能静默放行（否则拆股检测形同虚设）。"""
    rows = (
        "date,symbol,open,high,low,close,volume\n"
        "01/02/2024,TQQQ,300,301,299,300,1000\n"
        "01/03/2024,TQQQ,150,151,149,150,2000\n"
    )
    df = loader.load_prices(_write(tmp_path, rows), required_symbols=[])
    with pytest.raises(loader.DataQualityError, match="价格序列缺失"):
        loader.check_split_anomalies(df)


def _full_fixture_rows():
    """三个杠杆 ETF 与其标的各两天的完整夹具。

    检测函数对全部 UNDERLYING_MAP 键逐一校验，缺任一标的即 fail-closed，
    因此构造夹具时必须给全，否则测的是"序列缺失"而非目标行为。
    """
    rows = ["date,symbol,open,high,low,close,volume"]
    for sym, c0, c1 in [("QQQ", 300.0, 302.0), ("SOXX", 180.0, 180.5), ("SPY", 500.0, 501.0)]:
        for day, c in [(2, c0), (3, c1)]:
            rows.append("01/%02d/2024,%s,%s,%s,%s,%s,1000" % (day, sym, c, c, c, c))
    return rows


def test_real_extreme_move_is_not_flagged(tmp_path):
    """SOXL 2025-04-09 真实 +54.79%（标的 SOXX +18.57%）必须放行。"""
    rows = [
        "date,symbol,open,high,low,close,volume",
        "04/08/2025,QQQ,300,301,299,300,1000",
        "04/09/2025,QQQ,300,301,299,300,1000",      # 标的持平
        "04/08/2025,SOXX,180,181,179,180,1000",
        "04/09/2025,SOXX,213,214,212,213.4,1000",   # +18.57%
        "04/08/2025,SPY,500,501,499,500,1000",
        "04/09/2025,SPY,500,501,499,500,1000",      # 标的持平
        "04/08/2025,TQQQ,50,50.5,49.5,50,1000",
        "04/09/2025,TQQQ,50,50.5,49.5,50,1000",
        "04/08/2025,SOXL,20,20.1,19.9,20,1000",
        "04/09/2025,SOXL,31,31.1,30.9,30.96,1000",  # +54.79%
        "04/08/2025,UPRO,30,30.2,29.8,30,1000",
        "04/09/2025,UPRO,30,30.2,29.8,30,1000",
    ]
    df = loader.load_prices(_write(tmp_path, "\n".join(rows) + "\n"), required_symbols=[])
    loader.check_split_anomalies(df)
    # 该日 SOXL 偏离 = |54.79% − 3×18.57%| = 0.88pp << SPLIT_DEVIATION_THRESHOLD，故放行


def test_real_crisis_day_deviation_within_threshold(tmp_path):
    """2020-03-17 真实崩盘日（SOXL +9.94% vs 3×SOXX +26.40%，偏离 16.46pp）必须放行。

    该日为全区间最大真实偏离，是阈值标定的下界（详见 config.SPLIT_DEVIATION_THRESHOLD
    注释）。若此用例失败，说明阈值被下调到会把真实市场事件误判为拆股的程度。
    """
    rows = [
        "date,symbol,open,high,low,close,volume",
        # 为隔离目标偏离，QQQ/SPY 及其杠杆 ETF 设为持平
        "03/16/2020,QQQ,180,181,179,180,1000",
        "03/17/2020,QQQ,180,181,179,180,1000",
        "03/16/2020,SPY,240,241,239,240,1000",
        "03/17/2020,SPY,240,241,239,240,1000",
        "03/16/2020,TQQQ,50,50.5,49.5,50,1000",
        "03/17/2020,TQQQ,50,50.5,49.5,50,1000",
        "03/16/2020,UPRO,30,30.2,29.8,30,1000",
        "03/17/2020,UPRO,30,30.2,29.8,30,1000",
        # 真实数据（Data/raw/prices.csv）
        "03/16/2020,SOXX,59.1767,60.0,58.0,59.1767,1000",
        "03/17/2020,SOXX,64.3833,65.0,58.1067,64.3833,1000",   # +8.80%
        "03/16/2020,SOXL,5.3187,7.0973,5.2667,5.3187,1000",
        "03/17/2020,SOXL,5.32,5.992,4.3807,5.8473,1000",       # +9.94%，偏离 16.46pp
    ]
    df = loader.load_prices(_write(tmp_path, "\n".join(rows) + "\n"), required_symbols=[])
    loader.check_split_anomalies(df)


def test_reported_message_quantifies_deviation(tmp_path):
    """报错信息必须给出偏离百分点，便于人工判读（§4.4 第 4 条）。"""
    rows = ["date,symbol,open,high,low,close,volume"]
    for i in range(3):
        rows.append("01/0%d/2024,QQQ,100,101,99,100,1000" % (i + 2))
    rows += [
        "01/02/2024,TQQQ,300,301,299,300,1000",
        "01/03/2024,TQQQ,150,151,149,150,2000",  # 2:1 拆股未复权 → 偏离 50pp
        "01/04/2024,TQQQ,151,152,150,151,1000",
    ]
    df = loader.load_prices(_write(tmp_path, "\n".join(rows) + "\n"), required_symbols=[])
    with pytest.raises(loader.DataQualityError) as excinfo:
        loader.check_split_anomalies(df)
    msg = str(excinfo.value)
    assert "异常跳变" in msg
    # 校验语义（偏离量级）而非精确文案，避免改报告格式就碎
    assert "偏离" in msg
    matched = re.search(r"偏离\s*([\d.]+)\s*pp", msg)
    assert matched is not None, "报错信息应包含可解析的偏离百分点"
    assert 45.0 <= float(matched.group(1)) <= 55.0      # 2:1 拆股偏离约 50pp


def test_missing_symbol_raises(tmp_path):
    csv = "date,symbol,open,high,low,close,volume\n01/02/2024,QQQ,1,1,1,1,1\n"
    with pytest.raises(loader.DataQualityError, match="缺少标的"):
        loader.load_prices(_write(tmp_path, csv), required_symbols=["TQQQ"])


def test_wide_table_aligns_on_primary_calendar(tmp_path):
    """宽表以主日历（SPY 交易日）为基准，缺数据处为 NaN 而非前向填充。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/02/2024,SPY,100,101,99,100,1000\n"
        "01/03/2024,SPY,101,102,100,101,1000\n"
        "01/02/2024,QQQ,400,401,399,400,1000\n"
    )
    df = loader.load_prices(_write(tmp_path, csv), required_symbols=[])
    # 单字段视图：columns=symbol（to_wide 的文档字符串已明确），按 symbol 取值
    wide = loader.to_wide(df)
    assert list(wide.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert wide.loc[pd.Timestamp("2024-01-03"), "SPY"] == 101.0
    assert pd.isna(wide.loc[pd.Timestamp("2024-01-03"), "QQQ"])   # 缺口为 NaN，不前向填充

    # 多字段视图：columns=MultiIndex (symbol, field)
    wide_ohlcv = loader.to_wide_ohlcv(df, primary_symbol="SPY")
    assert list(wide_ohlcv.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert wide_ohlcv.loc[pd.Timestamp("2024-01-02"), ("QQQ", "close")] == 400.0
    assert pd.isna(wide_ohlcv.loc[pd.Timestamp("2024-01-03"), ("QQQ", "close")])


def test_real_data_covers_all_required_symbols():
    """真实数据文件必须覆盖 config.SYMBOLS 全部标的（§4.2 覆盖性硬约束）。"""
    df = loader.load_prices(config.RAW_DIR + "/prices.csv")
    assert loader.check_required_symbols(df) is True
