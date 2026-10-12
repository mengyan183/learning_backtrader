"""守卫测试：回测基准单一事实源（Windows WT 自查缺口 #3，2026-10-12）。

断言：
1. config.BACKTEST_BASELINE 存在且 stock/crypto 两个 sleeve 均有合法数值；
2. cli.py 不再内嵌基准数字字面量（-28.8 / 11.6 / -29.8 / -1.9 等），
   防止回退到硬编码双维护。
"""
import re
from pathlib import Path

from fg_system import config

CLI = Path("fg_system/cli.py").read_text(encoding="utf-8")
FORBIDDEN = ["-28.8", "11.6", "-29.8", "-1.9", "-34.30", "-1.42"]


def test_config_has_baseline():
    bb = config.BACKTEST_BASELINE
    assert "stock" in bb and "crypto" in bb
    for k in ("max_drawdown_pct", "annualized_pct"):
        assert isinstance(bb["stock"][k], (int, float))
        assert isinstance(bb["crypto"][k], (int, float))
    assert bb["stock"]["max_drawdown_pct"] < 0
    assert bb["crypto"]["max_drawdown_pct"] < 0


def test_cli_uses_config_not_hardcoded():
    assert "BACKTEST_BASELINE" in CLI
    # cli.py 中不允许残留基准数字字面量（守卫：只能改 config 一处）
    for s in FORBIDDEN:
        assert s not in CLI, f"cli.py 残留硬编码基准数字 {s}"


def test_values_match_previous_printed_baseline():
    bb = config.BACKTEST_BASELINE
    assert abs(bb["stock"]["max_drawdown_pct"] - (-28.8)) < 1e-6
    assert abs(bb["stock"]["annualized_pct"] - 11.6) < 1e-6
    assert abs(bb["crypto"]["max_drawdown_pct"] - (-29.8)) < 1e-6
    assert abs(bb["crypto"]["annualized_pct"] - (-1.9)) < 1e-6
