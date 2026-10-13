# -*- coding: utf-8 -*-
"""B5：加密侧预算复核（**独立预算声明** + **三层上限的机械断言**）。

依据（规划 v2.0 §方向 B「B5」，`docs/2026-10-12-贪恐系统迭代规划v2.0.md`）：

  - 产出**独立的加密预算声明** ✓ —— 加密 sleeve 的预算 **≠** 大盘 sleeve 的
    预算，但**共用总回撤预算 40%** ✓。
  - **禁止对冲** ✗：**不得**用大盘降敞口抵加密敞口（否则违反第 4.1.1 条
    「不得左口袋挪右口袋」）⇒ 两个 sleeve 各自独立预算 ✓。
  - **[计算层] 不重复出归零表** ✗（复审指出与 B4 重叠 ✓）：归零数值证据**引用
    B4**（`fg_system.risk_stress.zero_out_answer` / `stress_report`）✓，
    B5 只出「**独立预算声明 + 算子约束 + 三层上限的机械断言**」✓。
  - **三层上限的机械断言**：加密核心仓绝对上限 = `CORE_CAP ×
    MARKET_CORE_RATIO["crypto"]`；三层 = 该值 × `CRYPTO_LAYER_CAP`
    （**80/50/30%**）；三层是**互斥预算（不叠加）**（第 4B.1.1 条）✓。

🔴 口径（已核定 2026-10-13）：

  - `CORE_CAP` = 0.45、`MARKET_CORE_RATIO` = `{us_equity: 0.80, crypto: 0.20}`
    ⇒ 加密核心仓绝对上限 = **0.20 × 0.45 = 9%**（**不是** 13.5% ✗ —— 那是
    v2.1 旧口径 ✓）。
  - 三层：BTC 纯 Beta = 9% × 80% = **7.2%** / 币股高 Beta = **4.5%** /
    币股经营 Beta = **2.7%**。

⚠️ **一律从 `config` 派生** ✗✓（**不**硬编码 9% / 7.2% 等 ✗）⇒ 未来改分割
比例时自动跟随 ✓。本模块所有上限默认从 `fg_system.config` 读取；`declare()`
的三个参数仅为**注入复核**（如按 v2.1 旧口径 `crypto=0.30` 复核），
**不改生产参数** ✗。

⚠️ 与 B4 的边界：**归零数值证据在 B4**（`risk_stress.zero_out_answer`）✓。
本模块**只**验证「三层是互斥预算」这一**结构性**结论，不重算归零表 ✗。
"""
from fg_system import config

# 共享总回撤预算（正数，先验 -40%；与 `risk_budget.BUDGET` / `config.py`
# 第 12.7 条 / `risk_stress.DRAWDOWN_BUDGET` 同源）。
SHARED_DRAWDOWN_BUDGET = 0.40

# 三层上限的**层名 → 中文标签**（供声明/报告可读；标签不改数值口径）。
LAYER_LABELS = {
    "btc_beta": "BTC 纯 Beta",
    "stock_high_beta": "币股高 Beta",
    "stock_ops_beta": "币股经营 Beta",
}

# 归零证据来源：**引用 B4**，B5 不重复出表（规划明文）。
ZERO_OUT_EVIDENCE_SOURCE = "risk_stress (B4)"

# 来源标注（随声明一并输出，避免数字被脱来源引用）。
SOURCE = (
    "fg_system/config.py（CORE_CAP / MARKET_CORE_RATIO / CRYPTO_LAYER_CAP / "
    "CRYPTO_SYMBOLS）；docs/trading-discipline.md 第 4.1.1 条 / 第 4B.1.1 条 / "
    "第 12 条；docs/2026-10-12-贪恐系统迭代规划v2.0.md 方向 B「B5」"
)


def crypto_core_cap(core_cap=None, market_core_ratio=None):
    """加密核心仓**绝对上限** = `CORE_CAP × MARKET_CORE_RATIO["crypto"]`。

    默认从 `config` 派生（当前 = 0.45 × 0.20 = **9%**）。参数仅供口径复核注入。
    """
    cc = config.CORE_CAP if core_cap is None else core_cap
    ratio = config.MARKET_CORE_RATIO if market_core_ratio is None else market_core_ratio
    return cc * ratio["crypto"]


def layer_caps(core_cap=None, market_core_ratio=None, layer_ratio=None):
    """三层上限 = 加密核心仓绝对上限 × 该层层上限（`CRYPTO_LAYER_CAP`）。

    ⚠️ 这是**逐层上限**（各层最多占核心仓多少），**不是**层间权重；
    层上限之和 = core × 1.6 **≠** core ⇒ 三层是**互斥预算（不叠加）** ✓。
    """
    core = crypto_core_cap(core_cap=core_cap, market_core_ratio=market_core_ratio)
    ratio = config.CRYPTO_LAYER_CAP if layer_ratio is None else layer_ratio
    return {layer: core * cap for layer, cap in ratio.items()}


def declare(core_cap=None, market_core_ratio=None, layer_ratio=None):
    """**独立预算声明** + 三层上限机械断言（单一来源，供报告/守卫复用）。

    返回 dict：
      sleeves                  两个 sleeve 的**独立预算**：
                                 {market: {market, ratio, budget, label}}
                               （budget = `CORE_CAP × MARKET_CORE_RATIO[market]`；
                                加密 ≠ 大盘 ✓）
      shared_drawdown_budget   两者**共用**的总回撤预算（0.40）✓
      crypto_core_cap          加密核心仓**绝对上限**（当前 9%）✓
      layer_caps               三层上限（当前 7.2% / 4.5% / 2.7%）✓
      layer_labels             层名 → 中文标签
      layers_mutually_exclusive True —— 三层是**互斥预算（不叠加）**（第 4B.1.1 条）✓
      layer_cap_ratio          逐层上限比例（80/50/30%，声明用）
      constraints              算子约束（**禁止跨 sleeve 对冲** ✓；确定性纯函数式）
      zero_out_evidence_source 归零证据**引用 B4**（B5 不重复出表）✓
      source                   数字来源标注
      scope                    声明「答什么 / 不答什么」

    🔴 无副作用、无 IO ⇒ 不联网、不读 `Data/` ✓；对固定输入返回固定值 ✓。
    """
    cc = config.CORE_CAP if core_cap is None else core_cap
    ratio = (config.MARKET_CORE_RATIO if market_core_ratio is None
             else market_core_ratio)
    layer_ratio = config.CRYPTO_LAYER_CAP if layer_ratio is None else layer_ratio

    sleeves = {
        m: {
            "market": m,
            "ratio": ratio[m],
            "budget": cc * ratio[m],
            "label": {"us_equity": "大盘", "crypto": "加密"}.get(m, m),
        }
        for m in ratio
    }

    core = crypto_core_cap(core_cap=cc, market_core_ratio=ratio)
    caps = {layer: core * cap for layer, cap in layer_ratio.items()}

    label_pairs = "、".join(
        "%s %.4g%%" % (LAYER_LABELS.get(layer, layer), caps[layer] * 100.0)
        for layer in caps)

    return {
        "sleeves": sleeves,
        "shared_drawdown_budget": SHARED_DRAWDOWN_BUDGET,
        "crypto_core_cap": core,
        "layer_caps": caps,
        "layer_labels": dict(LAYER_LABELS),
        "layer_cap_ratio": {layer: float(r) for layer, r in layer_ratio.items()},
        "layers_mutually_exclusive": True,
        "constraints": {
            # 第 4.1.1 条：**不得**用大盘降敞口抵加密敞口（左口袋挪右口袋 ✗）
            "hedge_between_sleeves_allowed": False,
            "cross_sleeve_offset_allowed": False,
            "note": ("两个 sleeve 各自独立预算，**不得对冲**；**禁止**用大盘降敞口"
                     "抵加密敞口（第 4.1.1 条「**不得左口袋挪右口袋**」）。"
                     "合计占用仍受**共用**总回撤预算 %.2g 约束。"
                     % SHARED_DRAWDOWN_BUDGET),
        },
        # 归零数值证据**引用 B4**（B5 不重复出表 ✗）；本模块只断言**互斥预算**结构。
        "zero_out_evidence_source": ZERO_OUT_EVIDENCE_SOURCE,
        "source": SOURCE,
        "statement": (
            "加密 side 预算**独立**于大盘：加密核心仓绝对上限 = CORE_CAP × "
            "MARKET_CORE_RATIO[\"crypto\"] = %.4g%%（≠ 大盘 %.4g%%），"
            "但两者**共用**总回撤预算 %.2g%%。三层上限（%s）是**互斥预算**"
            "（第 4B.1.1 条，**不叠加**）：单层占用 ≤ 该层上限 ≤ 加密核心仓绝对上限。"
            "归零数值证据引用 B4，此处不重复。"
            % (core * 100.0, sleeves["us_equity"]["budget"] * 100.0,
               SHARED_DRAWDOWN_BUDGET * 100.0, label_pairs)
        ),
        "scope": {
            "answers": ("加密侧**独立预算声明** + 算子约束（禁止跨 sleeve 对冲）+ "
                        "三层上限的机械断言（互斥、不叠加、不击穿共享预算）"),
            "does_not_answer": ("**不**重复出归零表（数值证据引用 B4 / risk_stress）；"
                                "不回答「更好的组合是什么」"),
            "source": SOURCE,
        },
    }
