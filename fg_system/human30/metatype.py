# fg_system/human30/metatype.py
# -*- coding: utf-8 -*-
"""Human 3.0 整体层（**确定性**，无 LLM）。

对应设计文档：
  §1.7  整体分 Σ(层级分)/12〔主文〕+〔Prompt〕
  §1.8  Archetype 词表〔Prompt〕
  §1.9  Lifestyle 6 类〔Prompt〕（主文无此内容）
  §1.11 跨象限 解锁 6 / 阻塞 4〔Prompt〕
  §1.4  回退 / 假性转变〔主文〕+〔Prompt〕
🟡 Metatype 命名与叙述属 P4（走已登记 H-REV-001）。
"""
import json

from . import model


def band_of(avg_level):
    """**平均层级**（值域 1~3）→ 档位。

    ⚠️ 量纲说明（P3 自审修正 ✗）：Glitch 的 `2.0 / 2.5` 三级描述只在
    **平均层级**（= Σ层级分 / 4，值域 1~3 ✓）上成立；
    `Σ(层级分)/12` 的值域是 **0.333~1.0** ✗ ⇒ **不能**把 2.0/2.5 用在它上面 ✗。
    """
    if not (1.0 <= avg_level <= 3.0):
        raise ValueError("平均层级必须在 1.0~3.0（收到 %r）—— 量纲用错了？"
                         % (avg_level,))
    if avg_level < 2.0:
        return "low"
    if avg_level <= 2.5:
        return "mid"
    return "high"


def quadrant_levels(judged):
    """从 assess.judge_all() 的输出抽取四象限层级（可能含 None）。"""
    return {q: judged[q]["level"] for q in model.QUADRANTS}


def total_score(levels):
    """整体分。

    同时给出**两个**量纲（避免混淆 ✓）：
      - `total`     = Σ(层级分) / 12  ← 〔主文〕+〔Prompt〕原文算法 ✓（值域 0.333~1.0）
      - `avg_level` = Σ(层级分) / 4   ← 平均层级（值域 1.0~3.0），**分档用它** ✓
      - `band`      = band_of(avg_level) ✓

    levels: {象限: 1|2|3}（**不允许 None** —— 未判出的象限不得计入 ✗，调用方须先处理）。
    """
    s = 0
    for q in model.QUADRANTS:
        v = levels.get(q)
        if v not in (1, 2, 3):
            raise ValueError("象限 %s 层级非法（需 1/2/3，收到 %r）——"
                             "未判出层级的象限不得计入整体分" % (q, v))
        s += v
    total = s / float(model.TOTAL_SLICES)
    avg_level = s / float(len(model.QUADRANTS))
    return {"sum": s,
            "total": total,
            "avg_level": avg_level,
            "band": band_of(avg_level),
            "slices": model.TOTAL_SLICES}


def archetype_name(quadrant, level):
    """象限 + 层级 → 词表首位名称（〔Prompt〕词表；未判定返回"未判定"）。"""
    if level not in (1, 2, 3):
        return "未判定"
    names = model.ARCHETYPES.get(quadrant, {}).get(level) or []
    return names[0] if names else "未判定"


def archetype_names(levels):
    return {q: archetype_name(q, levels.get(q)) for q in model.QUADRANTS}


_LS = {a["name"]: a for a in model.LIFESTYLE_ARCHETYPES}


def _lifestyle_record(name):
    a = _LS[name]
    return {"name": a["name"], "trait": a["trait"],
            "problem": a["problem"], "solution": a["solution"]}


def lifestyle(levels):
    """Lifestyle Archetype 判定（6 类〔Prompt〕；阈值为〔自创〕）。

    优先级（先判先得）—— **具体形态先于泛化形态** ✓：
      1. 全象限 ≥2                            → The Integrated
      2. Vocation 比其它三象限都高 ≥2 档       → The Workaholic
      3. Spirit/Mind 高于 Body/Vocation ≥2 档  → The Seeker
      4. Body/Mind 高于 Spirit/Vocation ≥2 档  → The Optimizer
      5. 一个象限 L3 且其余全 L1               → The Specialist
      6. 其余                                  → The Drifter

    🔴 **为什么 Specialist 必须排在后面**（P3 自审修正 ✗）：
    「vocation 领先 ≥2 档」在层级只有 1/2/3 时，**必然意味着其余全 L1** ✗ ⇒
    若 Specialist（一个 L3 + 其余全 L1）先判，则 **Workaholic 永远不可达** ✗✗。
    语义上「事业独大」是**更具体**的形态 ⇒ 应先判 ✓。

    含未判定（None）象限 ⇒ 返回"未判定"（不猜 ✗）。
    """
    lv = {q: levels.get(q) for q in model.QUADRANTS}
    if any(v is None for v in lv.values()):
        return {"name": "未判定", "trait": "", "problem": "", "solution": ""}

    if all(v >= 2 for v in lv.values()):
        return _lifestyle_record("The Integrated")

    def hi(qs, others):
        return (min(lv[q] for q in qs) - max(lv[q] for q in others)) >= 2

    if hi(["vocation"], ["mind", "body", "spirit"]):
        return _lifestyle_record("The Workaholic")
    if hi(["spirit", "mind"], ["body", "vocation"]):
        return _lifestyle_record("The Seeker")
    if hi(["body", "mind"], ["spirit", "vocation"]):
        return _lifestyle_record("The Optimizer")

    l3 = [q for q, v in lv.items() if v == 3]
    if len(l3) == 1 and all(lv[q] == 1 for q in model.QUADRANTS if q != l3[0]):
        return _lifestyle_record("The Specialist")
    return _lifestyle_record("The Drifter")


def cross_quadrant(levels):
    """跨象限解锁 / 阻塞提示〔Prompt〕（**只做提示，不改任何判决** ✓）。

    解锁：源象限达 L2+ ⇒ 该序列被激活。
    阻塞：源象限为 L1 且目标象限 ≥L2 ⇒ 触发阻塞提示。
    含未判定（None）的象限 ⇒ 一律跳过（不猜 ✗）。
    """
    unlocked, blocked = [], []
    for src, dst in model.UNLOCK_SEQUENCES:
        s, d = levels.get(src), levels.get(dst)
        if s is None or d is None:
            continue
        if s >= 2:
            unlocked.append((src, dst))
        elif d >= 2:
            blocked.append((src, dst))
    return {"unlocked": unlocked, "blocked": blocked}


def false_transformation(levels, hits=None):
    """假性转变判定〔主文〕+〔Prompt〕16 条。

    hits: {象限: [命中的指标字符串]}（由问卷 / 🟡 追问给出）。
    规则：自评 L3 且命中该象限 ≥1 条 ⇒ True。
    """
    hits = hits or {}
    return {q: bool(levels.get(q) == 3 and hits.get(q)) for q in model.QUADRANTS}


def regression(levels, prev_levels):
    """回退判定〔主文〕：相对上一次，层级下降 ⇒ True（压力下退回低层 ✓）。"""
    return {q: bool(levels.get(q) is not None
                    and prev_levels.get(q) is not None
                    and levels[q] < prev_levels[q])
            for q in model.QUADRANTS}


# ---------------------------------------------------------------- 🟡 Metatype（H-REV-001）

_META_PROMPT = """你在做 Human 3.0 的 **Metatype 命名**（原文的招牌输出）。

四象限层级（JSON）：%s

请给出：
1. `metatype`：一个**动态名称**（2~4 个词，英文或中文均可，**不得含数字** ✗）
2. `narrative`：2~3 句叙述

严格只输出合法 JSON，字段名勿改：
{"metatype": "...", "narrative": "..."}"""

_BAND_WORD = {"low": "起步期", "mid": "发展期", "high": "整合期"}


def _fallback_metatype(levels):
    """确定性降级：Archetype 词表 + 整体档位（🔴 **不含数字** ✗）。"""
    names = archetype_names(levels)
    try:
        band = band_of(total_score(levels)["avg_level"])
    except ValueError:
        band = None
    band_word = _BAND_WORD.get(band, "未判定")
    return "以 %s 为主线的%s组合" % (names.get("vocation") or "未判定", band_word)


def generate(levels, client=None):
    """🟡 Metatype 命名与叙述（**已登记例外 H-REV-001**）。

    成功: {"metatype": str, "narrative": str, "via": str, "degraded": False}
    降级: {"metatype": <词表+档位，不含数字>, "narrative": "",
           "via": "deterministic", "degraded": True}
    """
    from . import llm

    llm.require_exception()          # 守卫 3（**调用时**检查 ✓）
    try:
        text, via = llm.call_llm(
            _META_PROMPT % json.dumps(levels, ensure_ascii=False), client=client)
        data = llm.extract_json(text)
        name = (data.get("metatype") or "").strip()
        if not name:
            raise ValueError("metatype 为空")
        return {"metatype": name,
                "narrative": (data.get("narrative") or "").strip(),
                "via": via, "degraded": False}
    except Exception:
        return {"metatype": _fallback_metatype(levels), "narrative": "",
                "via": "deterministic", "degraded": True}


def deterministic_metatype(levels):
    """确定性 Metatype（看板/简报默认用 ✓，**不调 LLM** ✗）。"""
    return {"metatype": _fallback_metatype(levels), "narrative": "",
            "via": "deterministic", "degraded": True}
