# -*- coding: utf-8 -*-
"""YINN 动量取证脚本测试（第 12.35 条**检验 1**，第 13.4 条否证性取证）。

`scripts/screen_yinn_momentum.py` 不是包内模块，用 importlib 直接加载
（同 `tests/test_portfolio_check.py` 的做法）。

重点验证三件事：
1. **复用 §12.17 的同一因子定义** —— 换定义会让数字与 §12.17 **不可比**。
2. **否证能力**：样本外符号翻转必须判为**不通过**。只会说「通过」的工具等于没做检验。
3. **红线**：因子输入与收益目标都必须是**无杠杆底层**（§4.5 约束 1）。
"""
import ast
import importlib.util
import pathlib

import numpy as np
import pandas as pd
import pytest

from fg_system import config

_PATH = (pathlib.Path(__file__).resolve().parent.parent
         / "scripts" / "screen_yinn_momentum.py")
_spec = importlib.util.spec_from_file_location("screen_yinn_momentum", _PATH)
ym = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ym)


def _index(n):
    """2019-10-01 起的 n 个交易日 —— 足以同时覆盖样本内与样本外两段。"""
    return pd.date_range("2019-10-01", periods=n, freq="B")


# ---------------------------------------------------------------- 红线（§4.5 约束 1）

def test_underlying_is_the_unleveraged_etf_from_config():
    """收益目标必须是**无杠杆底层** FXI，**不是** 3× 的 YINN。

    用 YINN 自身价格做收益目标会把 3× 杠杆的波动衰减混进「动量」里，
    与 §12.17 的口径也不可比。
    """
    assert ym.UNDERLYING == "FXI"
    assert ym.UNDERLYING == config.SIGNAL_UNDERLYING_MAP["YINN"], \
        "底层映射必须来自 config，不得在脚本里硬编码"


def test_candidates_are_exactly_the_three_from_the_plan():
    """§12.35 只列了 3 个候选 ⇒ 锁死集合，防止演变成**参数搜索**。"""
    assert set(ym.CANDIDATES) == {"kweb_price", "mchi_price", "fxi_price"}


def _close(n=1400):
    idx = pd.date_range("2016-09-19", periods=n, freq="B")
    base = np.linspace(50.0, 120.0, n)
    return pd.DataFrame(
        {s: base * (1.0 + 0.01 * i)
         for i, s in enumerate(["FXI", "MCHI", "KWEB", "YINN"])}, index=idx)


def test_candidate_factors_reuse_screen_factors_definition():
    """必须复用 `screen_factors.price_composite` —— 与 §12.17 同一定义才可比。"""
    close = _close()
    want = ym.screen_factors.price_composite(close["KWEB"])
    pd.testing.assert_series_equal(ym.CANDIDATES["kweb_price"](close), want)


def test_candidate_factors_never_read_the_leveraged_etf():
    """把 YINN 列全部置 NaN：若某候选读了它，输出必然全 NaN。"""
    close = _close()
    close["YINN"] = np.nan
    for name, fn in ym.CANDIDATES.items():
        got = fn(close)
        assert got.notna().sum() > 0, "%s 读了杠杆标的（或未产出任何值）" % name


# ---------------------------------------------------------------- 动量方向判定

def test_momentum_screen_passes_when_all_segments_positive():
    """贪婪 → 未来收益**更高**（动量）⇒ IC > 0，三段同号即通过。"""
    idx = _index(1800)
    f = pd.Series(np.linspace(0.0, 1.0, 1800), index=idx)
    out = ym.momentum_screen(f, 0.2 * f)
    assert out["ic"] == pytest.approx(1.0)
    assert [name for name, _ in out["ic_splits"]] == ["全样本", "样本内", "样本外"]
    assert out["stable_positive"] is True
    assert out["degenerate"] is False
    assert out["passed"] is True
    assert out["spread"] < 0, "screening 的 spread 是「恐惧组 − 贪婪组」，动量下应 < 0"
    assert out["hit"] < 0.5, "screening 的 hit 是 P(恐惧>贪婪)，动量下应 < 0.5"
    assert out["n"] == 1800


def test_momentum_screen_fails_when_out_of_sample_flips():
    """**核心否证能力**：样本内为正、样本外翻负 ⇒ 必须判为不通过。

    §12.35 的检验 1 明确「重点：样本外是否仍为正」——
    只在样本外翻负时判不通过，工具才有否证能力。
    """
    idx = _index(1800)
    f = pd.Series(np.linspace(0.0, 1.0, 1800), index=idx)
    r = 0.2 * f
    oos = idx >= "2023-01-01"
    assert oos.any() and (~oos).any(), "两段都必须有样本，否则测试无意义"
    r[oos] = -0.2 * f[oos]

    out = ym.momentum_screen(f, r)
    ics = dict(out["ic_splits"])
    assert ics["样本内"] > 0
    assert ics["样本外"] < 0
    assert out["stable_positive"] is False
    assert out["passed"] is False


def test_momentum_screen_rejects_degenerate_even_with_positive_ic():
    """**退化优先**：因子塌缩到单一分组时 `ic` 是伪影，方向再"对"也必须拒绝。

    `splits=[]` 把判定隔离到全样本 IC 上，专门验证「退化 ⇒ 拒绝」这一条门槛。
    """
    idx = _index(800)
    f = pd.Series([0.0] * 400 + [1.0] * 400, index=idx)
    out = ym.momentum_screen(f, f.copy(), splits=[])      # IC 恰好 +1.0
    assert out["ic"] == pytest.approx(1.0)
    assert out["stable_positive"] is True
    assert out["degenerate"] is True
    assert out["passed"] is False


def test_momentum_screen_rejects_nan_ic():
    """样本不足时 `ic` 为 NaN（`min_n=60`）⇒ 禁止据此下结论。"""
    idx = _index(30)
    f = pd.Series(np.linspace(0.0, 1.0, 30), index=idx)
    out = ym.momentum_screen(f, 0.2 * f, splits=[])
    assert np.isnan(out["ic"])
    assert out["stable_positive"] is False
    assert out["passed"] is False


def test_splits_match_screen_factors():
    """子区间切点必须与 §12.17 逐字一致，否则数字不可比。"""
    assert ym.SPLITS == ym.screen_factors.SPLITS
    assert ym.HORIZONS == ym.screen_factors.HORIZONS


# ---------------------------------------------------------------- 可直接运行

def test_script_injects_repo_root_before_importing_fg_system():
    """**实测踩到的坑**：`py -3.10 scripts/screen_yinn_momentum.py` 时 sys.path[0]
    是 `scripts/`、**不含仓库根** ⇒ `from fg_system import config` 直接
    `ModuleNotFoundError`（本仓库其余脚本都有同一行注入，`screen_factors.py` 缺了）。

    用 **AST 断言**而非"某字符串出现过"（§12.27-①）：顺序错了照样会崩，
    字符串守卫抓不到顺序。
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
