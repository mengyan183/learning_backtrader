# -*- coding: utf-8 -*-
"""美联储「前瞻文案」必须是**动态**的（2026-11-09 用户实测）。

🔴 症状：简报一直写「**10月预计维持**」✗ —— 10-28 的会议早开完了 ✗
   根因：`config.FED_OUTLOOK_TXT` 是**冻结字符串** ✗
   修法：`fed.py` 按「下次会议 + FedWatch 隐含概率」动态生成 ✓

⚠️ 第二个坑：FedWatch 可能指向**已开完**的会议（本地 `fedwatch.csv` 停在
   2026-10-13、会议 2026-10-28 ✗）⇒ 把它的 78% 挂到 12 月头上就是**假数据** ✗
   ⇒ 只在「同月」时才用概率 ✓
"""
import datetime as dt
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def _ctx(monkeypatch, fw_meeting, today=dt.date(2026, 11, 9)):
    from fg_system import config, fed

    monkeypatch.setattr(config, "FOMC_MEETINGS_2026",
                        [("2026-10-27", "2026-10-28"),
                         ("2026-12-08", "2026-12-09")])
    monkeypatch.setattr(config, "FOMC_MINUTES_2026", [])
    monkeypatch.setattr(config, "MACRO_EVENTS_2026", [])
    monkeypatch.setattr(fed, "_load_fedwatch", lambda: {
        "meeting": fw_meeting, "hold_pct": 22.0,
        "hike_pct": 78.0, "ease_pct": 0.0})
    return fed.fed_context(today=today)


def test_outlook_never_says_a_past_month_is_expected(monkeypatch):
    """10 月已过 ⇒ 文案里不得再出现「10月预计」."""
    ctx = _ctx(monkeypatch, "2026-12-09")
    assert "10月预计" not in ctx["outlook_txt"]
    assert ctx["outlook_txt"].startswith("12月")


def test_outlook_ignores_probabilities_of_a_past_meeting(monkeypatch):
    """FedWatch 指向已开完的会议 ⇒ 概率不得挂到下次会议头上."""
    ctx = _ctx(monkeypatch, "2026-10-28")
    assert "待定" in ctx["outlook_txt"]
    assert "78" not in ctx["outlook_txt"]


def test_outlook_uses_probabilities_when_meeting_matches(monkeypatch):
    """同月（开始日 12-08 / 结束日 12-09）⇒ 采用概率 ✓."""
    ctx = _ctx(monkeypatch, "2026-12-09")
    assert "12月预计加息" in ctx["outlook_txt"]
    assert "78%" in ctx["outlook_txt"]


def test_last_decision_advanced_past_september(monkeypatch):
    """决议日必须已推进到 10 月会议（原来停在 2026-09-16 ✗）."""
    from fg_system import config
    assert config.FED_LAST_DECISION >= "2026-10-28"


def test_kalshi_fallback_source_is_marked_frozen():
    """Kalshi 兜底的 `_source` 必须带**停更标记 + 数据天数** ✓（2026-11-26）。

    🔴 为什么必须标 ✗：
       `fetch_kalshi_fed.py` 已从每日链移除（`external-api.kalshi.com`
       经 ClashX 仍 `Connection reset`，`proxy_probe.py` 实测是节点屏蔽）✗
       ⇒ `kalshi_fed.csv` **永久停在 2026-11-26 之前** ✗
       ⇒ 若 `fedwatch.csv` 哪天断了，`fed.py` 会静默回退到这份**冻结数据**，
         而简报不会说「这是旧的」✗
       ⇒ 所以 `_source` 必须自证：停更日 + 数据距今多少天 ✓
    """
    from fg_system import fed

    # ① 有日期 ⇒ 带「已停更」+「N 天前」
    s = fed._kalshi_src({"date": "2026-11-25"})
    assert "已停更" in s, s
    assert fed.KALSHI_FROZEN_SINCE in s, s
    assert "2026-11-25" in s, s
    assert "天前" in s, s

    # ② 无日期 / 空 dict ⇒ 只带停更标记，不崩
    for row in ({"date": None}, {}):
        s2 = fed._kalshi_src(row)
        assert "已停更" in s2, s2
        assert "天前" not in s2, "无日期时不该编造天数 ✗"

    # ③ 停更日是 2026-11-26（改动它要同步改注释与 plist）
    assert fed.KALSHI_FROZEN_SINCE == "2026-11-26"
