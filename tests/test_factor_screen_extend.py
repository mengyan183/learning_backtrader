# -*- coding: utf-8 -*-
"""WT-09 新因子候选（F-010~F-012）测试：scripts/factor_screen_extend.py。

纪律：
- **绝不读真实 `Data/`** —— 全部用 `tmp_path` / 内存 DataFrame 造数据。
- 不调用会写文件的路径（`main()` 无 `--list` 时会写 evolution/，本测试不碰）。
- 覆盖三件事：`--list` 含新因子；每个新 factor 函数的返回值形状/数值；
  缺列或空数据时的行为（返回空 Series，不抛异常）。

`scripts/` 不是包内模块，用 importlib 直接加载（同 tests/test_screen_yinn_momentum.py）。
"""
import importlib.util
import pathlib

import numpy as np
import pandas as pd
import pytest

_PATH = (pathlib.Path(__file__).resolve().parent.parent
         / "scripts" / "factor_screen_extend.py")
_spec = importlib.util.spec_from_file_location("factor_screen_extend", _PATH)
fse = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fse)


# ---------------------------------------------------------------- --list / 注册表

def test_registry_contains_new_candidates():
    """F-010 / F-011 / F-012 必须已注册。"""
    assert {"F-010", "F-011", "F-012"} <= set(fse.FACTORS)
    for fid in ("F-010", "F-011", "F-012"):
        meta = fse.FACTORS[fid]
        assert meta["name"] and meta["formula"] and meta["direction"]


def test_list_factors_prints_new_names():
    """`--list` 文本含新因子名与编号。"""
    text = fse.list_factors()
    for fid in ("F-010", "F-011", "F-012"):
        assert fid in text
    assert "新闻情绪" in text
    assert "Put-Call" in text
    assert "波动率结构" in text


def test_main_list_does_not_touch_data(monkeypatch, capsys):
    """`main(['--list'])` 必须在**读任何 Data 之前**返回。

    把 `_load` 换成会爆炸的桩：若 --list 分支仍去读数据，测试立即失败。
    """
    def _boom(*a, **k):
        raise AssertionError("--list 不应读取任何数据")

    monkeypatch.setattr(fse, "_load", _boom)
    fse.main(["--list"])
    out = capsys.readouterr().out
    assert "F-010" in out and "F-012" in out


# ---------------------------------------------------------------- F-010 新闻情绪

def test_news_sentiment_returns_score_series():
    """默认取 mkt_score，按 date 排序、去重。"""
    news = pd.DataFrame({
        "date": pd.to_datetime(["2026-10-03", "2026-10-01", "2026-10-02"]),
        "mkt_score": [0.3, 0.1, 0.2],
    })
    s = fse.factor_news_sentiment(news)
    assert list(s.index) == list(pd.to_datetime(
        ["2026-10-01", "2026-10-02", "2026-10-03"]))
    assert list(s.values) == [0.1, 0.2, 0.3]


def test_news_sentiment_custom_column():
    """可指定列（如 crypto_score）。"""
    news = pd.DataFrame({
        "date": pd.to_datetime(["2026-10-01", "2026-10-02"]),
        "crypto_score": [-0.125, 0.5],
    })
    s = fse.factor_news_sentiment(news, score_col="crypto_score")
    assert list(s.values) == [-0.125, 0.5]


def test_news_sentiment_missing_column_returns_empty():
    """缺列时返回空 Series，不抛异常。"""
    news = pd.DataFrame({"date": pd.to_datetime(["2026-10-01"]), "other": [1.0]})
    s = fse.factor_news_sentiment(news)
    assert isinstance(s, pd.Series) and len(s) == 0


def test_news_sentiment_empty_returns_empty():
    """空数据返回空 Series。"""
    s = fse.factor_news_sentiment(pd.DataFrame(columns=["date", "mkt_score"]))
    assert isinstance(s, pd.Series) and len(s) == 0
    assert len(fse.factor_news_sentiment(None)) == 0


# ---------------------------------------------------------------- F-011 Put-Call

def test_putcall_sentiment_reads_put_call_ratio():
    """putcall_total.csv 的列名为 put_call_ratio。"""
    pc = pd.DataFrame({
        "date": pd.to_datetime(["2026-10-02", "2026-10-01"]),
        "put_call_ratio": [0.90, 1.10],
    })
    s = fse.factor_putcall_sentiment(pc)
    assert list(s.index) == list(pd.to_datetime(["2026-10-01", "2026-10-02"]))
    assert list(s.values) == [1.10, 0.90]


def test_putcall_sentiment_accepts_sentiment_csv_column():
    """亦接受 sentiment.csv 的重命名列 putcall_total。"""
    pc = pd.DataFrame({
        "date": pd.to_datetime(["2026-10-01"]),
        "putcall_total": [0.87],
    })
    s = fse.factor_putcall_sentiment(pc)
    assert list(s.values) == [0.87]


def test_putcall_sentiment_missing_column_returns_empty():
    pc = pd.DataFrame({"date": pd.to_datetime(["2026-10-01"]), "calls": [1.0]})
    assert len(fse.factor_putcall_sentiment(pc)) == 0
    assert len(fse.factor_putcall_sentiment(None)) == 0


# ---------------------------------------------------------------- F-012 VIX 期限结构

def test_vix_term_change_computes_rolling_pct_change():
    """term = vix3m_close / vix_close，信号 = term.pct_change(window)。"""
    idx = pd.date_range("2026-01-01", periods=8, freq="B")
    vix = pd.DataFrame({"date": idx, "close": [20.0] * 8})
    vix3m = pd.DataFrame({"date": idx, "close": [22.0, 22.0, 22.0, 22.0,
                                                 22.0, 22.0, 24.2, 22.0]})
    s = fse.factor_vix_term_change(vix, vix3m, window=5)
    # term: 前 6 天 = 1.1；第 7 天(下标6) = 24.2/20 = 1.21
    # pct_change(5)：下标5 起有效。term[5]=1.1, term[0]=1.1 ⇒ 0
    assert s.iloc[:5].isna().all()
    assert s.iloc[5] == pytest.approx(0.0)
    # 下标 6：term[6]=1.21 vs term[1]=1.1 ⇒ +10%
    assert s.iloc[6] == pytest.approx(0.1)


def test_vix_term_change_missing_close_returns_empty():
    idx = pd.date_range("2026-01-01", periods=3, freq="B")
    bad = pd.DataFrame({"date": idx, "value": [1.0, 2.0, 3.0]})
    good = pd.DataFrame({"date": idx, "close": [1.0, 2.0, 3.0]})
    assert len(fse.factor_vix_term_change(bad, good)) == 0
    assert len(fse.factor_vix_term_change(good, bad)) == 0
    assert len(fse.factor_vix_term_change(None, None)) == 0


# ---------------------------------------------------------------- 脚本可导入

def test_sets_utf8_stdout_before_fg_import():
    """AGENTS.md §6.2：脚本必须在导入 fg_system 前设置 stdout UTF-8。

    用 AST 断言顺序（字符串守卫抓不到顺序）。
    """
    import ast
    tree = ast.parse(_PATH.read_text(encoding="utf-8"))
    reconf, fg = [], []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "reconfigure"):
            reconf.append(node.lineno)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("fg_system"):
            fg.append(node.lineno)
    assert reconf, "脚本必须设置 stdout/stderr 编码"
    assert fg, "脚本必须导入 fg_system"
    assert min(reconf) < min(fg), "UTF-8 设置必须在 fg_system 导入之前"
