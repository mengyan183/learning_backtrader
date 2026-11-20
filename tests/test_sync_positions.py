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


def test_refuses_to_overwrite_existing_snapshot(monkeypatch):
    """当日快照已存在 ⇒ **默认拒绝覆盖** ✓（2026-11-20 实测事故）。

    盘后手动补跑（北京 11-20 11:26 = 美东 11-19 22:26）会被
    `trading_date()` 判成 11-19 ⇒ 把「11-19 收盘 6 个持仓」覆盖成
    「盘后清仓后的 2 个」✗ ⇒ 历史时间轴错一天，且 `derive_trades`
    靠相邻日差集反推 ⇒ 反推不出卖出 ✗
    """
    import pandas as pd

    date = "2026-11-19"
    a = pd.DataFrame([{"date": date, "account": "futu", "net_value": 1.0}])
    p = pd.DataFrame([{"date": date, "symbol": "YINN", "quantity": 1}])

    monkeypatch.setattr(sp, "load_existing", lambda: (a.copy(), p.copy()))
    monkeypatch.setattr(sp, "trading_date", lambda: date)
    monkeypatch.setattr(sp, "write_snapshot",
                        lambda *x: (_ for _ in ()).throw(
                            AssertionError("不该写盘 ✗")))
    monkeypatch.setenv("FG_SYNC_MODE", "live")
    monkeypatch.setattr(sp.sys, "argv", ["sync_positions.py"])

    assert sp.main() == 0, "拒绝覆盖时应当安静返回 0（不是失败）"


def test_allow_overwrite_flag_lets_it_through(monkeypatch):
    """显式 `--allow-overwrite` ⇒ 不再拦在门口 ✓。"""
    import pandas as pd

    date = "2026-11-19"
    a = pd.DataFrame([{"date": date, "account": "futu", "net_value": 1.0}])
    p = pd.DataFrame([{"date": date, "symbol": "YINN", "quantity": 1}])
    called = {"n": 0}

    monkeypatch.setattr(sp, "load_existing", lambda: (a.copy(), p.copy()))
    monkeypatch.setattr(sp, "trading_date", lambda: date)
    monkeypatch.setattr(sp, "futu_health", type("H", (), {
        "preflight": staticmethod(lambda: (False, "测试跳过")),
        "guard": staticmethod(lambda **kw: None),
        "done": staticmethod(lambda: None),
        "write_status": staticmethod(lambda *a, **kw: None),
    }))
    monkeypatch.setattr(sp, "sync_okx", lambda acc, pos, d: (acc, pos))
    monkeypatch.setattr(sp, "write_snapshot",
                        lambda acc, pos: called.__setitem__("n", 1))
    monkeypatch.setenv("FG_SYNC_MODE", "live")
    monkeypatch.setattr(sp.sys, "argv",
                        ["sync_positions.py", "--allow-overwrite"])

    sp.main()
    # 两源都没新增 ⇒ 走「不写盘」分支，但**已经过了覆盖检查** ✓
    assert called["n"] == 0
