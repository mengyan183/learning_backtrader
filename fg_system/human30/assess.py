# fg_system/human30/assess.py
# -*- coding: utf-8 -*-
"""Human 3.0 判定层（**确定性降级路径**，无 LLM）。

🟡 追问主路径见 P4（原框架的 LLM 自适应访谈）。
本模块对应设计文档 §5.2~§5.5 的固定问卷 + 确定性规则。
⚠️ 规则本身为〔自创〕（原文靠 LLM 判断），已在 docs/human30-v2-design.md 中明示。
"""
import json

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


# ---------------------------------------------------------------- 🟡 主路径（H-REV-001）

_PROMPT_TMPL = """你在做 Human 3.0 发展层级评估。基于下面的追问记录，
判定四个象限各自的**层级**（1/2/3）、**相位**（"dissonance"/"uncertainty"/"discovery" 之一）与 **Traits**（knowledge/experience/skill，各 1/2/3）。

追问记录（JSON）：
%s

严格只输出合法 JSON，字段名勿改，缺字段即失败：
{"mind": {"level": 1|2|3, "confidence": "high|medium|low", "phase": "dissonance"|"uncertainty"|"discovery",
          "traits": {"knowledge": 1|2|3, "experience": 1|2|3, "skill": 1|2|3}},
 "body": {...}, "spirit": {...}, "vocation": {...}}"""


def _extract_json(text):
    import re
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)


def _undetermined():
    """诚实"未判定"降级（**不猜** ✗）：四象限 level=None + fallback 标 ✓。"""
    out = {q: {"level": None, "confidence": "low",
               "detail": {"answers": []}, "phase": None, "traits": {}}
           for q in model.QUADRANTS}
    out["degraded"] = True
    out["via"] = "deterministic"
    out["fallback"] = "fixed_questionnaire"
    return out


def judge_via_llm(transcript, client=None, fixed_answers=None):
    """🟡 主路径：LLM 自适应追问判定（**已登记例外 H-REV-001**）。

    transcript: {象限: [{"q": 追问原文, "a": 回答}, ...]}
    返回与 `judge_all()` **同构** ✓，外加 `degraded` / `via`（/`fallback`）。

    降级（🟡 失败：抛错 / 非法 JSON / 字段非法 / 空 transcript）：
      · 给了 `fixed_answers`（{象限: [1|2|3] × 3}）⇒ 走 `judge_all(fixed_answers)` ✓
      · 否则 ⇒ `_undetermined()` ✓
    🔴 **不得**把自由文本机械映射成 1/2/3 ✗（那是发明新规则 ✗）。
    """
    from . import llm

    llm.require_exception()          # 守卫 3（**调用时**检查 ✓）

    def _degrade():
        if fixed_answers is not None:
            base = judge_all(fixed_answers)
            base["degraded"] = True
            base["via"] = "deterministic"
            return base
        return _undetermined()

    if not transcript or not any(transcript.get(q) for q in model.QUADRANTS):
        return _degrade()
    try:
        text, via = llm.call_llm(
            _PROMPT_TMPL % json.dumps(transcript, ensure_ascii=False), client=client)
        data = _extract_json(text)
        out = {}
        for q in model.QUADRANTS:
            d = data[q]
            if d.get("level") not in (1, 2, 3, None):
                return _degrade()
            if d.get("phase") not in (set(model.PHASES) | {"unknown", None}):
                return _degrade()
            tr = d.get("traits") or {}
            if not set(model.TRAITS) <= set(tr):
                return _degrade()
            out[q] = {"level": d.get("level"),
                      "confidence": d.get("confidence") or "medium",
                      "detail": {"answers": transcript.get(q) or []},
                      "phase": d.get("phase"),
                      "traits": {k: tr[k] for k in model.TRAITS}}
    except Exception:
        return _degrade()
    out["degraded"] = False
    out["via"] = via
    return out
