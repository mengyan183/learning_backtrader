# -*- coding: utf-8 -*-
"""D2 数据质量升级：drift_monitor 的**多源交叉校验** + **自动回填**。

验收（规划 v2.0 方向 D2 原文）：
  - [计算层] 断言「多源偏差表对**固定输入**返回**固定行**」—— 本文件全部用**合成序列**，
    不读 Data/、不联网（Windows 无公网）。
  - [结论层·人工] 偏差表的阈值判定（阈值可配置）；**不**据偏差表自动改仓位。

设计约束：
  - 交叉校验是**纯函数**：接收**两条序列**（如两个 VIX 源），返回偏差表。函数内**不联网**。
  - 自动回填是**可注入文件路径**的纯函数（tmp_path 测），路径从 `fg_system.config` 取。
"""
import importlib.util
import os

import pytest

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "drift_monitor.py")


def _load():
    spec = importlib.util.spec_from_file_location("drift_monitor", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dm = _load()


# ---------------------------------------------------------------- 固定合成输入
def _series(pairs):
    idx = pd.to_datetime([d for d, _ in pairs])
    return pd.Series([v for _, v in pairs], index=idx, dtype="float64")


# 两个 VIX 源：主源 / 副源。固定 4 个交易日，含两处超阈值偏差、两处一致。
_PRIMARY = _series([
    ("2026-10-05", 20.0),
    ("2026-10-06", 22.0),   # 副源 22.5 → 偏差 0.5（2.27%）
    ("2026-10-07", 30.0),   # 副源 40.0 → 偏差 10.0（33.33%）超阈值
    ("2026-10-08", 18.0),   # 副源 10.0 → 偏差 8.0（44.44%）超阈值
])
_SECONDARY = _series([
    ("2026-10-05", 20.0),
    ("2026-10-06", 22.5),
    ("2026-10-07", 40.0),
    ("2026-10-08", 10.0),
])


def test_crosscheck_fixed_input_fixed_rows():
    """**[计算层核心]** 固定输入 ⇒ 偏差表逐行固定（值 + 列名 + 顺序）。"""
    dev = dm.crosscheck_series(_PRIMARY, _SECONDARY, threshold=0.05)
    assert list(dev["date"]) == [
        "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]
    assert list(dev["primary"]) == [20.0, 22.0, 30.0, 18.0]
    assert list(dev["secondary"]) == [20.0, 22.5, 40.0, 10.0]
    # 绝对偏差 = |副源 − 主源|
    assert list(dev["abs_dev"]) == [0.0, 0.5, 10.0, 8.0]
    # 相对偏差 = abs_dev / |主源|
    assert dev["rel_dev"].round(4).tolist() == [0.0, 0.0227, 0.3333, 0.4444]
    # 超阈值标记（阈值 0.05 ⇒ 后两行 True）
    assert list(dev["breach"]) == [False, False, True, True]


def test_crosscheck_columns_are_stable():
    """偏差表**列名固定**（消费方/报告据此取字段，不得漂移）。"""
    dev = dm.crosscheck_series(_PRIMARY, _SECONDARY, threshold=0.05)
    assert list(dev.columns) == [
        "date", "primary", "secondary", "abs_dev", "rel_dev", "breach"]


def test_crosscheck_empty_overlap_returns_empty_table():
    """无重叠日期 ⇒ 空偏差表但**列名齐全**（不抛异常、不返回 None）。"""
    a = _series([("2026-01-01", 1.0), ("2026-01-02", 2.0)])
    b = _series([("2026-02-01", 1.0), ("2026-02-02", 2.0)])
    dev = dm.crosscheck_series(a, b, threshold=0.05)
    assert len(dev) == 0
    assert list(dev.columns) == [
        "date", "primary", "secondary", "abs_dev", "rel_dev", "breach"]


def test_crosscheck_inner_join_only_common_dates():
    """只在**共同日期**上比对（缺一天不算偏差，避免把停更误判成数据错误）。"""
    a = _series([("2026-10-05", 20.0), ("2026-10-06", 22.0), ("2026-10-07", 30.0)])
    b = _series([("2026-10-06", 22.0), ("2026-10-07", 30.0)])
    dev = dm.crosscheck_series(a, b, threshold=0.05)
    assert list(dev["date"]) == ["2026-10-06", "2026-10-07"]


def test_crosscheck_threshold_is_configurable():
    """阈值可配置：同一输入换个阈值 ⇒ breach 列随之变化（结论层·人工判定）。"""
    strict = dm.crosscheck_series(_PRIMARY, _SECONDARY, threshold=0.01)
    loose = dm.crosscheck_series(_PRIMARY, _SECONDARY, threshold=0.50)
    assert list(strict["breach"]) == [False, True, True, True]
    assert list(loose["breach"]) == [False, False, False, False]


def test_crosscheck_does_not_mutate_inputs():
    """纯函数：不得修改传入序列（否则上游数据被污染）。"""
    p = _PRIMARY.copy()
    s = _SECONDARY.copy()
    dm.crosscheck_series(p, s, threshold=0.05)
    pd.testing.assert_series_equal(p, _PRIMARY)
    pd.testing.assert_series_equal(s, _SECONDARY)


def test_crosscheck_breach_rows_helper():
    """只挑出超阈值行（供报告/告警用），固定输入 ⇒ 固定子表。"""
    dev = dm.crosscheck_series(_PRIMARY, _SECONDARY, threshold=0.05)
    bad = dm.breach_rows(dev)
    assert list(bad["date"]) == ["2026-10-07", "2026-10-08"]
    assert len(bad) == 2


# ---------------------------------------------------------------- 自动回填
# 触发条件（回填规则）：主源**缺值**行，用副源补齐 —— **但**若该行副源值相对
# 「主源最近已知值」的**相对偏差 > threshold**，视为可疑 ⇒ **不回填**（宁缺勿滥）。
# 主源已有值 ⇒ 绝不覆盖。
def _wide(tmp_path):
    """可回填样例：副源与主源贴近（10-06 5%、10-07 4.8%，均 ≤ 0.10）。"""
    p = tmp_path / "prices_multi.csv"
    p.write_text(
        "date,VIX_primary,VIX_secondary\n"
        "2026-10-05,20.0,20.0\n"
        "2026-10-06,,21.0\n"       # 主源缺 → 副源 21.0 vs 20.0 = 5% ≤ 阈值 ⇒ 回填
        "2026-10-07,,22.0\n"       # 主源缺 → 副源 22.0 vs 21.0 ≈ 4.8% ⇒ 回填
        "2026-10-08,30.0,31.0\n",  # 主源有值 ⇒ 不覆盖
        encoding="utf-8")
    return str(p)


def test_backfill_fills_missing_from_secondary(tmp_path):
    """缺值行用副源回填；已有值行不被覆盖。固定输入 ⇒ 固定明细。"""
    path = _wide(tmp_path)
    filled = dm.backfill_from_secondary(path, primary_col="VIX_primary",
                                        secondary_col="VIX_secondary",
                                        threshold=0.10)
    assert list(filled["date"]) == ["2026-10-06", "2026-10-07"]
    assert filled["value"].tolist() == [21.0, 22.0]
    assert set(filled["source"]) == {"VIX_secondary"}
    # 写回文件：缺值被补上，10-08 保持主源原值 30.0（不被副源 31.0 覆盖）
    out = pd.read_csv(path)
    assert out["VIX_primary"].tolist() == [20.0, 21.0, 22.0, 30.0]


def test_backfill_skips_implausible_rows(tmp_path):
    """守卫：缺口行副源值相对主源最近已知值**超阈值** ⇒ 不回填（坏数据不进合成）。"""
    p = tmp_path / "prices_multi.csv"
    p.write_text(
        "date,VIX_primary,VIX_secondary\n"
        "2026-10-05,20.0,20.0\n"
        "2026-10-06,,99.0\n",      # 99.0 vs 20.0 = 395% > 5% ⇒ 不回填，保留 NaN
        encoding="utf-8")
    filled = dm.backfill_from_secondary(str(p), primary_col="VIX_primary",
                                        secondary_col="VIX_secondary",
                                        threshold=0.05)
    assert len(filled) == 0
    out = pd.read_csv(str(p))
    assert pd.isna(out["VIX_primary"].iloc[1])


def test_backfill_threshold_is_configurable(tmp_path):
    """阈值可配置：放宽到 4.0 ⇒ 同一 99.0 行变为可回填（人工可调筛线）。"""
    p = tmp_path / "prices_multi.csv"
    p.write_text(
        "date,VIX_primary,VIX_secondary\n"
        "2026-10-05,20.0,20.0\n"
        "2026-10-06,,99.0\n",
        encoding="utf-8")
    filled = dm.backfill_from_secondary(str(p), primary_col="VIX_primary",
                                        secondary_col="VIX_secondary",
                                        threshold=4.0)
    assert list(filled["date"]) == ["2026-10-06"]


def test_backfill_no_op_when_nothing_missing(tmp_path):
    """无缺值 ⇒ 空明细、文件不变（幂等）。"""
    p = tmp_path / "prices_multi.csv"
    p.write_text(
        "date,VIX_primary,VIX_secondary\n"
        "2026-10-05,20.0,20.0\n",
        encoding="utf-8")
    before = open(str(p), encoding="utf-8").read()
    filled = dm.backfill_from_secondary(str(p), primary_col="VIX_primary",
                                        secondary_col="VIX_secondary",
                                        threshold=0.05)
    assert len(filled) == 0
    assert open(str(p), encoding="utf-8").read() == before


def test_backfill_columns_are_stable(tmp_path):
    """回填明细列名固定。"""
    path = _wide(tmp_path)
    filled = dm.backfill_from_secondary(path, primary_col="VIX_primary",
                                        secondary_col="VIX_secondary",
                                        threshold=0.10)
    assert list(filled.columns) == ["date", "value", "source"]


def test_backfill_default_path_from_config():
    """默认路径取自 `fg_system.config`（不硬编码 Data/）。"""
    from fg_system import config
    assert dm.BACKFILL_DEFAULT_PATH == os.path.join(config.RAW_DIR, "vix.csv")


# ---------------------------------------------------------------- 报告接线（非死代码）
def test_crosscheck_report_with_two_files(tmp_path):
    """注入两条 VIX 源文件 ⇒ 报告含超阈值行，偏差表非空（接线可用）。"""
    p = tmp_path / "vix.csv"
    s = tmp_path / "vix_alt.csv"
    p.write_text("date,close\n2026-10-05,20.0\n2026-10-07,30.0\n", encoding="utf-8")
    s.write_text("date,close\n2026-10-05,20.0\n2026-10-07,40.0\n", encoding="utf-8")
    report, dev = dm.crosscheck_report(str(p), str(s), threshold=0.05)
    assert "共同日期 2 天，超阈值 1 天" in report
    assert "2026-10-07" in report
    assert list(dev["date"]) == ["2026-10-05", "2026-10-07"]


def test_crosscheck_report_missing_secondary_is_safe(tmp_path):
    """副源缺失 ⇒ 报告明示并跳过，偏差表为空但列名齐全（不崩）。"""
    p = tmp_path / "vix.csv"
    p.write_text("date,close\n2026-10-05,20.0\n", encoding="utf-8")
    report, dev = dm.crosscheck_report(str(p), str(tmp_path / "nope.csv"),
                                       threshold=0.05)
    assert "有源为空" in report
    assert len(dev) == 0
    assert list(dev.columns) == dm.CROSSCHECK_COLUMNS


# ---------------------------------------------------------------- 源选择（D2 fed 接线）
# 需求：`crosscheck_report` 支持按**名字选一组源**（`--source vix|fed`）：
#   - vix 组：主源 vix.csv(close) / 副源 vix_alt.csv(close)  —— **行为保持不变**
#   - fed 组：主源 fedwatch.csv(hike_pct，CME FedWatch 市场隐含概率)
#             / 副源 kalshi_fed.csv(hike_pct，Kalshi KXFED 市场隐含概率)
# 副源缺失时**安全跳过并提示**（既有设计）。
def test_sources_registry_has_vix_only():
    """源组注册表：**只剩 vix 一组** ✓（2026-11-26 停用 fed 副源）。

    🔴 为什么删掉 fed 组 ✗：
       副源 `kalshi_fed.csv` 由 `fetch_kalshi_fed.py` 产出，而该脚本已从
       每日链移除 —— `external-api.kalshi.com` 经 ClashX 仍 `Connection
       reset`（`proxy_probe.py` 实测：代理正常，是节点屏蔽该站点）✗
       主源 `fedwatch.csv`（CME FedWatch）一直正常 ⇒ 简报不受影响 ✓
       ⇒ 副源不再更新，继续校验只会因「副源过期」报**假警** ✗
    ⚠️ 要恢复：把 `fetch_kalshi_fed.py` 加回 plist + 解除 `SOURCES` 里的注释 ✓
    """
    from fg_system import config

    assert set(dm.SOURCES) == {"vix"}, "fed 组应已停用 ✗"
    vix = dm.SOURCES["vix"]
    assert vix["value"] == "close"
    assert vix["primary"] == os.path.join(config.RAW_DIR, "vix.csv")
    assert vix["secondary"] == os.path.join(config.RAW_DIR, "vix_alt.csv")


@pytest.mark.skip(reason="fed 副源校验已停用（2026-11-26：kalshi 不可达，见 drift_monitor.SOURCES 注释）")
def test_crosscheck_report_selects_fed_group_by_name(tmp_path):
    """`source="fed"` ⇒ 用 fed 组：主源 fedwatch.csv / 副源 kalshi_fed.csv。"""
    p = tmp_path / "fedwatch.csv"
    s = tmp_path / "kalshi_fed.csv"
    p.write_text("date,meeting,hike_pct\n"
                 "2026-10-05,2026-11-04,22.0\n"
                 "2026-10-06,2026-11-04,21.0\n", encoding="utf-8")
    s.write_text("date,meeting,hike_pct\n"
                 "2026-10-05,2026-11-04,21.0\n"   # 差 1.0 / 22.0 ≈ 4.5% ≤ 5%
                 "2026-10-06,2026-11-04,30.0\n",  # 差 9.0 / 21.0 ≈ 42.9% 超阈值
                 encoding="utf-8")
    report, dev = dm.crosscheck_report(source="fed", primary_path=str(p),
                                       secondary_path=str(s), threshold=0.05)
    assert list(dev["date"]) == ["2026-10-05", "2026-10-06"]
    assert list(dev["breach"]) == [False, True]
    assert "2026-10-06" in report


def test_crosscheck_report_vix_group_unchanged(tmp_path):
    """`source` 缺省 / 显式 `vix` ⇒ 与既有 vix 双源行为**完全一致**（同表）。"""
    p = tmp_path / "vix.csv"
    s = tmp_path / "vix_alt.csv"
    p.write_text("date,close\n2026-10-05,20.0\n2026-10-07,30.0\n", encoding="utf-8")
    s.write_text("date,close\n2026-10-05,20.0\n2026-10-07,40.0\n", encoding="utf-8")
    default_report, default_dev = dm.crosscheck_report(str(p), str(s),
                                                       threshold=0.05)
    vix_report, vix_dev = dm.crosscheck_report(source="vix", primary_path=str(p),
                                               secondary_path=str(s),
                                               threshold=0.05)
    pd.testing.assert_frame_equal(default_dev, vix_dev)
    assert default_report == vix_report
    assert "共同日期 2 天，超阈值 1 天" in vix_report


@pytest.mark.skip(reason="fed 副源校验已停用（2026-11-26：kalshi 不可达，见 drift_monitor.SOURCES 注释）")
def test_crosscheck_report_fed_missing_secondary_is_safe(tmp_path):
    """fed 组：副源（Kalshi KXFED）缺失 ⇒ 安全跳过并提示，偏差表为空但不崩。"""
    p = tmp_path / "fedwatch.csv"
    p.write_text("date,meeting,hike_pct\n2026-10-05,2026-11-04,22.0\n",
                 encoding="utf-8")
    report, dev = dm.crosscheck_report(source="fed", primary_path=str(p),
                                       secondary_path=str(tmp_path / "nope.csv"),
                                       threshold=0.05)
    assert "有源为空" in report
    assert len(dev) == 0
    assert list(dev.columns) == dm.CROSSCHECK_COLUMNS


def test_crosscheck_report_unknown_source_raises(tmp_path):
    """未知源名 ⇒ 明确报错（不静默跑 vix，避免看错口径）。"""
    import pytest
    with pytest.raises((KeyError, ValueError)):
        dm.crosscheck_report(source="spx")


# ---------------------------------------------------------------- decide 相对阈值（12.51）
def _st(ic_mean, icir, ic_std=0.1):
    return {"ic_mean": ic_mean, "icir": icir, "ic_std": ic_std,
            "icir_raw": icir, "overlap": 3, "ic_positive_ratio": 0.5, "n": 100}


def test_decide_uses_ratio_not_absolute():
    """判据必须是「近窗 / 全窗」的**比值** ✓ —— 不是绝对 |ICIR| ✗。

    🔴 2026-11-20（第 12.51 条）：第 12.48 条把 ICIR 按重叠折算（×0.577）
       ⇒ 绝对阈值 0.3/0.5 的含义变了 ✗ ⇒ 改用比值，与口径解耦 ✓

    构造：基线 0.67、近窗 0.67（比值 1.0）⇒ 正常
          基线 0.67、近窗 0.30（比值 0.45）⇒ 预警边界
          基线 0.67、近窗 0.15（比值 0.22）⇒ 告警
    """
    assert dm.decide(_st(-0.35, -0.67), _st(-0.35, -0.67))[0] == "正常"
    assert dm.decide(_st(-0.35, -0.67), _st(-0.35, -0.15))[0] == "告警"
    assert dm.decide(_st(-0.35, -0.67), _st(-0.35, -0.30))[0] == "预警"


def test_decide_same_ratio_same_verdict_across_scales():
    """**同比值必须同结论** ✓ —— 这正是「与口径解耦」的意思。

    基线 1.16 / 近窗 0.58（比值 0.5）与 基线 0.67 / 近窗 0.335（比值 0.5）
    必须给同一个判定 ✗（旧绝对阈值下这两者会一个「正常」一个「预警」✗）
    """

    # 比值都取 0.40（落在 预警 区：0.30 ≤ 0.40 < 0.45）
    a = dm.decide(_st(-0.35, -1.16), _st(-0.35, -0.464))[0]
    b = dm.decide(_st(-0.35, -0.67), _st(-0.35, -0.268))[0]
    assert a == b == "预警"


def test_decide_reports_insufficient_when_baseline_too_weak():
    """全窗基线太弱（|ICIR| < 0.15）⇒ 判「数据不足」，不拿比值硬判 ✓。"""

    level, _ = dm.decide(_st(-0.02, -0.05), _st(-0.02, -0.05))
    assert level == "数据不足"


def test_decide_direction_flip_still_alerts():
    """方向翻转仍是最高优先级告警 ✓（未被比值逻辑吞掉）。"""

    level, note = dm.decide(_st(-0.35, -0.67), _st(+0.10, +0.20))
    assert level == "告警"
    assert "方向翻转" in note
