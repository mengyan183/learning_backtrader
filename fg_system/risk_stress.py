# -*- coding: utf-8 -*-
"""B4：尾部风险压力测试（逐标的最坏实测）——把「事后指标」变成「事前预算」。

依据（规划 v2.0 §方向 B「B4」）：

  - [计算层] 风险报告新增**压力测试节** + **情景表对固定输入返回固定值** ✓
  - 情景下限 = **逐标的最坏实测**（MSTX -99.61% / CONL -95.39% / TQQQ -81.75% /
    BTC -83.2%），**不是**一刀切的 -80% ✓
  - [结论层·人工] **强制含「直接归零」情形** ✓ —— 净值归零**无法用价格序列检测**
    ⇒ 必须**单独回答**「13.5% 绝对上限与三层 80/50/30 会不会被击穿」✓

纪律：

  - **纯函数 + 注入输入**（`tmp_path` / 构造小样本即可测）⇒ 不联网、不读 `Data/` ✓。
  - 逐标的最坏实测数字是**已知常量**，**注明来源、不得自编、不得改** ✓。
    来源：`docs/superpowers/specs/2026-09-21-fear-greed-index-v2-design.md` §12 风险 11；
    `docs/trading-discipline.md` 第 4B.4 条 / 第 12 条；
    `fg_system/config.py` 第 12.23 条注释（BTC -83.2%）。
  - 只读复用 `fg_system/config.py` 的 `CORE_CAP` / `MARKET_CORE_RATIO` /
    `CRYPTO_LAYER_CAP` / `CRYPTO_SYMBOLS`（**不**复制其数字、**不**改生产参数）。

⚠️ 口径提示：规划 B4 正文引用的「13.5% 加密核心仓绝对上限」是 **v2.1 口径**
（`CORE_CAP` 45% × 旧 `MARKET_CORE_RATIO["crypto"]` 30% = 13.5%）。生产现已改为
`MARKET_CORE_RATIO = {us_equity: 0.80, crypto: 0.20}`（v2.6）⇒ 现值为 45% × 20%
= **9%**（`docs/trading-discipline.md` 第 12 条）。本模块**按生产 config 派生**
（可用 `zero_out_answer(crypto_core_cap=0.135)` 注入规划口径复核），故结论随
config 演进保持正确 ✓；
无论取 13.5% 还是 9%，「直接归零未击穿预算」的机制结论都不变 ✓。
"""
from fg_system import config

# ---------------------------------------------------------------------------
# 逐标的最坏实测回撤（真实轨）—— **已知常量，不得自编、不得改**。
# 来源：设计文档 §12 风险 11 / trading-discipline.md 第 4B.4 条 / config.py 第 12.23 条。
# 仅登记规划 B4 明确给出的 4 个数（YAGNI：不给未标定标的编造下限）。
# ---------------------------------------------------------------------------
WORST_REALIZED_DRAWDOWN = {
    "MSTX": -0.9961,   # 2x 币股高 Beta（MSTR）——接近净值归零
    "CONL": -0.9539,   # 2x 币股经营 Beta（COIN）
    "TQQQ": -0.8175,   # 3x 纳指（大盘）
    "BTC": -0.8320,    # BTC 现货历史最大回撤（2018-12-16）
}

# 情景名（固定字符串，供报告节与测试共用）。
SCENARIO_WORST = "最坏实测"
SCENARIO_ZERO = "直接归零"

# 「直接归零」冲击 = -100%（净值归零**无法用价格序列检测**，只能单独作为情形回答）。
ZERO_SHOCK = -1.0

# 来源标注（随结论一并输出，避免数字被脱来源引用）。
SOURCE = (
    "docs/superpowers/specs/2026-09-21-fear-greed-index-v2-design.md §12 风险 11；"
    "docs/trading-discipline.md 第 4B.4 条 / 第 12 条；fg_system/config.py 第 12.23 条"
)

# 回撤预算（与 risk_budget.BUDGET / config.py 第 12.7 条一致：-40%）。
DRAWDOWN_BUDGET = 0.40


def scenario_floor(symbol):
    """逐标的最坏实测回撤（负值）；**未标定返回 None**（不猜、不自编）。"""
    return WORST_REALIZED_DRAWDOWN.get(str(symbol or "").upper())


def stress_scenarios(holdings, shocks=None):
    """压力测试情景表：**对固定输入返回固定行**（确定性、纯函数）。

    holdings: {symbol: position}（相对净值，如 0.30 = 30%）
    shocks:   {symbol: shock}（负值）；缺省用逐标的最坏实测。

    每个持仓标的产出：
      - 「最坏实测」行：shock = shocks[sym] 或内置最坏实测（**未标定则无此行**）
      - 「直接归零」行：shock = -1.0（**强制**，每标的必有）
    loss = position × shock（线性，无隐式缩放）。

    返回按 (scenario, symbol) 升序排序的行列表 ⇒ 固定输入 = 固定输出。
    """
    shocks = shocks or {}
    rows = []
    for sym, pos in holdings.items():
        sym_u = str(sym).upper()
        # 最坏实测行（仅在有已知下限或显式注入 shock 时产出 ⇒ 不编造）
        shock = shocks.get(sym, shocks.get(sym_u, scenario_floor(sym_u)))
        if shock is not None:
            rows.append({
                "scenario": SCENARIO_WORST,
                "symbol": sym_u,
                "shock": float(shock),
                "position": float(pos),
                "loss": float(pos) * float(shock),
            })
        # 直接归零行（强制）
        rows.append({
            "scenario": SCENARIO_ZERO,
            "symbol": sym_u,
            "shock": ZERO_SHOCK,
            "position": float(pos),
            "loss": float(pos) * ZERO_SHOCK,
        })
    rows.sort(key=lambda r: (r["scenario"], r["symbol"]))
    return rows


def stress_report(holdings, shocks=None, budget=DRAWDOWN_BUDGET):
    """压力测试节：情景表 + 逐情景组合总损失 + 是否击穿回撤预算。

    返回 dict：
      scenarios       情景表（`stress_scenarios` 输出）
      by_scenario     每情景 {total_loss, breaches_budget, symbols}
      budget          回撤预算（正数，默认 -40%）
      unknown_floors  无已知下限且未注入 shock 的标的（显式登记，不静默）
      source          数字来源标注
    预算可注入（`budget=`），便于按口径复核。
    """
    scenarios = stress_scenarios(holdings, shocks=shocks)
    known = set()
    injected = {str(s).upper() for s in (shocks or {})}
    for sym in holdings:
        sym_u = str(sym).upper()
        if scenario_floor(sym_u) is not None or sym_u in injected or sym in injected:
            known.add(sym_u)
    unknown = sorted({str(s).upper() for s in holdings} - known)

    by_scenario = {}
    for name in (SCENARIO_WORST, SCENARIO_ZERO):
        rows = [r for r in scenarios if r["scenario"] == name]
        total = sum(r["loss"] for r in rows)
        by_scenario[name] = {
            "total_loss": total,
            "breaches_budget": bool(-total > budget),
            "symbols": [r["symbol"] for r in rows],
        }

    return {
        "scenarios": scenarios,
        "by_scenario": by_scenario,
        "budget": float(budget),
        "unknown_floors": unknown,
        "source": SOURCE,
    }


def zero_out_answer(crypto_core_cap=None, market_core_ratio=None, layer_caps=None):
    """**单独回答「直接归零」**：绝对上限与三层 80/50/30 会不会被击穿。

    为什么必须单独回答：净值归零**无法用价格序列检测**（设计文档 §12 风险 11）
    ⇒ 无法用回测/情景表里的价格下行捕捉 ⇒ 只能作为**先验情形**单独回答 ✓。

    `crypto_core_cap` 可注入（如规划口径 13.5%）；缺省时由生产 config 派生：
    `CORE_CAP × market_core_ratio["crypto"]`。`layer_caps` 亦可注入。
    各层预算 = 加密核心仓绝对上限 × 层上限（三层**互斥预算**，第 4B.1.1 条）。

    机制结论：三层上限**就是**该层的最大损失预算 ⇒
      - 单标的归零损失 ≤ 该层预算 ≤ 加密核心仓绝对上限；
      - 整个加密 sleeve 归零损失 = 加密核心仓绝对上限 ≤ 回撤预算 40%。
    ⇒ **不被击穿**（`abs_cap_breached=False` / `layer_caps_breached=False`）。
    """
    if crypto_core_cap is None:
        ratio = (config.MARKET_CORE_RATIO if market_core_ratio is None
                 else market_core_ratio)
        crypto_core_cap = config.CORE_CAP * ratio["crypto"]
    caps = config.CRYPTO_LAYER_CAP if layer_caps is None else layer_caps

    crypto_core = crypto_core_cap
    layer_budget = {layer: crypto_core * cap for layer, cap in caps.items()}
    # 单标的归零：层内等权（第 4B.6 条）⇒ 单标的绝对位置 = 层预算 / 层内标的数
    single_name_max = {}
    for layer, budget in layer_budget.items():
        members = config.CRYPTO_SYMBOLS.get(layer, [])
        n = len(members) if members else 1
        single_name_max[layer] = budget / n

    max_loss_all_crypto = crypto_core
    layer_breached = any(b > DRAWDOWN_BUDGET for b in layer_budget.values())
    return {
        "crypto_core_cap": crypto_core,
        "layer_budget": layer_budget,
        "single_name_max_loss": single_name_max,
        # 整个加密 sleeve 直接归零 = 绝对上限（最大可能损失）
        "max_loss_all_crypto": max_loss_all_crypto,
        "drawdown_budget": DRAWDOWN_BUDGET,
        "abs_cap_breached": bool(max_loss_all_crypto > DRAWDOWN_BUDGET),
        "layer_caps_breached": bool(layer_breached),
        # 归零无法用价格序列检测 ⇒ 只能靠上限约束（第 4B.4 条）
        "detectable_by_price_series": False,
        "statement": (
            "「直接归零」无法用价格序列检测（净值归零=价格序列无定义，"
            "见设计文档 §12 风险 11）⇒ 只能靠**上限约束**：三层 80/50/30 是"
            "**互斥预算**（第 4B.1.1 条），单标的归零损失 ≤ 该层预算；"
            "整个加密 sleeve 归零的最大损失 = 加密核心仓绝对上限 %.4g "
            "≤ 回撤预算 %.2g ⇒ **绝对上限与三层均不被击穿**。"
            % (max_loss_all_crypto, DRAWDOWN_BUDGET)
        ),
        "source": SOURCE,
    }
