# -*- coding: utf-8 -*-
"""存量仓 1 年过渡期（交易纪律第 4.6 条，2026-11-09 用户裁定）。

🔴 为什么需要：现持仓建于贪恐系统之前 ✗ 用 `1% 风险 / 2×ATR` 去卡会得出
   「AXTX 318→151」这类无交易意义的数字，且全部减完只剩 **31.7%** ✗
   与「目标仓位 58.3%」直接矛盾 ✗

⇒ 过渡期内名单内标的：**跳过引擎 A**（1% 硬上限），只按贪恐系数定方向 ✓
⚠️ 加仓侧**不变**（已超上限仍冻结）✓
"""
import datetime as dt
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import invest_research as ir  # noqa: E402

LEGACY = "YINN"
NORMAL = "SOXL"


def _snap(sym=LEGACY, mv=4140.0, lim=1159.0, over=True,
          pnl=-1.68, sys_fg=55.8, shoutu=-44.0):
    return {
        "positions": [{"symbol": sym, "mv": mv, "risk_limit": lim,
                       "risk_over": over, "pnl_pct": pnl,
                       "sys_fg": sys_fg, "sys_fg_note": "个股级"}],
        "shoutu": {sym.replace("-USDT", ""): shoutu},
        "accounts": {"stock": 10432.2},
    }


def test_is_legacy_true_within_transition():
    """过渡期内（≤ 2026-11-19）名单内标的仍算存量仓 ✓（历史口径不变）。

    🔴 2026-11-20（第 12.50 条，用户裁定）：**过渡期提前结束** ✗
       原定 2027-11-09，现改为 2026-11-19 ⇒ 2027-11-09 不再是「期内」✗
    """
    assert ir._is_legacy(LEGACY, dt.date(2026, 11, 9)) is True
    assert ir._is_legacy(LEGACY, dt.date(2026, 11, 19)) is True


def test_is_legacy_false_after_transition():
    """过渡期结束后自动恢复 1% 规则（按日期判断，不改代码）✓。

    🔴 2026-11-20 起（第 12.50 条）：2026-11-20 当天就已结束 ✗
    """
    assert ir._is_legacy(LEGACY, dt.date(2026, 11, 20)) is False
    assert ir._is_legacy(LEGACY, dt.date(2027, 11, 10)) is False


def test_is_legacy_false_for_new_positions():
    """名单冻结：过渡期内新开的仓位不进名单 ✓."""
    assert ir._is_legacy(NORMAL, dt.date(2026, 11, 9)) is False


def test_legacy_skips_hard_cap_reduction(monkeypatch):
    """名单内 + 超上限 ⇒ **不产生「减仓至上限」**，只按系数定方向."""
    monkeypatch.setattr(ir, "_is_legacy", lambda s, t=None: s == LEGACY)
    txt = ir.action_brief_text(_snap())
    assert "减仓至上限" not in txt
    # ⚠️ 2026-11-20：原断言 `"存量仓过渡期" in txt` **早已失效** ✗
    #    2026-11-16 加了「全部无减仓触发 ⇒ 折叠成一行」后，逐标的动作不再输出
    #    ⇒ 这句断言在 HEAD 上就是红的（已在干净 worktree 复核）✗
    #    改成断言**意图**：不产生硬上限减仓 + 明确告知加仓仍冻结 ✓
    assert "无减仓触发" in txt
    assert "加仓仍冻结" in txt
    assert "持有观望" in txt          # 系数 -44 中性 ⇒ 观望


def test_legacy_still_reduces_when_coefficient_is_greedy(monkeypatch):
    """过渡期内**系数贪婪**仍要减仓 ✓（豁免的是硬上限，不是方向信号）."""
    monkeypatch.setattr(ir, "_is_legacy", lambda s, t=None: s == LEGACY)
    txt = ir.action_brief_text(_snap(sys_fg=72.0, shoutu=70.0))
    assert "减仓（系数贪婪" in txt


def test_legacy_never_suggests_adding(monkeypatch):
    """过渡期内**不得出现「可加」** ✓（第 4.6.6 条：加仓侧不变）。

    🔴 2026-11-09 实测事故：16:41 的简报对 CRCG(-60%)/AXTX(-93%) 写
       「持有/可加（恐慌买入区）」，而同页「建仓/加仓计划」写「禁止加仓」✗
       —— 因为原实现把「敞口合规」这个前提丢了（存量仓恰恰超 250%）。
    """
    monkeypatch.setattr(ir, "_is_legacy", lambda s, t=None: s == LEGACY)
    txt = ir.action_brief_text(_snap(shoutu=-95.0))      # 恐慌买入区
    assert "可加" not in txt, "存量仓不得出现「可加」（敞口超标，加仓仍冻结）"
    assert "加仓仍冻结" in txt


def test_non_legacy_still_uses_hard_cap(monkeypatch):
    """名单外标的照旧：超上限 ⇒ 减仓至上限 ✓（规则没被整体放宽）."""
    monkeypatch.setattr(ir, "_is_legacy", lambda s, t=None: False)
    txt = ir.action_brief_text(_snap(sym=NORMAL))
    assert "减仓至上限" in txt


def test_risk_summary_excludes_legacy(monkeypatch):
    """汇总不得再写「N/N 个标的超出 1% 风险上限」（与减仓节自相矛盾）."""
    monkeypatch.setattr(ir, "_is_legacy", lambda s, t=None: s == LEGACY)
    txt = ir.risk_brief_text(_snap())
    assert "个标的超出 1% 风险上限" not in txt
    assert "不适用 1% 硬上限" in txt


def test_risk_summary_keeps_non_legacy(monkeypatch):
    monkeypatch.setattr(ir, "_is_legacy", lambda s, t=None: False)
    txt = ir.risk_brief_text(_snap(sym=NORMAL))
    assert "个标的超出 1% 风险上限" in txt
