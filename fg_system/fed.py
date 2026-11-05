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


#: `fedwatch.csv` 超过这么多天就认为**过期** ✗ 改用 Kalshi 兜底 ✓
#: 为什么 5 天：FOMC 预期是**低频但要求准确**的 ✗
#:   一个会议周期的预期变化很大 ✗ 5 天前的数字已无参考价值 ✗
_FEDWATCH_MAX_LAG_DAYS = 5


def _load_fedwatch():
    """读 CME FedWatch 市场预期 CSV（`scripts/fetch_fedwatch.py` 产出）。
    返回最新一行 dict；无数据返回 None。

    🔴 2026-11-03：**加了 Kalshi 兜底** ✓
       背景：`fetch_fedwatch.py` 拿不到 CME 会话就 `sys.exit(2)` ✗
             ⇒ `fedwatch.csv` 停在 2026-10-13（21 天 ✗）
             ⇒ 本函数返回 `None` ⇒ `fw_*` 全 `None` ⇒ **`fed` 因子静默降级** ✗
             而**没有任何告警** ✗

       为什么 Kalshi 能兜：`kalshi_fed.csv`（`fetch_kalshi_fed.py` 产出 ✓ 在跑 ✓）
         字段几乎一一对应：
           `fedwatch.csv`: meeting / hold_pct / hike_pct / ease_pct
           `kalshi_fed.csv`: meeting / hold / hike / ease
         ⚠️ **语义不同** ✗ —— Kalshi 是**市场交易价格**（0~100 的概率）
            CME 是**期货隐含概率** ✗ 两者都表示「加息概率」✓ 方向一致 ✓
            但**数值不严格可比** ✗ ⇒ 兜底时打一条标注 ✓
         ⚠️ `wk_hike_pct`（一周前）和 `m_hike_pct`（下一档会议）Kalshi 没有 ✗
            ⇒ 这两项保持 `None` ✓（`fw_delta_1w` / `fw_curve` 会缺失 ✓）
    """
    p = os.path.join(config.RAW_DIR, "fedwatch.csv")
    try:
        df = pd.read_csv(p)
        if not df.empty:
            # 🔴 2026-11-04 **关键修复**：**文件存在 ≠ 数据新鲜** ✗
            #    实测：`fedwatch.csv` 停在 2026-10-13（22 天 ✗）
            #    而简报照常显示「市场预期（CME FedWatch 2026-10-13）」
            #    ⇒ 用户看到的「美联储动态」是 **22 天前** 的 ✗
            #    原因：原实现只要文件非空就 `return` ✗ 根本走不到 Kalshi 兜底 ✗
            #    ⇒ 加**新鲜度判断** ✓ 太旧就走兜底 ✓
            row = df.iloc[-1].to_dict()
            d = str(row.get("date") or row.get("fw_date") or "")[:10]
            fresh = True
            if d:
                try:
                    lag = (dt.date.today()
                           - dt.date.fromisoformat(d)).days
                    fresh = lag <= _FEDWATCH_MAX_LAG_DAYS
                    if not fresh:
                        print("[fed] ⚠️ fedwatch.csv 停在 %s（%d 天）⇒ "
                              "改用 Kalshi 兜底 ✓" % (d, lag))
                except ValueError:
                    pass
            if fresh:
                return row
    except (FileNotFoundError, pd.errors.EmptyDataError):
        pass

    # ---- 兜底：Kalshi ✓ ----
    kp = os.path.join(config.RAW_DIR, "kalshi_fed.csv")
    try:
        kdf = pd.read_csv(kp)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return None
    if kdf.empty:
        return None
    row = kdf.iloc[-1].to_dict()

    def _pick(*keys):
        """按顺序取第一个**非空**的键 ✓（兼容 `ease` / `ease_pct` 两种列名 ✗）。

        🔴 2026-11-04 踩坑：实际列名是 **`ease_pct` / `hold_pct` / `hike_pct`** ✗
           而我第一版写的是 `row.get("ease")` ✗ ⇒ 三个概率全是 `None` ✗
           ⇒ 简报里「市场预期」一栏会变成空白 ✗（比显示旧数据更糟 ✗）
        """
        for k in keys:
            v = row.get(k)
            if v is not None and pd.notna(v):
                return v
        return None

    return {
        # 🔴 2026-11-05 补：**必须有 `date`** ✗
        #    实测简报显示「市场预期（CME FedWatch **None**）」
        #    ⇒ `fed_brief_text` 用的是 `ctx["fw_date"]` ✗
        #      而本兜底 dict **没返回 `date`** ✗ ⇒ `None` ✗
        #    ⚠️ 注意：这里的 `date` 是 **kalshi_fed.csv 的抓取日** ✗
        #       不是 CME 的日期 ✓ 所以显示时要带来源标注 ✓
        "date": _pick("date"),
        "meeting": _pick("meeting"),
        # 字段名统一成 `fedwatch.csv` 的写法 ✓ 上层 `fed_context` 不用改 ✓
        "ease_pct": _pick("ease_pct", "ease"),
        "hold_pct": _pick("hold_pct", "hold"),
        "hike_pct": _pick("hike_pct", "hike"),
        # Kalshi 没有的两项 ✗ ⇒ 显式 None ✓（上层会算成 None ✓ 不会崩 ✓）
        "wk_hike_pct": None,
        "m_hike_pct": None,
        "_source": "kalshi_fed.csv（CME FedWatch 兜底 ✗ 语义为市场交易价 ✗）",
    }


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
        "fw_delta_1w": None, "fw_curve": None, "fw_migrate": None, "fw_date": None,
        # 🔴 2026-11-05：**数据来源** ✓（`fedwatch.csv` 还是 `kalshi_fed.csv` ✗）
        "fw_source": None,
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
            # 🔴 2026-11-05 **关键修复**：`wk == wk` 只能挡 `NaN` ✗
            #    而 Kalshi 兜底返回的是 **`None`** ✗
            #    `None == None` ⇒ **True** ✗ ⇒ `float(None)` 抛 TypeError ✗
            #    ⇒ **整个 try 块跳到 except** ✗
            #    ⇒ 后面的 `fw_date` / `fw_source` **全没赋值** ✗
            #    ⇒ 症状：简报显示「市场预期（CME FedWatch **None**）」
            #    ⇒ 必须显式判 `is not None` ✓
            ctx["fw_delta_1w"] = (
                ctx["fw_hike"] - float(wk)
                if (wk is not None and wk == wk) else None)
            # P-FW（2026-10-13，诺奖预期管理先验）：预期路径斜率 = 近端 vs
            # 远端（m_hike_pct，下一档会议）加息预期差；显著陡峭 → 预期路径
            # 迁移标记（|Δ1w|≥10pp 短期迁移 / |Δm|≥15pp 中期路径陡峭）。
            _m = fw.get("m_hike_pct")
            if _m is not None and _m == _m:
                ctx["fw_curve"] = (ctx["fw_hike"] - float(_m))
                _d1 = ctx["fw_delta_1w"]
                _dc = ctx["fw_curve"]
                if _d1 is not None and abs(_d1) >= 10.0:
                    ctx["fw_migrate"] = ("⚠️ 预期显著迁移：加息概率一周%s %.0fpp"
                                         % ("回升" if _d1 > 0 else "回落", abs(_d1)))
                elif abs(_dc) >= 15.0:
                    ctx["fw_migrate"] = ("⚠️ 预期路径陡峭：近端 vs 远端加息预期差"
                                         " %.0fpp（市场押注路径方向）" % abs(_dc))
            ctx["fw_date"] = str(fw.get("date") or "")
            # 🔴 2026-11-05：透传来源 ✓ 供 `fed_brief_text` 标注 ✗
            ctx["fw_source"] = fw.get("_source") or "fedwatch.csv"
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
        # 🔴 2026-11-05：**标注数据来源** ✓
        #    原来硬写「CME FedWatch」✗ 但实际可能是 Kalshi 兜底 ✗
        #    ⇒ 用户看到「CME FedWatch」会以为 CME 是好的 ✗ 误导 ✗
        _src = ctx.get("fw_source") or ""
        _tag = (" · **Kalshi 兜底** ✗" if "kalshi" in str(_src).lower()
                else "")
        fw = ("市场预期（CME FedWatch %s%s）："
              "维持 %.1f%% / 加息25bp %.1f%% / 降息 %.1f%%")
        fw = fw % (ctx["fw_date"] or "?", _tag,
                   ctx["fw_hold"], ctx["fw_hike"], ctx["fw_ease"])
        if ctx["fw_delta_1w"] is not None:
            d = ctx["fw_delta_1w"]
            arrow = "↑" if d > 0.05 else ("↓" if d < -0.05 else "→")
            fw += "（加息概率 %s，一周%s%.1fpp）" % (
                "回升" if d > 0.05 else ("回落" if d < -0.05 else "持平"), arrow, abs(d))
        if ctx["fw_migrate"]:
            fw += "；" + ctx["fw_migrate"]
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
        if ctx["fw_migrate"]:
            fw += "<span class='tag tag-zone' style='background:#8250df'>%s</span>" \
                % ctx["fw_migrate"]
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
