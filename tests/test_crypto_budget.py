# -*- coding: utf-8 -*-
"""B5：加密侧预算复核（**独立预算声明** + **三层上限的机械断言**）。

依据（规划 v2.0 §方向 B「B5」，`docs/2026-10-12-贪恐系统迭代规划v2.0.md`）：

  - 产出**独立的加密预算声明**：加密 sleeve 的预算 **≠** 大盘 sleeve 的预算，
    但**共用总回撤预算 40%**（先验 -40%，见 `risk_budget.BUDGET` /
    `config.py` 第 12.7 条）。
  - **禁止对冲**：**不得**用大盘降敞口抵加密敞口（第 4.1.1 条「不得左口袋挪
    右口袋」）⇒ 两个 sleeve 各自独立预算。
  - **[计算层] 不重复出归零表**（与 B4 重叠）：归零数值证据**引用 B4**
    （`fg_system.risk_stress`），B5 只出「**独立预算声明 + 算子约束 + 三层上限
    的机械断言**」。
  - **三层上限的机械断言**：加密核心仓绝对上限 = `CORE_CAP ×
    MARKET_CORE_RATIO["crypto"]`；三层 = 该值 × `CRYPTO_LAYER_CAP`
    （**80/50/30%**）；且三层是**互斥预算（不叠加）**（第 4B.1.1 条）。

🔴 口径（已核定 2026-10-13）：

  - `CORE_CAP` = 0.45、`MARKET_CORE_RATIO` = `{us_equity: 0.80, crypto: 0.20}`
    ⇒ 加密核心仓绝对上限 = **0.20 × 0.45 = 9%**（**不是** 13.5% —— 那是
    v2.1 旧口径）。
  - 三层：BTC 纯 Beta = 9% × 80% = **7.2%** / 币股高 Beta = **4.5%** /
    币股经营 Beta = **2.7%**。

⚠️ **一律从 `config` 派生**（**不硬编码** 9% / 7.2% 等）⇒ 未来改分割比例时
自动跟随 ✓。本测试因此**同时**断言「具体值 == 9%/7.2%/4.5%/2.7%」与
「值 == 由 config 表达式派生」，任意一个被改坏都会报红。
"""
import pytest

from fg_system import config
from fg_system import crypto_budget
from fg_system import risk_stress

# 共享总回撤预算（正数；先验 -40%，K 与 risk_budget.BUDGET 一致）。
SHARED_DRAWDOWN_BUDGET = 0.40


# ---------------------------------------------------------------- 独立预算声明
def test_declares_two_independent_sleeves_sharing_one_budget():
    """加密 sleeve 预算 ≠ 大盘 sleeve 预算，但**共用**总回撤预算 40%。"""
    decl = crypto_budget.declare()

    sleeves = decl["sleeves"]
    assert set(sleeves) == {"us_equity", "crypto"}

    us = sleeves["us_equity"]["budget"]
    cr = sleeves["crypto"]["budget"]
    # 两个 sleeve 各自独立预算，且**不相等**（加密≠大盘）
    assert us == pytest.approx(config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"])
    assert cr == pytest.approx(config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"])
    assert us != pytest.approx(cr)

    # 但共用同一个总回撤预算 40%
    assert decl["shared_drawdown_budget"] == pytest.approx(SHARED_DRAWDOWN_BUDGET)
    assert decl["shared_drawdown_budget"] == pytest.approx(risk_stress.DRAWDOWN_BUDGET)


def test_sleeve_declaration_is_bound_to_its_market_not_swappable():
    """每个 sleeve 的预算必须绑定其 market 的 `MARKET_CORE_RATIO`（不可互换）。"""
    decl = crypto_budget.declare()
    for market in ("us_equity", "crypto"):
        assert decl["sleeves"][market]["market"] == market
        assert decl["sleeves"][market]["ratio"] == pytest.approx(
            config.MARKET_CORE_RATIO[market])


def test_declaration_forbids_cross_sleeve_hedging():
    """**禁止对冲**：显式声明不得用大盘降敞口抵加密敞口（第 4.1.1 条）。"""
    decl = crypto_budget.declare()
    constraints = decl["constraints"]
    assert constraints["hedge_between_sleeves_allowed"] is False
    assert constraints["cross_sleeve_offset_allowed"] is False
    # 声明文字必须点明「不得左口袋挪右口袋」
    joined = " ".join(str(v) for v in constraints.values())
    assert "不得" in joined
    assert "挪" in joined or "对冲" in joined


def test_declaration_references_b4_for_zero_out_not_recomputed():
    """B5 **不重复出归零表**：归零数值证据**引用 B4**（不自己再算一遍）。"""
    decl = crypto_budget.declare()
    assert decl["zero_out_evidence_source"] == "risk_stress (B4)"
    # 引用上游模块，而不是把数字抄进来
    assert "risk_stress" in decl["zero_out_evidence_source"]


# ---------------------------------------------------------------- 三层上限机械断言
def test_crypto_core_absolute_cap_derived_from_config():
    """加密核心仓绝对上限 = `CORE_CAP × MARKET_CORE_RATIO["crypto"]`（从 config 派生）。"""
    decl = crypto_budget.declare()
    expected = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert decl["crypto_core_cap"] == pytest.approx(expected)


def test_crypto_core_absolute_cap_is_nine_percent_not_thirteen_five():
    """核定口径：加密核心仓绝对上限 = **9%**（**不是** v2.1 旧口径 13.5%）。"""
    decl = crypto_budget.declare()
    assert decl["crypto_core_cap"] == pytest.approx(0.09)
    assert decl["crypto_core_cap"] != pytest.approx(0.135)


def test_three_layer_caps_are_core_cap_times_layer_ratio():
    """三层上限 = 加密核心仓绝对上限 × `CRYPTO_LAYER_CAP`（80/50/30%）。"""
    decl = crypto_budget.declare()
    core = decl["crypto_core_cap"]
    for layer, ratio in config.CRYPTO_LAYER_CAP.items():
        assert decl["layer_caps"][layer] == pytest.approx(core * ratio)


@pytest.mark.parametrize("layer,expected", [
    ("btc_beta", 0.072),          # 9% × 80% = 7.2%
    ("stock_high_beta", 0.045),   # 9% × 50% = 4.5%
    ("stock_ops_beta", 0.027),    # 9% × 30% = 2.7%
])
def test_three_layer_caps_exact_values(layer, expected):
    """三层上限具体值 = 7.2% / 4.5% / 2.7%（与从 config 派生一致）。"""
    decl = crypto_budget.declare()
    assert decl["layer_caps"][layer] == pytest.approx(expected)
    assert decl["layer_caps"][layer] == pytest.approx(
        config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
        * config.CRYPTO_LAYER_CAP[layer])


def test_layer_caps_are_mutually_exclusive_not_additive():
    """三层是**互斥预算（不叠加）**：层上限是「该层最多占核心仓多少」，
    **不是**各层权重之和；断言每层 ≤ 核心仓绝对上限，且层上限之和 **≠** 核心仓
    绝对上限（若被误当权重叠加会露馅）。"""
    decl = crypto_budget.declare()
    core = decl["crypto_core_cap"]

    assert decl["layers_mutually_exclusive"] is True
    for layer, cap in decl["layer_caps"].items():
        assert cap <= core + 1e-12, "层上限不得超过核心仓绝对上限"

    # 互斥预算：三层上限之和 = core × sum(ratio) = core × 1.6，而**不是** core
    assert sum(decl["layer_caps"].values()) == pytest.approx(
        core * sum(config.CRYPTO_LAYER_CAP.values()))
    assert sum(decl["layer_caps"].values()) != pytest.approx(core)


def test_layer_caps_never_exceed_shared_budget_individually_or_in_total():
    """单层或三层之和都**不得**击穿共享总回撤预算 40%（先验约束）。"""
    decl = crypto_budget.declare()
    budget = decl["shared_drawdown_budget"]
    for layer, cap in decl["layer_caps"].items():
        assert cap <= budget
    assert sum(decl["layer_caps"].values()) <= budget


# ---------------------------------------------------------------- 派生自证（反硬编码）
def test_layer_caps_follow_config_change():
    """若改分割比例/层上限，三层值必须**跟随变化**（证明从 config 派生、非硬编码）。"""
    decl = crypto_budget.declare(
        core_cap=0.45, market_core_ratio={"us_equity": 0.80, "crypto": 0.20},
        layer_ratio={"btc_beta": 0.80, "stock_high_beta": 0.50,
                     "stock_ops_beta": 0.30})
    # 注入 v2.1 旧口径 crypto=0.30 ⇒ 绝对上限 13.5%，三层随之
    old = crypto_budget.declare(
        core_cap=0.45, market_core_ratio={"us_equity": 0.70, "crypto": 0.30},
        layer_ratio={"btc_beta": 0.80, "stock_high_beta": 0.50,
                     "stock_ops_beta": 0.30})
    assert decl["crypto_core_cap"] == pytest.approx(0.09)
    assert old["crypto_core_cap"] == pytest.approx(0.135)
    assert old["layer_caps"]["btc_beta"] == pytest.approx(0.108)
    assert old["layer_caps"]["stock_high_beta"] == pytest.approx(0.0675)
    assert old["layer_caps"]["stock_ops_beta"] == pytest.approx(0.0405)


# ---------------------------------------------------------------- 结构性防护
def test_scope_declares_answers_and_does_not_answer():
    """B5 只回答「加密独立预算 + 三层上限是否被击穿」，**不**回答归零表。"""
    decl = crypto_budget.declare()
    scope = decl["scope"]
    assert "预算" in scope["answers"]
    assert "归零" in scope["does_not_answer"]
