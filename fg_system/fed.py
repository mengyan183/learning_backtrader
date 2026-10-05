# -*- coding: utf-8 -*-
"""美联储政策环境（FOMC）上下文计算。

给看板/简报提供：政策方向标签、目标利率区间、最近决议、
下次 FOMC 会议/纪要倒计时、事件窗口提醒、环境温度修正提示。

设计原则（§12.31）：
- 数据 = config.py 内嵌官方日历（federalreserve.gov），人工随官方更新
- 只做"环境上下文"，**不进入 fg_index 合成**（避免改变指数历史口径）；
  校准成熟后可升级为独立 Fed 因子再议
- 事件窗口：FOMC 前 7 天（config.FED_EVENT_WINDOW_DAYS）标记，提示谨慎
"""
import datetime as dt

from fg_system import config


def _parse(d):
    return dt.date.fromisoformat(d)


def fed_context(today=None):
    """返回美联储环境字典。today=None 用系统当前日期。"""
    today = today or dt.date.today()
    meetings = [_parse(a) for a, _ in config.FOMC_MEETINGS_2026]
    minutes = [( _parse(r), _parse(m)) for r, m in config.FOMC_MINUTES_2026]

    # 下次会议（含今天在内找最近的未开会议）
    next_meeting = None
    for m in meetings:
        if m >= today:
            next_meeting = m
            break
    # 上次会议（已开）
    last_meeting = None
    for m in meetings:
        if m < today:
            last_meeting = m
    # 下次纪要发布
    next_minutes = None
    for r, _ in minutes:
        if r >= today:
            next_minutes = r
            break

    ctx = {
        "stance": config.FED_STANCE,
        "range_txt": config.FED_RANGE_TXT,
        "last_decision": config.FED_LAST_DECISION,
        "last_decision_txt": config.FED_LAST_DECISION_TXT,
        "outlook_txt": config.FED_OUTLOOK_TXT,
        "event_window": False,
        "event_window_days": config.FED_EVENT_WINDOW_DAYS,
        "next_meeting": None,
        "days_to_meeting": None,
        "next_minutes": None,
        "days_to_minutes": None,
        "sentiment_tone": None,   # 环境温度修正提示
    }
    if next_meeting is not None:
        d = (next_meeting - today).days
        ctx["next_meeting"] = next_meeting.isoformat()
        ctx["days_to_meeting"] = d
        if 0 <= d <= config.FED_EVENT_WINDOW_DAYS:
            ctx["event_window"] = True
    if next_minutes is not None:
        ctx["next_minutes"] = next_minutes.isoformat()
        ctx["days_to_minutes"] = (next_minutes - today).days

    # 环境温度修正：加息周期压制风险偏好，贪婪档位需谨慎；
    # 降息周期支撑，恐惧档位可视为更好机会。
    if config.FED_STANCE == "加息周期":
        ctx["sentiment_tone"] = ("政策收紧：贪婪档位信号打折扣，"
                                 "追高需谨慎；恐惧档位可分批布局")
    elif config.FED_STANCE == "降息周期":
        ctx["sentiment_tone"] = ("政策宽松：流动性支撑风险偏好，"
                                 "恐惧档位更具吸引力，但注意宽松尾声")
    else:
        ctx["sentiment_tone"] = ("政策按兵不动：情绪由基本面主导，"
                                 "聚焦通胀数据与下次会议指引")
    return ctx


def fed_brief_text(ctx):
    """简报用单段文本（飞书富文本正文行）。"""
    parts = [
        "政策方向：%s · 目标区间 %s" % (ctx["stance"], ctx["range_txt"]),
        ctx["last_decision_txt"],
        ctx["outlook_txt"],
    ]
    if ctx["next_meeting"]:
        w = ("⚠️ 已进入 FOMC 事件窗口（%d 天内开会）" % ctx["days_to_meeting"]
             if ctx["event_window"] else
             "下次 FOMC：%s（还有 %d 天）" % (ctx["next_meeting"], ctx["days_to_meeting"]))
        parts.append(w)
    if ctx["next_minutes"]:
        parts.append("纪要发布：%s（%d 天后）" % (ctx["next_minutes"], ctx["days_to_minutes"]))
    parts.append(ctx["sentiment_tone"])
    return "；".join(parts)


def fed_card_html(ctx):
    """渲染美联储环境卡片（看板市场温度下方）。"""
    w = ctx["event_window"]
    ev = ("<span class='tag tag-zone' style='background:#f0ad4e'>⚠️ FOMC 事件窗口"
          "（%d 天内开会，谨慎）</span>" % ctx["days_to_meeting"]) if w else ""
    mt = ("<span class='tag tag-zone' style='background:#3a4a63'>下次会议 "
          "%s（还有 %d 天）</span>" % (ctx["next_meeting"], ctx["days_to_meeting"])
          if ctx["next_meeting"] else "")
    mn = ("<span class='tag tag-zone' style='background:#3a4a63'>纪要 %s"
          "（%d 天后）</span>" % (ctx["next_minutes"], ctx["days_to_minutes"])
          if ctx["next_minutes"] else "")
    return (
        "<div class='fed-card'>"
        "<div class='fed-row'><b>美联储政策环境</b>"
        "<span class='tag tag-zone' style='background:#8b0000'>%s</span></div>"
        "<div class='fed-row'>目标利率区间 <b>%s</b> · 最近决议：%s</div>"
        "<div class='fed-row fed-muted'>%s</div>"
        "<div class='fed-row'>%s %s %s</div>"
        "<div class='fed-row fed-tone'>%s</div>"
        "</div>"
    ) % (ctx["stance"], ctx["range_txt"], ctx["last_decision_txt"],
         ctx["outlook_txt"], ev, mt, mn, ctx["sentiment_tone"])
