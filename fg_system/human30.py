# -*- coding: utf-8 -*-
"""Human 3.0 组合骨架（2026-10-10 用户定：四象限自评 + 每日状态记录 + 简报输出）。

框架来源：Dan Koe Human 3.0（四象限 × 三级意识）+ 孙宇晨×邵艾伦访谈行动原则
（先开地图/先行动/小自我/AI 自动化）——本模块先落地**确定性规则**部分：
四象限自评打卡、聚合判定意识层级、短板提示，无 LLM 判决（仓库纪律）。

四象限（0-100 自评）：
  mind     心/认知（思维、心智模型、认知升级）
  body     体/行动（健康、健身、执行力）
  spirit   精神/意义（关系、心态、小自我、生命感）
  vocation 职/事业（事业、系统、选择权、轻资产）

意识层级判定（可复算规则）：
  avg < 40        → L1 从众者 Conformist（外部权威驱动）
  40 <= avg <= 70 → L2 个体主义者 Individualist（内部权威驱动）
  avg > 70        → L3 综合者 Synthesist（多视角整合、策略设计）
  std > 20        → 失衡标记（某象限拖后腿，聚焦短板）

数据文件：Data/human30.json（运行态，不入库）：
  {"records": [{"date":"YYYY-MM-DD","mind":..,"body":..,"spirit":..,"vocation":..,"note":""}, ...]}
"""
import json
import os
from datetime import date

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "Data", "human30.json")

QUADRANTS = ["mind", "body", "spirit", "vocation"]
LABELS = {"mind": "心/认知", "body": "体/行动", "spirit": "精神/意义", "vocation": "职/事业"}
LEVELS = {
    1: ("1.0 从众者 Conformist", "外部权威驱动 · 规则思维 · 被社会模板定义"),
    2: ("2.0 个体主义者 Individualist", "内部权威驱动 · 理性思维 · 坚持自己的方式"),
    3: ("3.0 综合者 Synthesist", "多视角整合 · 策略设计 · 能综合出更整体方案"),
}


def _load():
    if not os.path.exists(DATA_PATH):
        return {"records": []}
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"records": []}


def _save(data):
    d = os.path.dirname(DATA_PATH)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def record(mind, body, spirit, vocation, note="", when=None):
    """追加一条自评记录（当日重复打卡则覆盖当日）。返回该记录。"""
    for v in (mind, body, spirit, vocation):
        if not (0 <= v <= 100):
            raise ValueError("四象限评分必须在 0-100 之间")
    rec = {
        "date": when or date.today().isoformat(),
        "mind": float(mind), "body": float(body),
        "spirit": float(spirit), "vocation": float(vocation),
        "note": note,
    }
    data = _load()
    data.setdefault("records", [])
    data["records"] = [r for r in data["records"] if r.get("date") != rec["date"]]
    data["records"].append(rec)
    data["records"].sort(key=lambda r: r["date"])
    _save(data)
    return rec


def latest():
    """最新一条记录；无记录返回 None。"""
    records = _load().get("records", [])
    return records[-1] if records else None


def history(n=30):
    """最近 n 条记录（时间升序）。"""
    return _load().get("records", [])[-n:]


def aggregate(rec):
    """四象限聚合：avg / std / level / 短板。确定性规则，无 LLM。"""
    vals = [rec[q] for q in QUADRANTS]
    avg = sum(vals) / len(vals)
    mean = avg
    std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    if avg < 40:
        level, level_name, level_desc = 1, LEVELS[1][0], LEVELS[1][1]
    elif avg <= 70:
        level, level_name, level_desc = 2, LEVELS[2][0], LEVELS[2][1]
    else:
        level, level_name, level_desc = 3, LEVELS[3][0], LEVELS[3][1]
    weakest = min(QUADRANTS, key=lambda q: rec[q])
    return {
        "avg": round(avg, 1),
        "std": round(std, 1),
        "level": level,
        "level_name": level_name,
        "level_desc": level_desc,
        "weakest": weakest,
        "weakest_label": LABELS[weakest],
        "weakest_val": rec[weakest],
        "imbalanced": std > 20,
    }


def advice(rec, prev=None):
    """规则化建议（无 LLM）。返回建议列表。"""
    agg = aggregate(rec)
    out = []
    w = agg["weakest"]
    # 短板优先（Koe：四象限同步升级，木桶短板是主要矛盾）
    if agg["weakest_val"] < 40:
        out.append(f"优先补短板：{LABELS[w]}（{agg['weakest_val']:.0f}/100）低于 40，"
                   "四象限同步升级的木桶短板——先聚焦它再谈整体。")
    elif agg["weakest_val"] < 70:
        out.append(f"次短板在{LABELS[w]}（{agg['weakest_val']:.0f}/100），"
                   "处于 2.0 区间，建议保持节奏、小幅提升。")
    else:
        out.append("四象限均已 ≥70：已达综合者态，建议外化输出"
                   "（Vocation 传承/教学/沉淀系统），而非继续内卷自评。")
    # 失衡标记
    if agg["imbalanced"]:
        out.append(f"四象限失衡（std={agg['std']}）：{LABELS[w]}显著落后，"
                   "注意别让短板象限拖垮整体迁移能力。")
    # 趋势（与上次比：下降象限提示）
    if prev:
        drops = [q for q in QUADRANTS if rec[q] < prev[q] - 5]
        if drops:
            out.append("较上次下降的象限：" + "、".join(LABELS[q] for q in drops)
                       + "——检查是状态波动还是真实退化。")
    # 行动原则（孙学引擎注入，骨架期仅提示，不执行）
    out.append("行动原则（孙学引擎）：先开地图再下注 · 先行动再补条件 · 小自我 · AI 自动化。")
    return out


def brief_line():
    """简报用一行状态（无记录返回 None）。"""
    rec = latest()
    if not rec:
        return None
    agg = aggregate(rec)
    return (f"Level {agg['level_name']}（四象限均分 {agg['avg']}，"
            f"短板 {agg['weakest_label']} {agg['weakest_val']:.0f}"
            f"{'，失衡' if agg['imbalanced'] else ''}）")
