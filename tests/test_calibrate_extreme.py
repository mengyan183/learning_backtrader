# -*- coding: utf-8 -*-
"""WT-08 `scripts/calibrate_extreme.py` 测试。

**不读真实 Data/**：用 tmp_path 造 features.csv / prices.csv，
并用 monkeypatch 把模块级路径常量 FEATURES / PRICES 指到 tmp_path。
"""
import importlib.util
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "calibrate_extreme.py")


def _load():
    """每次加载新鲜模块，避免测试间全局状态串扰。"""
    spec = importlib.util.spec_from_file_location("calibrate_extreme", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ce = _load()


def _write_features(tmp_path, rows):
    path = tmp_path / "features.csv"
    header = "date,fg_index,circuit_breaker,extreme\n"
    body = "".join("%s,%s,%s,%s\n" % r for r in rows)
    path.write_text(header + body, encoding="utf-8")
    return str(path)


def _write_prices(tmp_path, rows):
    path = tmp_path / "prices.csv"
    header = "date,symbol,close\n"
    body = "".join("%s,%s,%s\n" % r for r in rows)
    path.write_text(header + body, encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------ 纯函数
def test_is_true_accepts_variants():
    assert ce._is_true("true") is True
    assert ce._is_true("1") is True
    assert ce._is_true("YES") is True
    assert ce._is_true(" false ") is False
    assert ce._is_true("") is False


def test_forward_return_horizon_and_insufficient():
    """第 horizon 个交易日收益；数据不足返回 None。"""
    series = [("2026-01-01", 100.0), ("2026-01-02", 110.0), ("2026-01-03", 121.0)]
    assert ce.forward_return(series, "2026-01-01", 1) == pytest.approx(0.10)
    assert ce.forward_return(series, "2026-01-01", 2) == pytest.approx(0.21)
    # 命中索引 + horizon 越界 → None
    assert ce.forward_return(series, "2026-01-01", 3) is None
    # 日期不存在 → None
    assert ce.forward_return(series, "2099-01-01", 1) is None


def test_forward_return_zero_base_is_none():
    series = [("2026-01-01", 0.0), ("2026-01-02", 5.0)]
    assert ce.forward_return(series, "2026-01-01", 1) is None


def test_load_triggers_missing_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(ce, "FEATURES", str(tmp_path / "nope.csv"))
    assert ce.load_triggers() is None


def test_load_triggers_collects_flagged_rows(monkeypatch, tmp_path):
    import math
    path = _write_features(tmp_path, [
        ("2026-01-01", 90.0, "true", "false"),
        ("2026-01-02", 5.0, "false", "1"),
        ("2026-01-03", "abc", "true", "false"),   # 非数值 fg → ValueError → 跳过
        ("2026-01-04", "nan", "true", "false"),   # "nan" 可转 float ⇒ 保留为 nan
    ])
    monkeypatch.setattr(ce, "FEATURES", path)
    trig = ce.load_triggers()
    cb = trig["circuit_breaker"]
    assert [d for d, _ in cb] == ["2026-01-01", "2026-01-04"]      # "abc" 行被跳过
    assert cb[0][1] == 90.0
    assert math.isnan(cb[1][1])
    assert trig["extreme"] == [("2026-01-02", 5.0)]


def test_load_prices_sorts_and_filters(monkeypatch, tmp_path):
    path = _write_prices(tmp_path, [
        ("2026-01-03", "SPY", 103.0),
        ("2026-01-01", "SPY", 101.0),
        ("2026-01-02", "QQQ", 202.0),
    ])
    monkeypatch.setattr(ce, "PRICES", path)
    series = ce.load_prices({"SPY"})
    assert list(series) == ["SPY"]
    assert [d for d, _ in series["SPY"]] == ["2026-01-01", "2026-01-03"]  # 升序


# ------------------------------------------------------------------ main 分支
def test_main_missing_features_returns_0(monkeypatch, tmp_path, capsys):
    """缺 features.csv ⇒ 打印样本不足并返回 0（验收：不是错误）。"""
    monkeypatch.setattr(ce, "FEATURES", str(tmp_path / "nope.csv"))
    rc = ce.main()
    assert rc == 0
    assert "样本不足" in capsys.readouterr().out


def test_main_zero_triggers_reports_insufficient(monkeypatch, tmp_path, capsys):
    """有文件但 0 次触发 ⇒ 打印「样本不足（0 次触发）」并返回 0。"""
    feat = _write_features(tmp_path, [("2026-01-01", 50.0, "false", "false")])
    prices = _write_prices(tmp_path, [("2026-01-01", "SPY", 100.0)])
    monkeypatch.setattr(ce, "FEATURES", feat)
    monkeypatch.setattr(ce, "PRICES", prices)
    rc = ce.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "样本不足（0 次触发）" in out
    assert "校准证据表产出完成" in out


def test_main_few_triggers_reports_below_min(monkeypatch, tmp_path, capsys):
    """触发次数 < MIN_EVENTS ⇒ 判「样本不足（n < 10 次）」，只登记不判结论。"""
    rows = [("2026-01-%02d" % d, 88.0, "true", "false") for d in range(1, 4)]
    monkeypatch.setattr(ce, "FEATURES", _write_features(tmp_path, rows))
    monkeypatch.setattr(ce, "PRICES", _write_prices(tmp_path, []))
    rc = ce.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "样本不足**（3 < 10 次）" in out
    assert "样本不足的项：circuit_breaker" in out


def test_main_enough_triggers_prints_forward_returns(monkeypatch, tmp_path, capsys):
    """触发次数 >= MIN_EVENTS ⇒ 打印前瞻收益表（T+4/8/16）。"""
    n = ce.MIN_EVENTS
    rows = [("2026-01-%02d" % d, 88.0, "true", "false") for d in range(1, n + 1)]
    monkeypatch.setattr(ce, "FEATURES", _write_features(tmp_path, rows))
    # 价格序列足够长（> n + max horizon），使 forward_return 有值
    # 用生产 SYMBOLS（TQQQ）使 load_prices 的过滤通过
    prices = [("2026-01-%02d" % d, "TQQQ", 100.0 + d) for d in range(1, n + 20)]
    monkeypatch.setattr(ce, "PRICES", _write_prices(tmp_path, prices))
    rc = ce.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "触发后前瞻收益" in out
    assert "T+4" in out and "T+8" in out and "T+16" in out
    assert "TQQQ" in out
