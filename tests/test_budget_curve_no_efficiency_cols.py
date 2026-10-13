# -*- coding: utf-8 -*-
"""B1 守卫测试：回撤预算曲线**禁止**含「效率」列。

依据（规划 v2.0 §方向 B / 团队评审 C7 / `config.py` 第 12.7 条）：
  「**不按矩阵挑 Calmar / 年化最高的格子**——那是对历史路径的拟合。」
  ⇒ 曲线**只回答「余量还剩多少」**（回撤 / CVaR 尾部指标），
    **不回答「更好的组合是什么」** ⇒ 结构性禁止输出
    Calmar / 年化 / Sortino（以及 Sharpe / 年化波动 等同族效率指标）列。

本测试是**结构性防护**（评审 C20：本仓库有过「只写在 docstring 里、
代码层无约束」的先例 ⇒ 必须机械化断言）：
  1. 曲线产物**每个网格**只含 {回撤, CVaR} 类字段，不含效率列；
  2. 产物整体带 `OOS_WARNING`；
  3. 产物显式声明「只答余量、不答更优组合」且「禁止喂 evolve_propose」。
"""
import json
import os

import pytest

from fg_system import risk_budget

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURVE_PATH = os.path.join(REPO, "evolution", "drawdown_budget_curve.json")

# 「效率」列名特征（禁止出现）：年化收益 / 风险调整后收益 / 波动率。
FORBIDDEN_SUBSTRINGS = (
    "calmar", "annual_return", "sortino", "sharpe", "annual_vol",
    "return", "cagr",
)


def _iter_keys(obj, prefix=""):
    """递归产出 (key_path, key) 对（dict 的每个键）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield "%s%s" % (prefix, k), k
            yield from _iter_keys(v, "%s%s." % (prefix, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_keys(v, "%s[%d]." % (prefix, i))


def test_curve_grid_has_no_efficiency_keys():
    """每个网格点不得含效率列（只留回撤 / CVaR）。"""
    curve = risk_budget.build_curve()
    assert curve["grid"], "曲线网格不得为空"
    for point in curve["grid"]:
        keys = {k.lower() for k in point.keys()}
        for bad in FORBIDDEN_SUBSTRINGS:
            offenders = [k for k in keys if bad in k]
            assert not offenders, (
                "网格点含禁止的效率列 %r（key=%r）" % (offenders, point))
        # 必须含回撤与 CVaR 尾部指标
        assert "drawdown" in keys
        assert "cvar95" in keys and "cvar99" in keys


def test_curve_has_no_efficiency_keys_anywhere():
    """递归扫描全产物，任何层级都不得出现效率列键名。"""
    curve = risk_budget.build_curve()
    offenders = []
    for path, key in _iter_keys(curve):
        kl = key.lower()
        if any(bad in kl for bad in FORBIDDEN_SUBSTRINGS):
            # meta/声明字段里允许出现「不输出 Calmar/年化」这类**文字说明**，
            # 但它们都是字符串值，不是数值列 ⇒ 只拦截**数值列键**。
            val = curve
            for part in path.rstrip(".").split("."):
                if not part:
                    continue
                if "[" in part:
                    name, idx = part[:-1].split("[")
                    val = val[name][int(idx)]
                else:
                    val = val[part]
            if isinstance(val, (int, float)):
                offenders.append("%s = %r" % (path, val))
    assert not offenders, "产物含效率数值列：\n" + "\n".join(offenders)


def test_curve_has_oos_warning():
    """产物必须带 OOS_WARNING（规划 B1 验收）。"""
    curve = risk_budget.build_curve()
    assert curve.get("OOS_WARNING"), "产物缺少 OOS_WARNING 字段"


def test_curve_declares_scope_and_no_evolve_propose():
    """产物必须声明「只答余量、不答更优组合」且「禁止喂 evolve_propose」。"""
    curve = risk_budget.build_curve()
    scope = json.dumps(curve.get("scope", {}), ensure_ascii=False)
    assert "余量" in scope
    assert "更优" in scope or "更好" in scope
    assert curve.get("forbidden_input_to")
    assert "evolve_propose" in curve["forbidden_input_to"]


def test_curve_json_artifact_matches_builder():
    """落盘产物必须与构建器一致（防止手工篡改产物绕过守卫）。"""
    if not os.path.exists(CURVE_PATH):
        pytest.skip("产物未生成（先跑 scripts/build_budget_curve.py）")
    with open(CURVE_PATH, encoding="utf-8") as fh:
        on_disk = json.load(fh)
    built = json.loads(json.dumps(risk_budget.build_curve(), default=str))
    assert on_disk["grid"] == built["grid"]
    assert on_disk["OOS_WARNING"] == built["OOS_WARNING"]
