# -*- coding: utf-8 -*-
"""`scripts/sync_positions.py` 的未实现盈亏自算（WT-43）。

背景（2026-10-19）：`accounts.csv` 的 `unrealized_pnl` 取自 `accinfo_query` 的
`unrealized_pl` 字段 ✗，该字段在部分 FutuOpenD 版本**不存在** ✗ ⇒ `r.get(..., 0)`
**静默写 0.0** ✗（实测 10-16 快照 = 0.0，而持仓全在浮亏 ✓）。
⇒ 改为**由持仓行自算** `Σ qty×(price−cost)` ✓，本文件锁住该行为。
"""
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "sync_positions.py")


def _load():
    spec = importlib.util.spec_from_file_location("sync_positions", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sp = _load()


def test_sum_unrealized_basic():
    """qty×(price−cost) 逐行求和；行格式 = positions.csv 的 12 列。"""
    rows = [
        # date, account, symbol, name, qty, price, cost, ...
        ["2026-10-16", "stock", "AXTX", "2倍做多AXTI", 48.0, 20.6, 24.0, 988.8, 988.8, "", "system", "USD"],
        ["2026-10-16", "stock", "GDXU", "3倍做多GDX", 42.0, 100.63, 90.0, 4226.46, 4226.46, "", "system", "USD"],
    ]
    # 48×(20.6−24.0) = −163.2 ; 42×(100.63−90.0) = 446.46 ⇒ 合计 283.26
    assert sp._sum_unrealized(rows) == 283.26


def test_sum_unrealized_negative_and_empty():
    """全浮亏 ⇒ 负数 ✓；无持仓 ⇒ 0.0 ✓（不得返回 None ✗）。"""
    rows = [["d", "stock", "X", "x", 10.0, 9.0, 10.0, 90.0, 90.0, "", "system", "USD"]]
    assert sp._sum_unrealized(rows) == -10.0
    assert sp._sum_unrealized([]) == 0.0


def test_sum_unrealized_skips_rows_without_cost():
    """`cost` 缺失/为 0 ⇒ 跳过该行 ✓（避免除零式噪声 ✗）。"""
    rows = [
        ["d", "stock", "A", "a", 10.0, 9.0, 0.0, 90.0, 90.0, "", "system", "USD"],
        ["d", "stock", "B", "b", 5.0, 11.0, 10.0, 55.0, 55.0, "", "system", "USD"],
    ]
    assert sp._sum_unrealized(rows) == 5.0
