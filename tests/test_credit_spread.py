# -*- coding: utf-8 -*-
"""`fg_system/factors/credit_spread.py` 测试（MT-76 ③）。

🔴 **核心是 lookahead** ✗：
`available_date` 之后才发布的数据，**不得**影响该日之前的结果 ✓。
真实 CSV 只在 Mac 本地（不入库 ✓）⇒ 这里全部用**合成小样本** ✓。
"""
import importlib.util
import os

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cs = _load("fg_system/factors/credit_spread.py", "credit_spread")


def _mk(rows):
    """rows: `(date, value, available_date)` ⇒ DataFrame ✓。"""
    df = pd.DataFrame(rows, columns=["date", "value", "available_date"])
    for c in ("date", "available_date"):
        df[c] = pd.to_datetime(df[c])
    return df


# ---------------------------------------------------------------- 对齐口径
def test_align_uses_available_date_not_observation_date():
    """🔴 观测日**不可见** ✗ —— 必须等到 `available_date` 才可见 ✓。"""
    df = _mk([("2026-10-01", 1.50, "2026-10-06")])
    days = ["2026-10-01", "2026-10-05", "2026-10-06"]
    s = cs.align_to(df, days)

    assert pd.isna(s.loc["2026-10-01"])        # 观测日看不到 ✓
    assert pd.isna(s.loc["2026-10-05"])        # 发布前一天仍看不到 ✓
    assert s.loc["2026-10-06"] == pytest.approx(1.50)   # 发布当日可见 ✓


def test_align_picks_latest_available_value():
    """同日有多个已发布值时 ⇒ 取**最新** ✓（`direction="backward"` ✓）。"""
    df = _mk([
        ("2026-10-01", 1.0, "2026-10-02"),
        ("2026-10-02", 2.0, "2026-10-03"),
    ])
    s = cs.align_to(df, ["2026-10-01", "2026-10-02", "2026-10-03"])
    assert pd.isna(s.loc["2026-10-01"])
    assert s.loc["2026-10-02"] == pytest.approx(1.0)
    assert s.loc["2026-10-03"] == pytest.approx(2.0)


def test_lag_days_shifts_visibility():
    """`lag_days` 必须把可见性**整体后移** ✓（保守余量 ✓）。"""
    df = _mk([("2026-10-01", 1.50, "2026-10-06")])
    days = ["2026-10-06", "2026-10-08"]
    s = cs.align_to(df, days, lag_days=2)
    assert pd.isna(s.loc["2026-10-06"])        # +2 天 ⇒ 10-08 才可见 ✓
    assert s.loc["2026-10-08"] == pytest.approx(1.50)


# ---------------------------------------------------------------- lookahead
def test_no_lookahead_when_future_rows_removed():
    """🔴 **核心测试**：删掉「尚未发布」的行 ⇒ 之前的结果**完全不变** ✓。"""
    df = _mk([
        ("2026-10-01", 1.0, "2026-10-06"),
        ("2026-10-02", 2.0, "2026-10-07"),
        ("2026-10-03", 9.9, "2026-10-08"),     # 未来值 ⇒ 不该影响 10-07 之前 ✓
    ])
    days = ["2026-10-01", "2026-10-02", "2026-10-03",
            "2026-10-06", "2026-10-07", "2026-10-08"]
    full = cs.align_to(df, days)

    cut = df[df["available_date"] <= pd.Timestamp("2026-10-07")]
    part = cs.align_to(cut, days)

    assert full.loc[:"2026-10-07"].equals(part.loc[:"2026-10-07"]), \
        "未来行影响了历史结果 ⇒ lookahead ✗"
    # 10-08 之后才允许不同 ✓（那是「未来数据只影响未来」✓）
    assert full.loc["2026-10-08"] == pytest.approx(9.9)
    assert part.loc["2026-10-08"] == pytest.approx(2.0)


def test_wrong_alignment_by_date_would_leak():
    """反例：按 `date`（观测日）对齐会**提前泄露** ✗ —— 证明守卫有意义 ✓。"""
    df = _mk([("2026-10-01", 1.50, "2026-10-06")])
    days = pd.to_datetime(["2026-10-01", "2026-10-06"])

    correct = cs.align_to(df, days)
    leak = df.set_index("date")["value"].reindex(days).ffill()

    assert pd.isna(correct.loc["2026-10-01"])       # 正确：看不到 ✓
    assert leak.loc["2026-10-01"] == pytest.approx(1.50)   # 错误：看到了 ✗


# ---------------------------------------------------------------- 因子形态
def test_level_without_target_index_uses_available_date():
    df = _mk([("2026-10-01", 1.0, "2026-10-06"),
              ("2026-10-02", 2.0, "2026-10-07")])
    lvl = cs.baa10y_level(df)
    assert list(lvl.index) == [pd.Timestamp("2026-10-06"),
                              pd.Timestamp("2026-10-07")]
    assert lvl.name == "baa10y"


def test_zscore_nan_when_window_insufficient():
    """窗口不足 ⇒ **NaN** ✓（禁止用不足窗口凑值 ✗）。"""
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    df = _mk([(d, float(i), d + pd.Timedelta(days=1))
              for i, d in enumerate(dates)])
    z = cs.baa10y_zscore(df, dates, window=10)
    assert z.isna().all()


def test_score_is_reverse_of_zscore():
    """分数 = 100 × (1 − 分位) ✓（利差宽 ⇒ 恐惧 ⇒ 低分 ✓）。

    注：**不做「分位与原值的相关系数」断言** ✗ —— `base.rolling_pct` 在趋势/锯齿
    序列上会**饱和**（窗口右端必为极值 ⇒ 分位恒 1）✓，这是 `base.py` 里写明的
    数学必然 ✗，不是实现缺陷 ✓。⇒ 改用**确定性的定义关系**验证方向 ✓。
    """
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 100.0]
    df = _mk([(d, v, d + pd.Timedelta(days=1)) for d, v in zip(dates, vals)])

    z = cs.baa10y_zscore(df, dates, window=3)
    sc = cs.baa10y_score(df, dates, window=3)
    both = pd.concat([z.rename("z"), sc.rename("s")], axis=1).dropna()
    assert len(both) > 0

    # 定义关系：分数 = 100 × (1 − 分位) ✓
    assert (both["s"] - 100.0 * (1.0 - both["z"])).abs().max() < 1e-9
    # 末值远大于窗口内其它值 ⇒ 分位=1 ⇒ 分数=0（利差极宽 ⇒ 极度恐惧）✓
    assert both["z"].iloc[-1] == pytest.approx(1.0)
    assert both["s"].iloc[-1] == pytest.approx(0.0)
    assert sc.dropna().between(0.0, 100.0).all()


# ---------------------------------------------------------------- 读文件
def test_load_raises_on_missing_column(tmp_path):
    """缺 `available_date` ⇒ **抛错** ✗（绝不拿 `date` 兜底 ✗）。"""
    p = tmp_path / "bad.csv"
    p.write_text("date,value\n2026-10-01,1.5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="available_date"):
        cs.load(str(p))


def test_load_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        cs.load(str(tmp_path / "nope.csv"))


def test_load_sorts_by_available_date(tmp_path):
    p = tmp_path / "ok.csv"
    p.write_text(
        "date,value,available_date\n"
        "2026-10-02,2.0,2026-10-07\n"
        "2026-10-01,1.0,2026-10-06\n",
        encoding="utf-8")
    df = cs.load(str(p))
    assert list(df["value"]) == [1.0, 2.0]     # 按 available_date 升序 ✓
