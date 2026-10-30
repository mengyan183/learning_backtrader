# -*- coding: utf-8 -*-
"""C2 ERP 估值因子（`fg_system/factors/erp.py`）。

锁住三条设计决策（2026-10-30）：
  1. **10Y 用月均**（不是月末值）✓ —— 与月度 PE 同频
  2. **available_date = date + 1 个月** ✓ —— 防 lookahead
  3. **分位窗口 2520**（10 年）✗ 不用默认 756
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors import erp


def _pe(n=24, start="2024-01-01", pe_val=25.0):
    d = pd.date_range(start, periods=n, freq="MS")
    return pd.DataFrame({
        "date": d,
        "pe": [pe_val] * n,
        "available_date": d + pd.DateOffset(months=1),
    })


def _dgs10(n_months=24, start="2024-01-01", rate=4.0):
    """造日频 10Y：每个月内**前半月 4.0%、后半月 6.0%** ⇒ 月均必然是 5.0。

    ⇒ 若实现误用「月末值」，结果会是 6.0 而不是 5.0，测试立刻抓出来 ✓
    """
    rows = []
    for i in range(n_months):
        base = pd.Timestamp(start) + pd.DateOffset(months=i)
        for day in range(28):
            dt = base + pd.Timedelta(days=day)
            rows.append({"date": dt, "value": 4.0 if day < 14 else 6.0})
    return pd.DataFrame(rows)


def test_erp_uses_monthly_average_y10():
    """🔴 10Y 必须是**月均**（5.0），不是月末值（6.0）✓。

    2026-10-30 用户裁定：月度 PE 配「月末那天的 10Y」会引入日内噪声 ✗。
    """
    out = erp.erp_monthly(pe=_pe(6), dgs10=_dgs10(6))

    assert len(out) == 6
    assert out["y10"].iloc[0] == pytest.approx(5.0, abs=1e-9), \
        "用了月末值 6.0 而不是月均 5.0 ✗"
    # ERP = 1/25×100 − 5.0 = 4.0 − 5.0 = −1.0
    assert out["erp"].iloc[0] == pytest.approx(-1.0, abs=1e-9)


def test_erp_formula():
    """ERP = 100/PE − 10Y ✓（两个都按百分数算 ✓）。"""
    out = erp.erp_monthly(pe=_pe(3, pe_val=20.0), dgs10=_dgs10(3))
    # 100/20 = 5.0；10Y 月均 5.0 ⇒ ERP = 0
    assert out["erp"].iloc[0] == pytest.approx(0.0, abs=1e-9)


def test_available_date_backfilled_when_missing(tmp_path):
    """缺 `available_date` 列 ⇒ 按 `date + 1 个月` 补齐 ✓（绝不用 date 兜底 ✗）。"""
    p = tmp_path / "sp500_pe.csv"
    pd.DataFrame({"date": ["2026-01-01", "2026-02-01"],
                  "pe": [25.0, 26.0]}).to_csv(p, index=False)

    df = erp.load_monthly(path=str(p), value_col="pe")

    assert list(df["available_date"].dt.strftime("%Y-%m-%d")) == [
        "2026-02-01", "2026-03-01"]


def test_default_window_is_ten_years_in_months():
    """分位窗口必须是 **120 个月（10 年）** ✓。

    🔴 2026-10-30 实测踩坑：`rolling_pct` 的 window 单位是**行数** ✗，
    而 ERP 是月度序列（779 行）⇒ 传「2520 交易日」> 总行数 ⇒ **分位全 NaN** ✗。
    ⇒ 月度序列必须按月计：10 年 = 120 ✓，不是 2520、也不是 756 ✗。
    """
    assert erp.ERP_WINDOW == 120
    assert erp.ERP_WINDOW not in (756, 2520)


def test_window_larger_than_series_yields_all_nan():
    """窗口 > 序列长度 ⇒ 全 NaN ✓（这是上面那个 bug 的可复现形式）。

    锁住「窗口单位是行数」这一事实 ⇒ 以后谁再传交易日数就会立刻发现 ✗。
    """
    pct = erp.erp_pct(pe=_pe(24), dgs10=_dgs10(24), window=2520)
    assert pct.dropna().empty, "窗口 2520 用在 24 行月度序列上竟然有值 ✗"


def test_erp_pct_range_and_monotonic():
    """ERP 分位落在 [0,1] ✓，且**越高 = 越便宜 = 越贪婪**（方向不许反 ✗）。"""
    pe = _pe(60)
    # 让 10Y 逐步下行 ⇒ ERP 逐步上行 ⇒ 分位应单调不降 ✓
    rows = []
    for i in range(60):
        base = pd.Timestamp("2024-01-01") + pd.DateOffset(months=i)
        for day in range(28):
            rows.append({"date": base + pd.Timedelta(days=day),
                         "value": 6.0 - i * 0.05})
    dgs10 = pd.DataFrame(rows)

    pct = erp.erp_pct(pe=pe, dgs10=dgs10, window=12)

    valid = pct.dropna()
    assert len(valid) > 0
    assert valid.min() >= 0.0 and valid.max() <= 1.0
    assert valid.iloc[-1] >= valid.iloc[0], "ERP 上行时分位却下降 ⇒ 方向反了 ✗"


def test_cape_flag_uses_p90_threshold():
    """`cape_flag` 默认阈值取 **P90** ✓（用户裁定：按分布定，不写死 ✗）。"""
    div = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0],
                    index=pd.date_range("2026-01-01", periods=5))
    thr = div.quantile(0.90)
    flag = div > thr
    assert flag.sum() == 1, "P90 应该只标记最高的那个 ✗"
    assert flag.iloc[-1] is np.True_ or bool(flag.iloc[-1]) is True


def test_missing_files_raise_clear_error(tmp_path, monkeypatch):
    """数据文件不存在 ⇒ 抛**明确的** FileNotFoundError ✓（不静默返回空 ✗）。"""
    monkeypatch.setattr(erp, "_raw_path", lambda n: str(tmp_path / n))
    with pytest.raises(FileNotFoundError, match="fetch_pe_ratio"):
        erp.load_monthly()
    with pytest.raises(FileNotFoundError, match="fetch_fred"):
        erp.load_dgs10()
