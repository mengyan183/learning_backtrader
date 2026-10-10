# -*- coding: utf-8 -*-
"""WT-08 `scripts/execution_confirm.py` 测试。

**不读真实 Data/**：用 monkeypatch 把模块级 REPO / OUT_DIR 指到 tmp_path，
并用 tmp_path 造 positions.csv 与 shoutu_fng.csv。
"""
import importlib.util
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "execution_confirm.py")


def _load():
    spec = importlib.util.spec_from_file_location("execution_confirm", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ec = _load()

POS_HEAD = "date,symbol,qty,price,cost,market_value,bucket\n"
SHT_HEAD = "date,symbol,value\n"


def _write_pos(tmp_path, rows):
    """写到 tmp_path/Data/positions.csv（脚本拼 REPO/Data/...）。"""
    d = tmp_path / "Data"
    d.mkdir(exist_ok=True)
    (d / "positions.csv").write_text(
        POS_HEAD + "".join(",".join(str(c) for c in r) + "\n" for r in rows),
        encoding="utf-8")


def _write_sht(tmp_path, rows):
    """写到 tmp_path/Data/raw/shoutu_fng.csv。"""
    raw = tmp_path / "Data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "shoutu_fng.csv").write_text(
        SHT_HEAD + "".join("%s,%s,%s\n" % r for r in rows), encoding="utf-8")


@pytest.fixture
def patched(monkeypatch, tmp_path):
    monkeypatch.setattr(ec, "REPO", str(tmp_path))
    monkeypatch.setattr(ec, "OUT_DIR", str(tmp_path / "execution"))
    return tmp_path


# ------------------------------------------------------------------ argparse
def test_help_runs(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["execution_confirm.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        ec.main()
    assert exc.value.code == 0
    assert "--finalize" in capsys.readouterr().out


# ------------------------------------------------------------------ zone_of（纯函数）
def test_zone_of_boundaries():
    assert ec.zone_of(-100) == 0
    assert ec.zone_of(-61) == 0
    assert ec.zone_of(-60) == 1
    assert ec.zone_of(-1) == 1
    assert ec.zone_of(0) == 2
    assert ec.zone_of(59) == 2
    assert ec.zone_of(60) == 3
    assert ec.zone_of(99) == 3
    assert ec.zone_of(100) == 4


# ------------------------------------------------------------------ build_rows 分支
def test_build_rows_buy_zone(patched):
    """系数 <= 买入线 ⇒ 买入区。用 TQQQ（3X，buy=-70）。"""
    _write_pos(patched, [("2026-01-01", "TQQQ", 10, 50.0, 40.0, 500.0, 3)])
    _write_sht(patched, [("2026-01-01", "TQQQ", -80.0)])
    rows = ec.build_rows()
    r = [x for x in rows if x["sym"] == "TQQQ"][0]
    assert "买入区" in r["action"]
    assert r["v"] == -80.0
    assert r["pnl"] == pytest.approx((50.0 - 40.0) / 40.0)


def test_build_rows_sell_zone(patched):
    """系数 >= 卖出线 ⇒ 卖出区。TQQQ sell=50。"""
    _write_pos(patched, [("2026-01-01", "TQQQ", 10, 50.0, 40.0, 500.0, 3)])
    _write_sht(patched, [("2026-01-01", "TQQQ", 55.0)])
    r = [x for x in ec.build_rows() if x["sym"] == "TQQQ"][0]
    assert "卖出区" in r["action"]


def test_build_rows_watch_zone(patched):
    """买入线 < 系数 < 卖出线 ⇒ 观望。"""
    _write_pos(patched, [("2026-01-01", "TQQQ", 10, 50.0, 40.0, 500.0, 3)])
    _write_sht(patched, [("2026-01-01", "TQQQ", 0.0)])
    r = [x for x in ec.build_rows() if x["sym"] == "TQQQ"][0]
    assert r["action"] == "观望"


def test_build_rows_missing_shoutu(patched):
    """守猪待兔无该标的 ⇒ 数据缺失分支。"""
    _write_pos(patched, [("2026-01-01", "TQQQ", 10, 50.0, 40.0, 500.0, 3)])
    _write_sht(patched, [("2026-01-01", "SOXL", -80.0)])   # 无 TQQQ
    r = [x for x in ec.build_rows() if x["sym"] == "TQQQ"][0]
    assert r["v"] is None
    assert "数据缺失" in r["action"]


def test_latest_positions_keeps_last_row_per_symbol(patched):
    _write_pos(patched, [("2026-01-01", "TQQQ", 10, 50.0, 40.0, 500.0, 3),
                         ("2026-01-02", "TQQQ", 12, 51.0, 40.0, 612.0, 3)])
    pos = ec.latest_positions()
    assert pos.loc["TQQQ", "qty"] == 12


# ------------------------------------------------------------------ 文件产物
def test_write_confirm_creates_file(patched, capsys):
    _write_pos(patched, [("2026-01-01", "TQQQ", 10, 50.0, 40.0, 500.0, 3)])
    _write_sht(patched, [("2026-01-01", "TQQQ", -80.0)])
    ec.write_confirm()
    files = list((patched / "execution").glob("confirm-*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "执行确认清单" in text and "TQQQ" in text


def test_write_instructions_only_actionable(patched):
    """--finalize：仅买/卖区进指令；观望与数据缺失被跳过。

    注：脚本 `write_instructions` 不自建 OUT_DIR（仅 `write_confirm` 建），
    故测试先创建 execution/ 目录，模拟真实调用顺序。
    """
    (patched / "execution").mkdir(exist_ok=True)
    _write_pos(patched, [("2026-01-01", "TQQQ", 10, 50.0, 40.0, 500.0, 3),
                         ("2026-01-01", "SOXL", 5, 20.0, 25.0, 100.0, 3)])
    _write_sht(patched, [("2026-01-01", "TQQQ", -80.0),   # 买入区
                         ("2026-01-01", "SOXL", 0.0)])     # 观望
    ec.write_instructions()
    files = list((patched / "execution").glob("instructions-*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "TQQQ" in text and "买入(加仓参考)" in text
    assert "SOXL" not in text                       # 观望不入指令


def test_main_finalize_branch(patched, monkeypatch):
    (patched / "execution").mkdir(exist_ok=True)
    _write_pos(patched, [("2026-01-01", "TQQQ", 10, 50.0, 40.0, 500.0, 3)])
    _write_sht(patched, [("2026-01-01", "TQQQ", -80.0)])
    monkeypatch.setattr("sys.argv", ["execution_confirm.py", "--finalize"])
    ec.main()
    assert list((patched / "execution").glob("instructions-*.md"))


def test_main_confirm_branch(patched, monkeypatch):
    _write_pos(patched, [("2026-01-01", "TQQQ", 10, 50.0, 40.0, 500.0, 3)])
    _write_sht(patched, [("2026-01-01", "TQQQ", -80.0)])
    monkeypatch.setattr("sys.argv", ["execution_confirm.py"])
    ec.main()
    assert list((patched / "execution").glob("confirm-*.md"))
