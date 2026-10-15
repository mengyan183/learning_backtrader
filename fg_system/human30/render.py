# fg_system/human30/render.py
# -*- coding: utf-8 -*-
"""§7 官方输出格式（**纯文本**）+ §7.1 硬约束。

🔴 硬约束：
  1. 输出**不得出现数字分数与 Level 数字** ✗（内部照算 ✓，对外一律 Archetype 名/档位词 ✓）
  2. 不得出现交易动词 ✗
  3. 🟡 字段前缀 `AI 复盘（🟡 研究参考，非系统信号）` ✓，不入下游 ✗
  4. 降级必须明示「非原框架的追问判定」✓
  5. **不做**具体 Glitch 推荐 ✗（只做风险提示 ✓）
"""
import re

from . import metatype as _mt
from . import model

AI_PREFIX = "AI 复盘（🟡 研究参考，非系统信号）"
DEGRADED_NOTE = "本结果由固定问卷的确定性映射得出，非原框架的追问判定。"

_GLITCH_TIERS = {
    "low": "建议自然发展（当前不必刻意追求）",
    "mid": "谨慎（如需探索，务必先建立稳定基础）",
    "high": "可考虑（基础已稳，探索风险相对可控）",
}


def level_word(level):
    """层级 → **无数字**显示词（剥掉 `model.LEVELS` 名里的 `1.0 ` 前缀 ✗）。"""
    if level not in model.LEVELS:
        return "未判定"
    return re.sub(r"^\s*\d+(?:\.\d+)?\s*", "", model.LEVELS[level][0])


def phase_word(phase):
    return model.PHASE_LABELS.get(phase or "unknown", "未知")


def _glitch_tier(levels):
    """Glitch 风险三级（确定性 ✓，**只提示不推荐** ✗）。"""
    try:
        band = _mt.total_score(levels)["band"]
    except ValueError:
        return "未判定"
    return _GLITCH_TIERS.get(band, "未判定")


def render_report(levels, phases=None, metatype=None, lifestyle=None,
                  cross=None, degraded=False):
    """按 §7 字段顺序渲染纯文本报告 ✓。"""
    phases = phases or {}
    mt = metatype or {}
    out = ["HUMAN 3.0 DEVELOPMENT ASSESSMENT RESULTS", ""]

    out.append("YOUR METATYPE:")
    out.append("  %s %s" % (AI_PREFIX, mt.get("metatype") or "未判定"))
    if mt.get("narrative"):
        out.append("  %s" % mt["narrative"])
    out.append("")

    out.append("YOUR LIFESTYLE ARCHETYPE:")
    ls = lifestyle or {}
    out.append("  %s" % (ls.get("name") or "未判定"))
    if ls.get("problem"):
        out.append("  核心问题：%s" % ls["problem"])
    out.append("")

    out.append("QUADRANT BREAKDOWN:")
    for q in model.QUADRANTS:
        lv = levels.get(q)
        out.append("  %s：" % model.LABELS[q])
        out.append("    Archetype：%s" % _mt.archetype_name(q, lv))
        out.append("    Current Phase：%s" % phase_word(phases.get(q)))
        out.append("    Consciousness Level：%s" % level_word(lv))
    out.append("")

    out.append("CROSS-QUADRANT DYNAMICS:")
    cr = cross or {}
    for src, dst in (cr.get("unlocked") or []):
        out.append("  Unlock：%s → %s" % (model.LABELS[src], model.LABELS[dst]))
    for src, dst in (cr.get("blocked") or []):
        out.append("  Primary Block：%s → %s" % (model.LABELS[src], model.LABELS[dst]))
    out.append("")

    out.append("YOUR CORE PROBLEM TO SOLVE:")
    out.append("  %s %s" % (AI_PREFIX, (mt.get("metatype") or "未判定")))
    out.append("")

    out.append("GLITCH ASSESSMENT:")
    out.append("  %s" % _glitch_tier(levels))
    out.append("")

    if degraded:
        out.append("⚠️ %s" % DEGRADED_NOTE)
        out.append("")
    return "\n".join(out)


def quadrant_lines(levels, phases=None, lifestyle=None, cross=None):
    """四象限明细（**无数字** ✗）：Archetype 名 · 相位 · 意识层级词。"""
    phases = phases or {}
    return ["%s：%s · %s · %s" % (
        model.LABELS[q],
        _mt.archetype_name(q, levels.get(q)),
        phase_word(phases.get(q)),
        level_word(levels.get(q))) for q in model.QUADRANTS]


def lifestyle_line(lifestyle):
    """Lifestyle 一行（**无数字** ✗）。"""
    ls = lifestyle or {}
    name = ls.get("name") or "未判定"
    prob = ls.get("problem") or ""
    return "Lifestyle：%s%s" % (name, ("（核心问题：%s）" % prob) if prob else "")


def metatype_line(metatype):
    """Metatype 一行（🟡 明标 ✓；降级 ⇒ 明示非原框架 ✓）。"""
    mt = metatype or {}
    body = mt.get("metatype") or "未判定"
    if mt.get("degraded"):
        return "Metatype：%s（确定性降级，非原框架的追问判定）" % body
    return "Metatype：%s %s" % (AI_PREFIX, body)


def degraded_note():
    return DEGRADED_NOTE
