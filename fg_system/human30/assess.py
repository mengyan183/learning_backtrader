# fg_system/human30/assess.py
# -*- coding: utf-8 -*-
"""Human 3.0 判定层（**确定性降级路径**，无 LLM）。

🟡 追问主路径见 P4（原框架的 LLM 自适应访谈）。
本模块对应设计文档 §5.2~§5.5 的固定问卷 + 确定性规则。
⚠️ 规则本身为〔自创〕（原文靠 LLM 判断），已在 docs/human30-v2-design.md 中明示。
"""
from . import model


def judge_level(answers, quadrant=None, ft_hits=None):
    """由 3 道题（各 1/2/3 分）判定某象限层级。

    规则（设计 §5.3）：
      - 三题一致      → level=该值, confidence="high"
      - 两同一异      → level=多数值, confidence="medium", straddling=True
      - 三题互不相同  → level=None, confidence="low",  straddling=True
                        （**禁止静默取中位数** —— 评审 M-4：那会系统性归到 L2）
    守卫 14：若自评 L3 且命中该象限假性转变指标 ⇒ false_transformation=True 且降 confidence。
    """
    vals = list(answers)
    if len(vals) != 3:
        raise ValueError("判层需要恰好 3 道题的答案")
    for v in vals:
        if v not in (1, 2, 3):
            raise ValueError("每题答案必须是 1/2/3，收到：%r" % (v,))

    uniq = sorted(set(vals))
    if len(uniq) == 1:
        level, conf, straddle = uniq[0], "high", False
    elif len(uniq) == 2:
        level, conf, straddle = sorted(vals)[1], "medium", True
    else:
        level, conf, straddle = None, "low", True

    ft = False
    if level == 3 and ft_hits:
        ft = True
        conf = "medium" if conf == "high" else "low"

    return {
        "level": level,
        "confidence": conf,
        "straddling": straddle,
        "answers": vals,
        "false_transformation": ft,
    }


def judge_all(answers_by_quadrant, ft_by_quadrant=None):
    """四象限判层。answers_by_quadrant: {象限: [3 题]}。"""
    ft_by_quadrant = ft_by_quadrant or {}
    return {
        q: judge_level(answers_by_quadrant[q], quadrant=q,
                       ft_hits=ft_by_quadrant.get(q))
        for q in model.QUADRANTS
    }


# 相位问卷：1 题三选一（设计 §5.4，由官方相位检测问题改写，选项为〔自创〕）
PHASE_OPTIONS = {
    "stale": "dissonance",          # 我对现状感到厌倦/停滞，但不知道下一步
    "exploring": "uncertainty",     # 我正在尝试新的东西，还在摸索中
    "integrating": "discovery",     # 我找到了有效的方法/洞见，正在整合
}

# Traits 三档（设计 §5.5；题干照官方，三档计分为〔自创〕）
TRAIT_TIERS = {"yes": 3, "some": 2, "no": 1}


def judge_phase(answer):
    """相位判定。None/空 ⇒ "unknown"；非法值 ⇒ ValueError。"""
    if answer in (None, ""):
        return "unknown"
    if answer not in PHASE_OPTIONS:
        raise ValueError("相位答案非法：%r（可选 %s）"
                         % (answer, sorted(PHASE_OPTIONS)))
    return PHASE_OPTIONS[answer]


def phase_label(phase):
    """相位中文标签。"""
    return model.PHASE_LABELS.get(phase, "未知")


def judge_traits(answers):
    """Traits 三档判定：{knowledge/experience/skill: "yes"|"some"|"no"} → 3/2/1。"""
    out = {}
    for t in model.TRAITS:
        v = answers.get(t)
        if v not in TRAIT_TIERS:
            raise ValueError("Trait %s 答案非法：%r（可选 %s）"
                             % (t, v, sorted(TRAIT_TIERS)))
        out[t] = TRAIT_TIERS[v]
    return out
