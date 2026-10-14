# fg_system/human30/metrics.py
# -*- coding: utf-8 -*-
"""Human 3.0 指标层（确定性，无 LLM）。由 v1 整体搬迁而来。"""
from datetime import date

from . import model
from .store import record, latest, _load, bucket_level


def answers_to_scores(answers):
    """{象限: 1..5} → {象限: 0-100}。非法 level 抛 ValueError（确定性查表）。"""
    out = {}
    for q in model.QUADRANTS:
        v = answers.get(q)
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise ValueError("参数 %s 必须是 1-5 的整数" % q)
        if v not in model.LIKERT_SCORES:
            raise ValueError("参数 %s 超出 1-5（%s）" % (q, v))
        out[q] = model.LIKERT_SCORES[v]
    return out


def record_from_answers(mind, body, spirit, vocation, note="", when=None, market=None):
    """问答打卡：5 级答案 → 分数 → 与 record() 同路径写入。"""
    scores = answers_to_scores({"mind": mind, "body": body,
                                "spirit": spirit, "vocation": vocation})
    return record(scores["mind"], scores["body"], scores["spirit"],
                  scores["vocation"], note=note, when=when, market=market)


def aggregate(rec):
    """四象限聚合：avg / std / level / 短板。确定性规则，无 LLM。"""
    vals = [rec[q] for q in model.QUADRANTS]
    avg = sum(vals) / len(vals)
    mean = avg
    std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    if avg < 40:
        level, level_name, level_desc = 1, model.LEVELS[1][0], model.LEVELS[1][1]
    elif avg <= 70:
        level, level_name, level_desc = 2, model.LEVELS[2][0], model.LEVELS[2][1]
    else:
        level, level_name, level_desc = 3, model.LEVELS[3][0], model.LEVELS[3][1]
    weakest = min(model.QUADRANTS, key=lambda q: rec[q])
    quadrant_levels = {q: bucket_level(rec[q]) for q in model.QUADRANTS}
    return {
        "avg": round(avg, 1),
        "std": round(std, 1),
        "level": level,                  # ← 旧语义：整体均分档，**保持不变**
        "level_name": level_name,
        "level_desc": level_desc,
        "weakest": weakest,
        "weakest_label": model.LABELS[weakest],
        "weakest_val": rec[weakest],
        "imbalanced": std > 20,
        "quadrant_levels": quadrant_levels,         # ← 新增（v2 用）
        "weakest_level": quadrant_levels[weakest],  # ← 新增（v2 用）
    }


def advice(rec, prev=None):
    """规则化建议（无 LLM）。返回建议列表。"""
    agg = aggregate(rec)
    out = []
    w = agg["weakest"]
    # 短板优先（Koe：四象限同步升级，木桶短板是主要矛盾）
    if agg["weakest_val"] < 40:
        out.append(f"优先补短板：{model.LABELS[w]}（{agg['weakest_val']:.0f}/100）低于 40，"
                   "四象限同步升级的木桶短板——先聚焦它再谈整体。")
    elif agg["weakest_val"] < 70:
        out.append(f"次短板在{model.LABELS[w]}（{agg['weakest_val']:.0f}/100），"
                   "处于 2.0 区间，建议保持节奏、小幅提升。")
    else:
        out.append("四象限均已 ≥70：已达综合者态，建议外化输出"
                   "（Vocation 传承/教学/沉淀系统），而非继续内卷自评。")
    # 失衡标记
    if agg["imbalanced"]:
        out.append(f"四象限失衡（std={agg['std']}）：{model.LABELS[w]}显著落后，"
                   "注意别让短板象限拖垮整体迁移能力。")
    # 趋势（与上次比：下降象限提示）
    if prev:
        drops = [q for q in model.QUADRANTS if rec[q] < prev[q] - 5]
        if drops:
            out.append("较上次下降的象限：" + "、".join(model.LABELS[q] for q in drops)
                       + "——检查是状态波动还是真实退化。")
    # 行动原则（孙学引擎注入，骨架期仅提示，不执行）
    out.append("行动原则（孙学引擎）：先开地图再下注 · 先行动再补条件 · 小自我 · AI 自动化。")
    return out


def brief_line(rec=None):
    """简报用一行状态（无记录返回 None）。

    `rec` 可选：传入则直接用该记录（便于纯函数式调用/测试）；不传则取最新一条。
    """
    if rec is None:
        rec = latest()
    if not rec:
        return None
    agg = aggregate(rec)
    return (f"Level {agg['level_name']}（四象限均分 {agg['avg']}，"
            f"短板 {agg['weakest_label']} {agg['weakest_val']:.0f}"
            f"{'，失衡' if agg['imbalanced'] else ''}）")


def days_since_last(today=None):
    """距上次打卡的自然日天数；从未打卡返回 None。"""
    rec = latest()
    if not rec:
        return None
    from datetime import datetime
    last = datetime.strptime(rec["date"], "%Y-%m-%d").date()
    ref = today or date.today()
    return max(0, (ref - last).days)


def window_stats(days=7, today=None):
    """指定窗口（自然日）内的确定性统计，供简报/页面汇总。

    返回：{"records": n, "level_counts": {1:..,2:..,3:..},
           "weakest_counts": {label:..}, "avg_series": [{"date","avg"}],
           "window_days": days, "no_data": bool}
    """
    ref = today or date.today()
    from datetime import timedelta
    start = ref - timedelta(days=days - 1)
    recs = [r for r in _load().get("records", [])
            if start.isoformat() <= r["date"] <= ref.isoformat()]
    level_counts = {1: 0, 2: 0, 3: 0}
    weakest_counts = {}
    avg_series = []
    for r in recs:
        agg = aggregate(r)
        level_counts[agg["level"]] = level_counts.get(agg["level"], 0) + 1
        weakest_counts[agg["weakest_label"]] = weakest_counts.get(agg["weakest_label"], 0) + 1
        avg_series.append({"date": r["date"], "avg": agg["avg"]})
    return {
        "records": len(recs),
        "level_counts": level_counts,
        "weakest_counts": weakest_counts,
        "avg_series": avg_series,
        "window_days": days,
        "no_data": not recs,
    }


def to_csv(path):
    """导出全部记录为 CSV（date, mind, body, spirit, vocation, avg, level, weakest, fg_index, zone, note）。"""
    import csv as _csv
    recs = _load().get("records", [])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["date", "mind", "body", "spirit", "vocation",
                    "avg", "level", "weakest", "fg_index", "zone", "note"])
        for r in recs:
            agg = aggregate(r)
            mkt = r.get("market") or {}
            w.writerow([r["date"], r["mind"], r["body"], r["spirit"], r["vocation"],
                        agg["avg"], agg["level"], agg["weakest_label"],
                        mkt.get("fg_index", ""), mkt.get("zone", ""), r.get("note", "")])
    return path


def insight_summary(days=7, today=None):
    """L3.5 规则化复盘洞察（确定性，无 LLM 判决）。

    基于 window_stats + history 提炼：
    - 打卡纪律：窗口打卡率（records / 窗口自然日）
    - 主导水平：窗口内占比最高的 self-rating level（1/2/3 → 1.0/2.0/3.0 段）
    - 短板聚焦：窗口内出现频率最高的最弱象限
    - 趋势：窗口前后半段 avg 比较（上升/下降/持平）
    返回 list[str]（洞察行），无数据时返回 ["窗口内无打卡记录，暂无可提炼洞察。"]。
    """
    from datetime import date as _date
    if isinstance(today, str):
        today = _date.fromisoformat(today)
    ws = window_stats(days=days, today=today)
    if ws["no_data"]:
        return ["窗口内无打卡记录，暂无可提炼洞察。"]
    out = []
    # 打卡纪律
    rate = ws["records"] / max(ws["window_days"], 1)
    out.append("打卡纪律：%d/%d 天（%.0f%%）%s"
               % (ws["records"], ws["window_days"], rate * 100,
                  "——连续性良好" if rate >= 0.7 else "——存在断档，注意保持节奏"))
    # 主导水平
    lc = ws["level_counts"]
    dom = max(lc, key=lc.get)
    out.append("主导水平：%s 段（%d/%d 天）%s"
               % ({1: "1.0", 2: "2.0", 3: "3.0"}[dom], lc[dom], ws["records"],
                  "——仍处积累期" if dom == 1 else (
                      "——升级期，具备迁移/外化条件" if dom == 3 else "——稳步爬坡中")))
    # 短板聚焦
    wc = ws["weakest_counts"]
    if wc:
        wmax = max(wc, key=wc.get)
        out.append("短板聚焦：%s 出现频率最高（%d 次）——优先补它，木桶短板是主要矛盾"
                   % (wmax, wc[wmax]))
    # 趋势（窗口前后半段 avg 比较）
    series = [s["avg"] for s in ws["avg_series"]]
    if len(series) >= 4:
        half = len(series) // 2
        a, b = sum(series[:half]) / half, sum(series[half:]) / (len(series) - half)
        diff = b - a
        out.append("趋势：窗口后半段 vs 前半段 %+.1f%s"
                   % (diff, "（上升）" if diff >= 3 else ("（下降）" if diff <= -3 else "（持平）")))
    return out
