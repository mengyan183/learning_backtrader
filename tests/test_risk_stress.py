# -*- coding: utf-8 -*-
"""B4 尾部风险压力测试（逐标的最坏实测）测试。

**不读真实 Data/**：全部为纯函数 + 注入输入（构造小样本 holdings/shocks）。

验收（规划 v2.0 §方向 B「B4」）：
- [计算层] 风险报告新增压力测试节 + 情景表对固定输入返回固定值 ✓
- 情景下限 = 逐标的最坏实测（MSTX -99.61% / CONL -95.39% / TQQQ -81.75% /
  BTC -83.2%），**不是** -80% ✓
- [结论层·人工] 强制含「直接归零」情形 ✓ —— 净值归零**无法用价格序列检测**
  ⇒ 必须单独回答「13.5% 绝对上限与三层 80/50/30 会不会被击穿」✓

数字来源（**不得自编、不得改**）：
- `docs/superpowers/specs/2026-09-21-fear-greed-index-v2-design.md` §12 风险 11
- `docs/trading-discipline.md` 第 4B.4 条 / 第 12 条、`fg_system/config.py` 第 12.23 条注释
"""
import pytest

from fg_system import config
from fg_system import risk_stress


# ---------------------------------------------------------------- 常量与来源
def test_worst_realized_floors_match_known_constants():
    """逐标的最坏实测必须与已知常量**逐位相等**（规划给定的 4 个数）。"""
    assert risk_stress.WORST_REALIZED_DRAWDOWN["MSTX"] == pytest.approx(-0.9961)
    assert risk_stress.WORST_REALIZED_DRAWDOWN["CONL"] == pytest.approx(-0.9539)
    assert risk_stress.WORST_REALIZED_DRAWDOWN["TQQQ"] == pytest.approx(-0.8175)
    assert risk_stress.WORST_REALIZED_DRAWDOWN["BTC"] == pytest.approx(-0.8320)


def test_scenario_floor_is_worst_realized_not_minus_80():
    """情景下限取**逐标的最坏实测**，而不是一刀切的 -80%（规划明文）。"""
    assert risk_stress.scenario_floor("TQQQ") == pytest.approx(-0.8175)
    assert risk_stress.scenario_floor("TQQQ") != pytest.approx(-0.80)
    # 大小写不敏感（符号口径统一）
    assert risk_stress.scenario_floor("mstx") == pytest.approx(-0.9961)


def test_scenario_floor_unknown_symbol_returns_none_not_fabricated():
    """未标定的标的返回 None —— **不猜、不自编**下限。"""
    assert risk_stress.scenario_floor("SOXL") is None
    assert risk_stress.scenario_floor("NO_SUCH") is None


# ---------------------------------------------------------------- 情景表：固定输入→固定值
def test_scenario_table_fixed_input_returns_fixed_rows():
    """情景表对**固定输入**返回**固定值**（可测、确定性）。"""
    holdings = {"TQQQ": 0.30, "MSTX": 0.05, "CONL": 0.03}
    rows_a = risk_stress.stress_scenarios(holdings)
    rows_b = risk_stress.stress_scenarios(holdings)
    assert rows_a == rows_b
    # 确定性排序：先按情景名，再按标的名
    keys = [(r["scenario"], r["symbol"]) for r in rows_a]
    assert keys == sorted(keys)


def test_scenario_row_loss_is_position_times_shock():
    """逐行：loss = position × shock（线性、无隐式缩放）。"""
    holdings = {"TQQQ": 0.30}
    rows = risk_stress.stress_scenarios(holdings)
    worst = [r for r in rows if r["scenario"] == risk_stress.SCENARIO_WORST][0]
    assert worst["shock"] == pytest.approx(-0.8175)
    assert worst["position"] == pytest.approx(0.30)
    assert worst["loss"] == pytest.approx(0.30 * -0.8175)


def test_scenario_table_includes_zero_out_for_every_held_symbol():
    """**强制含「直接归零」情形**：每个持仓标的都必须有 shock == -1.0 的行。"""
    holdings = {"TQQQ": 0.30, "MSTX": 0.05, "CONL": 0.03}
    rows = risk_stress.stress_scenarios(holdings)
    zero_rows = [r for r in rows if r["scenario"] == risk_stress.SCENARIO_ZERO]
    assert {r["symbol"] for r in zero_rows} == set(holdings)
    assert all(r["shock"] == pytest.approx(-1.0) for r in zero_rows)
    # 归零 = 该标的位置全损
    for r in zero_rows:
        assert r["loss"] == pytest.approx(-r["position"])


def test_injected_shocks_override_floors():
    """shocks 注入优先于内置常量（纯函数、输入可注入）。"""
    holdings = {"TQQQ": 0.30}
    rows = risk_stress.stress_scenarios(holdings, shocks={"TQQQ": -0.5})
    worst = [r for r in rows if r["scenario"] == risk_stress.SCENARIO_WORST][0]
    assert worst["shock"] == pytest.approx(-0.5)


def test_unknown_symbol_marked_not_silently_dropped():
    """无已知下限且未注入 shock 的持仓：仍出现在「直接归零」行，但
    「最坏实测」行缺失（不确定就不编），并在 unknown 里显式登记。"""
    holdings = {"SOXL": 0.10}
    rep = risk_stress.stress_report(holdings)
    assert rep["unknown_floors"] == ["SOXL"]
    worst_syms = {r["symbol"] for r in rep["scenarios"]
                  if r["scenario"] == risk_stress.SCENARIO_WORST}
    assert worst_syms == set()          # 不编造 SOXL 的下限
    zero_syms = {r["symbol"] for r in rep["scenarios"]
                 if r["scenario"] == risk_stress.SCENARIO_ZERO}
    assert zero_syms == {"SOXL"}        # 归零行仍在


# ---------------------------------------------------------------- 压力测试节
def test_stress_report_has_section_with_totals_and_budget_flag():
    """压力测试节：逐情景组合损失 + 是否击穿回撤预算（预算可注入）。"""
    holdings = {"TQQQ": 0.30, "MSTX": 0.05}
    rep = risk_stress.stress_report(holdings, budget=0.40)
    assert set(rep) >= {"scenarios", "by_scenario", "budget", "unknown_floors"}
    for name in (risk_stress.SCENARIO_WORST, risk_stress.SCENARIO_ZERO):
        blk = rep["by_scenario"][name]
        assert set(blk) >= {"total_loss", "breaches_budget"}
    # 归零情景总损失 = -（两标的位置和）
    zero = rep["by_scenario"][risk_stress.SCENARIO_ZERO]
    assert zero["total_loss"] == pytest.approx(-(0.30 + 0.05))
    # 0.35 < 0.40 预算 ⇒ 未击穿
    assert zero["breaches_budget"] is False


def test_stress_report_flags_budget_breach_when_loss_exceeds_budget():
    """损失超过预算 ⇒ breaches_budget 置 True（不得静默）。"""
    rep = risk_stress.stress_report({"TQQQ": 0.50}, budget=0.40)
    assert rep["by_scenario"][risk_stress.SCENARIO_ZERO]["breaches_budget"] is True


# ---------------------------------------------------------------- 「直接归零」单独回答
def test_zero_out_answer_derives_caps_from_config():
    """直接归零答案由 config 派生（可注入 core_cap/ratio/layer_caps）。"""
    ans = risk_stress.zero_out_answer()
    core = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert ans["crypto_core_cap"] == pytest.approx(core)
    for layer, cap in config.CRYPTO_LAYER_CAP.items():
        assert ans["layer_budget"][layer] == pytest.approx(core * cap)
    # 三层预算互斥，总额 == 加密核心仓绝对上限
    assert sum(ans["layer_budget"].values()) == pytest.approx(
        core * sum(config.CRYPTO_LAYER_CAP.values()))


def test_zero_out_answer_reports_not_breached():
    """「直接归零」不得击穿 13.5%/当前绝对上限，也不得击穿三层 80/50/30。

    机制：三层上限是**预算**；单标的归零损失 ≤ 该层预算 ≤ 加密核心仓绝对上限；
    即整个加密 sleeve 归零的最大损失 = 加密核心仓绝对上限。结论 = 未被击穿。
    """
    ans = risk_stress.zero_out_answer()
    assert ans["abs_cap_breached"] is False
    assert ans["layer_caps_breached"] is False
    # 整个加密 sleeve 归零 = 加密核心仓绝对上限（≤ 回撤预算）
    assert ans["max_loss_all_crypto"] == pytest.approx(ans["crypto_core_cap"])
    assert ans["max_loss_all_crypto"] <= ans["drawdown_budget"]


def test_zero_out_single_name_loss_bounded_by_layer_cap():
    """单标的归零：损失 = 该标的绝对位置 ≤ 所属层预算（≤ core×层上限）。"""
    ans = risk_stress.zero_out_answer()
    for layer, budget in ans["layer_budget"].items():
        n = len(config.CRYPTO_SYMBOLS[layer])
        per_name = ans["single_name_max_loss"][layer]
        assert per_name == pytest.approx(budget / n)
        assert per_name <= budget


def test_zero_out_answer_states_price_series_cannot_detect_zero():
    """归零无法用价格序列检测 ⇒ 答案必须显式声明（来源：§12 风险 11）。"""
    ans = risk_stress.zero_out_answer()
    assert ans["detectable_by_price_series"] is False
    assert ans["source"]        # 非空来源标注
    assert "归零" in ans["statement"]


def test_zero_out_answer_injected_crypto_core_cap_is_used():
    """注入 crypto_core_cap（如规划口径 13.5%）时，答案按注入值缩放。"""
    ans = risk_stress.zero_out_answer(crypto_core_cap=0.135)
    assert ans["crypto_core_cap"] == pytest.approx(0.135)
    assert ans["layer_budget"]["btc_beta"] == pytest.approx(0.135 * 0.80)
    assert ans["layer_budget"]["stock_high_beta"] == pytest.approx(0.135 * 0.50)
    assert ans["layer_budget"]["stock_ops_beta"] == pytest.approx(0.135 * 0.30)
    assert ans["abs_cap_breached"] is False


# ---------------------------------------------------------------- 报告节（只加不改）
def test_report_has_stress_section(tmp_path):
    """B4：[计算层] 风险报告新增**压力测试节** + 强制含「直接归零」。"""
    import pandas as pd
    from fg_system.dashboard import report

    idx = pd.bdate_range("2024-01-01", periods=30)
    us = pd.DataFrame({
        "fg_index": range(30), "zone": [0] * 30, "target_position": [0.4] * 30,
        "core_position": [0.4] * 30, "ammo_position": [0.0] * 30,
        "drawdown": [0.0] * 30, "circuit_breaker": [False] * 30,
        "note": [""] * 30, "trend_blocked": [False] * 30}, index=idx)
    crypto = pd.DataFrame({
        "crypto_fg_index": range(30), "zone": [0] * 30,
        "target_position": [0.1] * 30, "core_position": [0.1] * 30,
        "layer_btc_beta": [0.1] * 30, "layer_stock_high_beta": [0.07] * 30,
        "layer_stock_ops_beta": [0.05] * 30, "greed_tier": [0] * 30,
        "trend_blocked": [False] * 30, "drawdown": [0.0] * 30,
        "note": [""] * 30}, index=idx)
    p = str(tmp_path / "dash.html")
    report.build_v2(us, crypto, path=p, stress_holdings={"MSTX": 0.05, "TQQQ": 0.30})
    html = open(p, encoding="utf-8").read()
    assert "压力测试" in html
    assert risk_stress.SCENARIO_ZERO in html      # 强制含「直接归零」
    assert "直接归零" in html
    assert "MSTX" in html and "TQQQ" in html
    # 逐标的最坏实测值出现在表里（-99.61% / -81.75%）
    assert "99.61" in html
    assert "81.75" in html
    # 「直接归零」单独回答：绝对上限 + 三层
    assert "绝对上限" in html
    assert "币股高 Beta" in html
