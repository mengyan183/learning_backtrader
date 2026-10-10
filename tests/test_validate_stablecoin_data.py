# -*- coding: utf-8 -*-
"""WT-10 稳定币数据质量校验测试。

**不读真实 Data/**：全部用 tmp_path 造 CSV（WT-08 同类要求的先例）。
"""
import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import validate_stablecoin_data as V  # noqa: E402


def _write(tmp_path, rows, cols=None):
    path = tmp_path / "u.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(cols or V.COLUMNS)
        for row in rows:
            writer.writerow(row)
    return str(path)


def test_help_runs():
    with pytest.raises(SystemExit) as exc:
        V.main(["--help"])
    assert exc.value.code == 0


def test_missing_file_exits_2_and_hints_fetch(tmp_path, capsys):
    """无数据 → 退出 2，且提示先跑 fetch_stablecoin_usage.py（验收标准）。"""
    rc = V.main(["--in", str(tmp_path / "nope.csv")])
    assert rc == 2
    assert "fetch_stablecoin_usage" in capsys.readouterr().err


def test_clean_data_passes(tmp_path):
    rows = [["2026-01-%02d" % d, "USDC", 100 + d, 50 + d, 2.0] for d in range(1, 11)]
    assert V.main(["--in", _write(tmp_path, rows)]) == 0


def test_bad_columns_exits_2(tmp_path):
    rc = V.main(["--in", _write(tmp_path, [["2026-01-01", "USDC"]],
                               cols=["date", "symbol"])])
    assert rc == 2


def test_anomalies_reported_and_rc_1(tmp_path, capsys):
    """≤0 与环比 >10× 都要进异常清单，退出码 1。"""
    rows = [["2026-01-01", "USDC", 100, 50, 2.0],
            ["2026-01-02", "USDC", 0, 50, 0.0],            # ≤0
            ["2026-01-03", "USDC", 100000, 50, 2000.0]]    # 跳变 >10×
    rc = V.main(["--in", _write(tmp_path, rows)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "≤0" in out
    assert "跳变" in out
    assert "缺失率" in out


def test_missing_rate_warns(tmp_path, capsys):
    """缺失率 >5% 触发告警。"""
    rows = [["2026-01-01", "USDC", 100, 50, 2.0],
            ["2026-01-02", "USDC", "", 50, ""]]            # 2/2 行缺 → 50%
    assert V.main(["--in", _write(tmp_path, rows)]) == 1
    assert "缺失率超阈值" in capsys.readouterr().out
