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
import os

import pandas as pd

from fg_system import config


def _load_fedwatch():
    """读 CME FedWatch 市场预期 CSV（scripts/fetch_fedwatch.py 产出）。
    返回最新一行 dict；无数据返回 None。"""
    p = os.path.join(config.RAW_DIR, "fedwatch.csv")
    try:
        df = pd.read_csv(p)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return None
    if df.empty:
        return None
    return df.iloc[-1].to_dict()


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
        # 宏观事件日历（CPI/非农，P3）：可缺失
        "macro_event": None, "macro_date": None, "days_to_macro": None,
        "macro_window": False, "macro_window_days": config.MACRO_EVENT_WINDOW_DAYS,
        # 市场预期（CME FedWatch，可缺失）
        "fw_meeting": None, "fw_hold": None, "fw_hike": None, "fw_ease": None,
        "fw_delta_1w": None, "fw_date": None,
    }
    fw = _load_fedwatch()
    if fw is not None:
        try:
            ctx["fw_meeting"] = str(fw.get("meeting") or "")
            _e = fw.get("ease_pct")
            ctx["fw_ease"] = (float(_e) if pd.notna(_e) and _e is not None
                              else float("nan"))
            _h = fw.get("hold_pct")
            ctx["fw_hold"] = (float(_h) if pd.notna(_h) and _h is not None
                              else float("nan"))
            _k = fw.get("hike_pct")
            ctx["fw_hike"] = (float(_k) if pd.notna(_k) and _k is not None
                              else float("nan"))
            wk = fw.get("wk_hike_pct")
            ctx["fw_delta_1w"] = (ctx["fw_hike"] - float(wk)) if wk == wk else None
            ctx["fw_date"] = str(fw.get("date") or "")
        except (TypeError, ValueError):
            pass
    if next_meeting is not None:
        d = (next_meeting - today).days
        ctx["next_meeting"] = next_meeting.isoformat()
        ctx["days_to_meeting"] = d
        if 0 <= d <= config.FED_EVENT_WINDOW_DAYS:
            ctx["event_window"] = True
    if next_minutes is not None:
        ctx["next_minutes"] = next_minutes.isoformat()
        ctx["days_to_minutes"] = (next_minutes - today).days

    # 宏观事件日历（CPI/非农，FRED 官方日程，config.MACRO_EVENTS_2026）
    for d0, name in config.MACRO_EVENTS_2026:
        if _parse(d0) >= today:
            ctx["macro_event"] = name
            ctx["macro_date"] = d0
            ctx["days_to_macro"] = (_parse(d0) - today).days
            ctx["macro_window"] = 0 <= ctx["days_to_macro"] <= config.MACRO_EVENT_WINDOW_DAYS
            break

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
    if ctx["macro_event"]:
        w = ("⚠️ 宏观事件窗口（%s 明日发布）" % ctx["macro_event"]
             if ctx["macro_window"] and ctx["days_to_macro"] == 1
             else "⚠️ 宏观事件窗口（%s %d 天后发布，避免重仓押注方向）"
             % (ctx["macro_event"], ctx["days_to_macro"])
             if ctx["macro_window"]
             else "下次宏观数据：%s（%s，%d 天后）"
             % (ctx["macro_event"], ctx["macro_date"], ctx["days_to_macro"]))
        parts.append(w)
    if ctx["fw_meeting"]:
        fw = "市场预期（CME FedWatch %s）：维持 %.1f%% / 加息25bp %.1f%% / 降息 %.1f%%"
        fw = fw % (ctx["fw_date"], ctx["fw_hold"], ctx["fw_hike"], ctx["fw_ease"])
        if ctx["fw_delta_1w"] is not None:
            d = ctx["fw_delta_1w"]
            arrow = "↑" if d > 0.05 else ("↓" if d < -0.05 else "→")
            fw += "（加息概率 %s，一周%s%.1fpp）" % (
                "回升" if d > 0.05 else ("回落" if d < -0.05 else "持平"), arrow, abs(d))
        parts.append(fw)
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
    fw = ""
    if ctx["fw_meeting"]:
        fw = ("<div class='fed-row'><b>市场预期（CME FedWatch）</b>"
              "维持 <b>%.1f%%</b> · 加息25bp <b>%.1f%%</b> · 降息 <b>%.1f%%</b>"
              % (ctx["fw_hold"], ctx["fw_hike"], ctx["fw_ease"]))
        if ctx["fw_delta_1w"] is not None:
            d = ctx["fw_delta_1w"]
            color = "#7ee787" if d < -0.05 else ("#f85149" if d > 0.05 else "#d29922")
            fw += ("<span class='tag tag-zone' style='background:%s'>加息概率"
                   "%s（一周%s %.1fpp）</span>"
                   % (color, "回升" if d > 0.05 else ("回落" if d < -0.05 else "持平"),
                      "↑" if d > 0.05 else ("↓" if d < -0.05 else "→"), abs(d)))
        fw += "</div>"
    return (
        "<div class='fed-card'>"
        "<div class='fed-row'><b>美联储政策环境</b>"
        "<span class='tag tag-zone' style='background:#8b0000'>%s</span></div>"
        "<div class='fed-row'>目标利率区间 <b>%s</b> · 最近决议：%s</div>"
        "<div class='fed-row fed-muted'>%s</div>"
        "%s"
        "<div class='fed-row'>%s %s %s</div>"
        "<div class='fed-row fed-tone'>%s</div>"
        "</div>"
    ) % (ctx["stance"], ctx["range_txt"], ctx["last_decision_txt"],
         ctx["outlook_txt"], fw, ev, mt, mn, ctx["sentiment_tone"])
