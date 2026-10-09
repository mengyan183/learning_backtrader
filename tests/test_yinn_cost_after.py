# -*- coding: utf-8 -*-
"""YINN 成本后净收益取证脚本测试（第 12.35 条**检验 2**，第 12.37 条口径）。

`scripts/yinn_cost_after.py` 不是包内模块，用 importlib 直接加载
（同 `tests/test_screen_yinn_momentum.py` 的做法）。

重点验证四件事：
1. **净价差算法正确** —— 用合成数据手算可复核。
2. **否证能力** —— 成本 > 价差时必须判**不通过**；只会说"通过"的工具等于没做检验。
3. **双边交易成本真的被计入** —— 把它设为 0 必须改变结果（否则漏项）。
4. **复用既有切点 / 工具** —— 与 `screen_yinn_momentum` 逐字一致，数字才可比。
"""
import ast
import importlib.util
import pathlib

import pytest

from fg_system import config

_PATH = (pathlib.Path(__file__).resolve().parent.parent
         / "scripts" / "yinn_cost_after.py")
_spec = importlib.util.spec_from_file_location("yinn_cost_after", _PATH)
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


# ---------------------------------------------------------------- 红线（§4.5 约束 1）

def test_underlying_is_the_unleveraged_etf_from_config():
    """收益目标必须是**无杠杆底层** FXI，**不是** 3× 的 YINN（§4.5 约束 1）。"""
    assert ca.UNDERLYING == "FXI"
    assert ca.UNDERLYING == config.SIGNAL_UNDERLYING_MAP["YINN"], \
        "底层映射必须来自 config，不得在脚本里硬编码"


def test_horizon_is_only_120():
    """§12.36 的符号稳定性**唯一确定** horizon = 120 ⇒ 不是搜索。"""
    assert ca.HORIZON == 120


def test_splits_match_screen_yinn_momentum():
    """子区间切点必须与 `screen_yinn_momentum.SPLITS` 逐字一致，否则数字不可比。"""
    assert ca.SPLITS == ca.screen_yinn_momentum.SPLITS


def test_factor_reuses_screen_yinn_momentum_definition():
    """因子必须复用 `screen_yinn_momentum.CANDIDATES["kweb_price"]`（同一定义才可比）。"""
    import numpy as np
    import pandas as pd
    n = 1400
    idx = pd.date_range("2019-10-01", periods=n, freq="B")
    base = np.linspace(50.0, 120.0, n)
    close = pd.DataFrame(
        {s: base * (1.0 + 0.01 * i)
         for i, s in enumerate(["FXI", "MCHI", "KWEB", "YINN"])}, index=idx)
    want = ca.screen_yinn_momentum.CANDIDATES["kweb_price"](close)
    pd.testing.assert_series_equal(ca.factor(close), want)


# ---------------------------------------------------------------- 净价差算法

def test_net_spread_computation_is_exactly_the_formula():
    """手算复核：`净价差 = 价差 − total_annual*(120/252) − (佣金+滑点)`。"""
    total_annual = 0.20
    spread = 0.15
    trade_cost = config.COMMISSION + config.SLIPPAGE
    got = ca.net_spread(spread, total_annual, trade_cost)
    want = 0.15 - 0.20 * (120.0 / 252.0) - trade_cost
    assert got == pytest.approx(want)


def test_net_spread_verdict_passes_when_positive():
    """净价差 > 0 ⇒ 判通过。"""
    spread = 0.50
    out = ca.judge(spread, total_annual=0.05,
                   trade_cost=config.COMMISSION + config.SLIPPAGE)
    assert out["net_spread"] > 0
    assert out["passed"] is True


# ---------------------------------------------------------------- 否证能力

def test_verdict_fails_when_cost_exceeds_spread():
    """**核心否证能力**：成本 > 价差 ⇒ 净价差 < 0 ⇒ 必须判**不通过**。

    只会说"通过"的工具没有检验价值；这里把 `total_annual` 设得远大于 `spread`。
    """
    out = ca.judge(spread=0.05, total_annual=1.00,
                   trade_cost=config.COMMISSION + config.SLIPPAGE)
    assert out["net_spread"] < 0
    assert out["passed"] is False


def test_verdict_fails_when_spread_is_zero_after_costs():
    """价差恰好等于成本之和（含双边）⇒ 净价差 = 0 ⇒ **不通过**（要求严格 > 0）。"""
    total_annual = 0.20
    trade_cost = config.COMMISSION + config.SLIPPAGE
    spread = total_annual * (120.0 / 252.0) + trade_cost
    out = ca.judge(spread, total_annual=total_annual, trade_cost=trade_cost)
    assert out["net_spread"] == pytest.approx(0.0, abs=1e-12)
    assert out["passed"] is False


# ---------------------------------------------------------------- 双边成本被计入

def test_two_sided_trade_cost_is_counted():
    """把双边成本设为 0，结果必须**变化** —— 否则漏计了换手成本。

    用极小的价差使结果刚好落在成本两侧，从而判定翻转。
    """
    total_annual = 0.10
    spread = 0.10 * (120.0 / 252.0) + 0.0005          # 只够覆盖一半的双边成本
    with_cost = ca.judge(spread, total_annual=total_annual,
                         trade_cost=config.COMMISSION + config.SLIPPAGE)
    without_cost = ca.judge(spread, total_annual=total_annual, trade_cost=0.0)
    assert with_cost["net_spread"] != without_cost["net_spread"], \
        "双边成本没有被计入净价差"
    assert with_cost["passed"] is False
    assert without_cost["passed"] is True, "去掉双边成本后应刚好转正"


# ---------------------------------------------------------------- 分段工具复用

def test_decompose_reuses_leverage_module():
    """损耗标定必须复用 `fg_system/leverage.py::decompose`（**禁止**自己实现）。"""
    import fg_system.leverage as lev
    assert ca.leverage.decompose is lev.decompose


# ---------------------------------------------------------------- 可直接运行

def test_script_injects_repo_root_before_importing_fg_system():
    """**实测踩到的坑**：`py -3.10 scripts/xxx.py` 时 sys.path[0] 是 `scripts/`、
    **不含仓库根** ⇒ `from fg_system import config` 直接 ModuleNotFoundError。

    用 **AST 断言**而非"某字符串出现过"（§12.27-①）：顺序错了照样会崩。
    """
    tree = ast.parse(_PATH.read_text(encoding="utf-8"))
    syspath, fg = [], []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "insert"
                and ast.unparse(node.func.value) == "sys.path"):
            syspath.append(node.lineno)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("fg_system"):
            fg.append(node.lineno)
        if isinstance(node, ast.Import) and any(
                a.name.startswith("fg_system") for a in node.names):
            fg.append(node.lineno)
    assert syspath, "脚本必须把仓库根注入 sys.path"
    assert fg, "脚本必须导入 fg_system"
    assert min(syspath) < min(fg), "sys.path 注入必须在 fg_system 导入**之前**"
