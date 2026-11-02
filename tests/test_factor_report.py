# -*- coding: utf-8 -*-
"""因子评测统一渲染层 `fg_system/factors/report.py`（2026-11-02 工程加固）。

【为什么存在】`eval_baa10y` / `eval_erp` / `eval_ene` 三个脚本各自写了一遍
`_fmt()` / `_spy_close()` / IC 表格 ✗ ⇒ 三处重复、口径已漂（`eval_ene` 的
`_fmt` 少了 `scale`、表格列不一致）✗ ⇒ 统一到本模块 ✓
"""
import pytest

from fg_system.factors import report as R


def test_fmt_none_is_dash():
    """`None` ⇒ `—` ✓ —— 样本不足时 `screen_report` 会给 None ✗。"""
    assert R.fmt(None) == "—"
    assert R.fmt(0.5) == "+0.500"
    assert R.fmt(-0.1234, ".2f") == "-0.12"
    assert R.fmt(0.0123, "+.2f", 100) == "+1.23"


def test_forward_return_matches_definition():
    """前瞻收益 = `shift(-h)/close − 1` ✓。"""
    import pandas as pd
    s = pd.Series([100.0, 110.0, 121.0],
                  index=pd.date_range("2026-01-01", periods=3))
    f = R.forward_return(s, 1)
    assert f.iloc[0] == pytest.approx(0.10)
    assert f.iloc[1] == pytest.approx(0.10)
    assert f.iloc[2] != f.iloc[2], "末位应为 NaN ✗"


def test_ic_table_has_autocorr_columns():
    """表格必须带 **IC自相关 + n_eff** ✓ —— ICIR 已降级为参考 ✗。"""
    rep = {"ic": {5: {"rank_ic_mean": 0.05, "rank_icir": 0.3,
                      "pearson_icir": 0.28, "n": 100}}}
    txt = R.ic_table(rep, (5,))
    assert "IC自相关" in txt and "n_eff" in txt
    assert "| 5 |" in txt


def test_ic_table_handles_missing_values():
    """`ic` 缺字段 ⇒ 打 `—` ✓ 不抛错（`n=0` 也要能渲染）✓。"""
    txt = R.ic_table({"ic": {5: {}}}, (5,))
    assert "—" in txt


def test_ic_table_extra_columns():
    """`extra` 参数化列 ✓ —— `eval_baa10y` 需要「近窗ICIR/分层/top-bottom」✗。"""
    rep = {"ic": {5: {"n": 10}},
           "recent": {5: {"icir": 0.9}},
           "layers": {5: {"monotonic_spearman": 1.0,
                          "top_minus_bottom": 0.01}}}
    txt = R.ic_table(
        rep, (5,),
        extra=[("近窗ICIR", lambda r, h: R.fmt((r["recent"].get(h) or {}).get("icir"))),
               ("分层mono", lambda r, h: R.fmt(
                   (r["layers"].get(h) or {}).get("monotonic_spearman"), ".3f"))])
    assert "近窗ICIR" in txt and "分层mono" in txt
    assert "+0.900" in txt


def test_verdict_line_says_icir_is_reference_only():
    """判定行必须传递「ICIR 仅作参考」✗。"""
    rep = {"verdict": {"status": "通过",
                       "detail": "ICIR 仅作方向参考，不作采纳依据"}}
    txt = R.verdict_line(rep)
    assert "通过" in txt and "不作采纳依据" in txt
