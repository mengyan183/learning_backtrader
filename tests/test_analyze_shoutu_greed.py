# -*- coding: utf-8 -*-
"""`scripts/analyze_shoutu_greed.py` 的静态守卫 + 口径不变量测试（同既有做法）。

⚠️ **规模口径不变量（D8 修复的锁）**：规则侧按 `p0` 规模，持有端**必须也是 `p0` 规模**
（spec §4「每 1 元持仓」）。脚本原实现里 `_forward_return` 返回的是**原始价格收益**
（= 100% 持仓）⇒ 差值被 `1/p0` 倍放大（实测高估 2~8 倍）。
`test_fixed_window_matches_full120_scale` 锁住「同窗口同口径必须相等」这一不变量。
"""
import ast
import importlib.util
import os

import pandas as pd
import pytest

from fg_system import config


def _src():
    p = os.path.join(config.ROOT, "scripts", "analyze_shoutu_greed.py")
    return open(p, encoding="utf-8").read()


def _load_script():
    """把 `scripts/analyze_shoutu_greed.py` 当模块加载（路径走 `config.ROOT`）。

    ⚠️ **每次新建模块对象**：脚本在导入期只做 `sys.path` 注入与常量定义，
    没有副作用；但不复用 `sys.modules` 缓存，避免与其他用例互相影响。
    """
    p = os.path.join(config.ROOT, "scripts", "analyze_shoutu_greed.py")
    spec = importlib.util.spec_from_file_location("_analyze_shoutu_greed_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _real_inputs():
    """真实数据：`shoutu_history.csv` + 实际权重序列（走库层，不重写）。"""
    from fg_system import pipeline
    from fg_system.data import loader

    hist = loader.load_shoutu_history()
    weights = pipeline.risk_weight_series(pipeline.load_wide())
    return hist, weights


def test_fixed_window_matches_full120_scale():
    """**D8 修复的锁**：`days <= 120` 时 `d120 == full120`（同窗口、同 `p0` 规模）。

    为什么必然相等：`d120` 的窗口 = 从事件日起 120 个交易日；`full120` 的 horizon =
    `max(days-1, 120)`，`days <= 120` 时即 120 ⇒ **两者是同一窗口、同一 `p0` 缩放、
    同一 `pct_change().fillna(0)` 约定**（`_pair` 与 `d` 列走的是同一套公式）。

    ⚠️ **修之前该不变量不成立**（实测 TQQQ 2025-05-13：`d120 = 0.7289` vs
    `full120 = 0.3433`）—— 因为持有端用了 100% 规模而规则侧是 `p0` 规模。

    ⚠️ **只在数据够满 120 日窗口时断言**：窗口不足时 `_forward_return` 按约定返回
    **NaN**（`j >= len(prices)`，保持原语义），而 `full120` 的 `_pair` 用
    `stop = min(pos + horizon, len - 1)` **截断到数据末尾** ⇒ 二者在数据尾部
    **按设计不同**（NaN vs 截断值），不属"规模口径"问题。
    """
    mod = _load_script()
    hist, weights = _real_inputs()
    ev = mod.analyze_symbol("TQQQ", hist, weights)
    assert not ev.empty, "TQQQ 必须有 episode（真实数据）"
    sub = ev[(ev["days"] <= 120) & ev["d120"].notna()]
    assert len(sub) >= 10, "至少要有 10 个「数据够满 120 日窗口」的 episode（TQQQ 实测 22 个）"
    for _, row in sub.iterrows():
        assert row["d120"] == pytest.approx(row["full120"], abs=1e-9), (
            "d120 与 full120 必须同规模同窗口：%s %s d120=%.4f full120=%.4f"
            % (row["symbol"], row["start"].date(), row["d120"], row["full120"]))


def test_hold_return_scales_with_p0():
    """`_forward_return` 必须**按 `p0` 缩放**（不是原样返回价格收益）。

    - `p0 = 1.0` ⇒ 等于原始价格收益（`prices.iloc[j]/prices.iloc[i] - 1`）。
    - `p0 = 0.5` ⇒ **严格小于** `p0 = 1.0` 的结果（证明它确实按规模缩放）。

    ⚠️ 修之前 `_forward_return` **没有 `p0` 参数** ⇒ 本用例以 `TypeError` 失败。
    """
    mod = _load_script()
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    px = pd.Series([100.0, 110.0, 121.0, 133.1], index=idx)   # 每日 +10%

    r_full = mod._forward_return(px, idx[0], 2, 1.0)
    assert r_full == pytest.approx(px.iloc[2] / px.iloc[0] - 1.0)   # +21%

    r_half = mod._forward_return(px, idx[0], 2, 0.5)
    assert r_half < r_full, "p0 更小 ⇒ 持有端收益必须更小（按规模缩放）"
    # p0 scaling: prod(1 + 0.5 * r_t) - 1 = 1.05 * 1.05 - 1 = 0.1025
    assert r_half == pytest.approx(1.05 * 1.05 - 1.0)

    # 窗口不足 ⇒ NaN（保持原语义，`r_h == r_h` 的守卫不变）
    r_nan = mod._forward_return(px, idx[0], 99, 0.5)
    assert r_nan != r_nan


def test_mutation_old_forward_return_breaks_invariant():
    """**变异验证（常驻）**：把 `_forward_return` 换回**修之前**的实现 ⇒ 不变量必须破。

    修之前的实现**忽略 `p0`、原样返回价格收益**（= 100% 持仓）。这是"上一条不变量测试
    本身有效"的锁 —— 若上一条哪天变成同义反复（两边都调同一函数而不检查规模），
    本用例会先失败。

    实测（本仓 TQQQ 2025-05-13）：`d120 = +0.7289` vs `full120 = +0.3433`。
    """
    mod = _load_script()

    def old_forward_return(prices, start, days, p0):     # noqa: ARG001
        if start not in prices.index:
            return float("nan")
        i = prices.index.get_loc(start)
        j = i + days
        if j >= len(prices):
            return float("nan")
        return float(prices.iloc[j] / prices.iloc[i] - 1.0)   # 原始价格收益

    mod._forward_return = old_forward_return
    hist, weights = _real_inputs()
    ev = mod.analyze_symbol("TQQQ", hist, weights)
    row = ev[ev["start"].astype(str).str.startswith("2025-05-13")].iloc[0]
    assert row["d120"] == pytest.approx(0.7289, abs=1e-4), "修前 d120 应为原始价格收益"
    assert row["full120"] == pytest.approx(0.3433, abs=1e-4), "full120 不受影响"
    assert row["d120"] != pytest.approx(row["full120"], abs=1e-4), (
        "修之前 `d120 == full120` 不成立（正是本仓库实测到的 bug）")


def test_script_uses_library_functions():
    """计算必须走库层纯函数，不得在脚本里重写。"""
    called = set()
    for node in ast.walk(ast.parse(_src())):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                called.add(f.attr)
            elif isinstance(f, ast.Name):
                called.add(f.id)
    for need in ("greed_episodes", "replay_exit_path"):
        assert need in called, "脚本没有调用 shoutu_analysis.%s" % need


def _hardcoded_symbols(src):
    """返回 `src` 里**以精确相等**出现的标的名（扫描**全部** `ast.Constant` 字符串）。

    ⚠️ **不排除 docstring** —— 早期版本把 docstring 内容从待检常量里剔除
    （`[s for s in lits if s not in docs]`），使"把标的写进 docstring"可**绕过**守卫。
    现在扫描全部字符串常量（含 docstring）。

    ⚠️ 判定是**精确相等**（`s == sym`），**不是**子串匹配 —— 子串匹配会把说明文字里
    的提及（如 "TQQQ/SOXL/UPRO 作旁证"）误判成硬编码（本仓库已有先例，见
    trading-discipline.md §14.5「判据是带引号而不是裸词」那段）。
    """
    lits = [n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return [sym for sym in config.SHOUTU_SYMBOLS if any(s == sym for s in lits)]


def test_script_does_not_hardcode_symbols():
    """标的白名单必须来自 config，不得硬编码（含 docstring，同既有守卫的纪律）。"""
    bad = _hardcoded_symbols(_src())
    assert not bad, "脚本里硬编码了标的 %s（应走 config）" % "/".join(bad)


def test_guard_detects_symbol_hidden_in_docstring():
    """**变异验证（常驻）**：标的**以精确相等出现在 docstring 常量里**也必须被抓到。

    这是"守卫本身有效"的锁 —— 旧版守卫把 docstring 全文从待检常量里剔除，
    故「docstring 本身就是标的」（三引号包裹一个纯标的串）**能绕过**；
    新版扫描全部字符串常量（含 docstring）⇒ 必须判为硬编码。
    """
    src = '"""TQQQ"""\n\nx = 1\n'
    assert _hardcoded_symbols(src), "docstring 里的标的常量必须被判为硬编码"


def test_guard_detects_symbol_hidden_in_nested_docstring():
    """变异验证（嵌套）：函数 docstring **恰好等于**标的，同样必须被抓到。"""
    src = 'def f():\n    """SOXL"""\n    return 1\n'
    assert _hardcoded_symbols(src), "嵌套 docstring 里的标的常量必须被判为硬编码"


def test_guard_does_not_flag_plaintext_mentions():
    """守卫**不**误判说明文字里的裸词提及（精确相等而非子串匹配）。"""
    src = '"""主样本与旁证：TQQQ/SOXL/UPRO 与 YINN/GDXU/CONL。"""\n\nx = 1\n'
    assert _hardcoded_symbols(src) == [], "裸词提及不得被判为硬编码"
