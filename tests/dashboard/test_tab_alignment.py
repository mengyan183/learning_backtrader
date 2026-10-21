# -*- coding: utf-8 -*-
"""看板 tab 与区块的对齐约束（2026-10-21 修 tab 白屏/不可达）。

历史缺陷（两次）：
1. 2026-10-20：加了 `sec-wrap`「标的查询」却**没加 tab** ✗ ⇒ 按索引切换错位
   （点「任务」显示「标的查询」✗）；
2. 2026-10-21：改成按 `data-name` 匹配 ✓ 后，「标的查询」**永远点不到** ✗，
   且「市场」tab 没有同名区块 ✗ ⇒ 点它**白屏** ✗。

本文件锁两条约束 ✓：
- 每个 `sec-wrap` 都必须有**同名 tab** ✓（否则该区块不可达 ✗）；
- 除「市场」（概览，特判显示全部 ✓）外，tab 必须能匹配到区块 ✓。
"""
import os
import re

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))),
    "fg_system", "dashboard", "templates", "index.html")

TAB_RE = re.compile(r'<button class="tab-btn[^"]*"[^>]*>([^<]+)</button>')
SEC_RE = re.compile(r'<div class="sec-wrap" data-name="([^"]+)"')

#: 没有同名区块、按「概览」特判显示全部的 tab ✓
OVERVIEW_TABS = {"市场"}


def _html():
    return open(TEMPLATE, encoding="utf-8").read()


def test_every_section_has_a_tab():
    """每个区块都要有同名 tab ✓ —— 否则用户**永远点不到** ✗。"""
    t = _html()
    tabs = {x.strip() for x in TAB_RE.findall(t)}
    secs = [x.strip() for x in SEC_RE.findall(t)]
    missing = [s for s in secs if s not in tabs]
    assert not missing, "以下区块没有 tab，用户点不到 ✗：%s" % missing


def test_every_tab_resolves_to_section_or_overview():
    """每个 tab 要么有同名区块 ✓，要么属于概览特判 ✓（否则点了白屏 ✗）。"""
    t = _html()
    tabs = [x.strip() for x in TAB_RE.findall(t)]
    secs = {x.strip() for x in SEC_RE.findall(t)}
    dead = [x for x in tabs if x not in secs and x not in OVERVIEW_TABS]
    assert not dead, "以下 tab 点了会白屏 ✗：%s" % dead


def test_overview_tab_is_special_cased_in_js():
    """「市场」必须真的在 JS 里被特判 ✓ —— 否则它依旧白屏 ✗。"""
    t = _html()
    assert 'targetName === "市场"' in t
    assert "showAll" in t


def test_query_section_is_reachable():
    """「标的查询」区块必须有 tab ✓（2026-10-21 它就是缺 tab ✗）。"""
    t = _html()
    assert 'data-name="标的查询"' in t
    tabs = {x.strip() for x in TAB_RE.findall(t)}
    assert "标的查询" in tabs
