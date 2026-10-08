# -*- coding: utf-8 -*-
"""进化变体：adopted 假说 → 回测变体的**先验定义**（C-1）。

设计：docs/evolution-plan.md 第 ⑤ 步「变体验证」——
  新增变体 = 一个 VARIANTS 条目 + 一条等价性守卫测试；
  **先验推导，不是从回测里搜出来的**（第 8 条 / 第 13.1 条）；
  生产代码零改动（本模块只替换 features 的 target_position 列）。

**本模块只做纯计算**：不读文件、不做 I/O。编排在 scripts/evolve_variant.py。

## 变体机制
回测入口 `runner.run_single(features, symbol)` 消费 features 的
`target_position` 列（FgStrategy 唯一实现 `portfolio.next_position`）。
⇒ 变体 = 对 `target_position` 做**先验变换**后喂同一回测。

## B0 基准
`apply_variant(features, ..., "B0")` 原样返回 ⇒ 输出必须与 baseline.json
逐位一致（等价性守卫红线：默认参数逐位相同）。

## V-H7（adopted 假说 H-007 的规则化）
H-007（2026-10-08 adopted）：trend_blocked_us=True（趋势过滤阻断）组
最大回撤 -37.37% **大于**未阻断组 -34.24%（1760 日样本）。
先验规则化（非调参，固定折扣声明先验）：**阻断日 target_position × 0.5**
（阻断意味着模型认为趋势不支持，实证其回撤更大 ⇒ 更保守）。
"""
import pandas as pd

BASELINE = "B0"
VARIANTS = {
    "V-H7": {
        "label": "趋势阻断日仓位 ×0.5（H-007 实证→先验保守）",
        "factor": 0.5,
        "basis": "H-007 adopted：阻断组回撤 -37.37% > 未阻断 -34.24%",
    },
}
VARIANT_KEYS = (BASELINE,) + tuple(VARIANTS)


def apply_variant(features, portfolio_features, variant):
    """返回**变换后**的 features 副本（只动 target_position 列）。

    - features：Data/features.csv（生产同款，含 target_position）
    - portfolio_features：Data/portfolio_features.csv（含 trend_blocked_us）
    - variant：B0（原样）或 V-H7（阻断日 ×0.5）

    对齐：portfolio_features 与 features 按 date 内连接；阻断标记缺失的
    交易日（如 warmup 段）按未阻断处理（不新增规则，保守）。
    """
    if variant not in VARIANT_KEYS:
        raise KeyError("未知变体 %r；可选：%s" % (variant, tuple(VARIANT_KEYS)))
    out = features.copy()
    if variant == BASELINE:
        return out

    spec = VARIANTS[variant]
    pf = portfolio_features.copy()
    if "date" in pf.columns:
        pf = pf.set_index("date")
    common = out.index.intersection(pf.index)
    blocked = pf.loc[common, "trend_blocked_us"].fillna(False).astype(bool)
    mask = out.index.isin(common[blocked.values])
    # 仅阻断日降仓；阻断列缺失日不动（保守，不加新规则）
    out.loc[mask, "target_position"] = (
        out.loc[mask, "target_position"] * spec["factor"])
    return out
