# -*- coding: utf-8 -*-
"""看板导航与区块的对齐约束。

历史缺陷（三次）：
1. 2026-10-20：加了 `sec-wrap`「标的查询」却**没加 tab** ✗ ⇒ 按索引切换错位 ✗；
2. 2026-10-21：改成按 `data-name` 匹配 ✓ 后「标的查询」**永远点不到** ✗，
   且「市场」没有同名区块 ✗ ⇒ 点它**白屏** ✗；
3. 2026-10-27：「市场」的兜底 `showAll` 没删 ✗ ⇒ 首页往下滑能看到
   **其它 tab 的内容** ✗ ⇒ 改成「4 主 tab + 更多面板」✓ 并删掉兜底 ✓。

本文件锁三条约束 ✓：
- 每个 `sec-wrap` 都必须**可达** ✓（有同名 tab，或在「更多」面板里 ✓）；
- 每个 tab 要么有同名区块 ✓，要么是只负责弹面板的「更多」✓；
- 「市场」**不再**特判显示全部 ✓。
"""
import os
import re

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))),
    "fg_system", "dashboard", "templates", "index.html")

TAB_RE = re.compile(r'<button class="tab-btn[^"]*"[^>]*>([^<]+)</button>')
ITEM_RE = re.compile(r'<button class="sheet-item" data-name="([^"]+)">')
# 注意：初始可见的区块是 `class="sec-wrap on"` ✓ ⇒ 必须允许额外 class ✗
SEC_RE = re.compile(r'<div class="sec-wrap[^"]*" data-name="([^"]+)"')

#: 只负责弹「更多」面板、本身没有同名区块的 tab ✓
SHEET_TABS = {"更多"}


def _html():
    return open(TEMPLATE, encoding="utf-8").read()


def test_every_section_is_reachable():
    """每个区块都要能到达 ✓ —— 有同名 tab，或在「更多」面板里 ✗ 否则点不到 ✗。"""
    t = _html()
    reach = ({x.strip() for x in TAB_RE.findall(t)}
             | set(ITEM_RE.findall(t)))
    secs = [x.strip() for x in SEC_RE.findall(t)]
    missing = [s for s in secs if s not in reach]
    assert not missing, "以下区块既无 tab 也不在「更多」面板 ✗：%s" % missing


def test_every_tab_resolves_to_section_or_sheet():
    """每个 tab 要么有同名区块 ✓，要么是「更多」✓（否则点了白屏 ✗）。"""
    t = _html()
    tabs = [x.strip() for x in TAB_RE.findall(t)]
    secs = {x.strip() for x in SEC_RE.findall(t)}
    dead = [x for x in tabs if x not in secs and x not in SHEET_TABS]
    assert not dead, "以下 tab 点了会白屏 ✗：%s" % dead


def test_market_tab_no_longer_shows_all():
    """🔴 「市场」必须只显示自己 ✓。

    旧兜底 `showAll` 让首页显示**全部**区块 ✗ ⇒ 往下滑能看到其它 tab 的内容 ✗。
    断言用代码模式（`var showAll` / `showAll ||`）而非裸词 ✓ ——
    注释里提到这个名字是正常的 ✓。
    """
    t = _html()
    assert 'data-name="市场"' in t
    assert "var showAll" not in t, "showAll 变量残留 ⇒ 首页会显示全部区块 ✗"
    assert "showAll ||" not in t, "showAll 分支残留 ⇒ 首页会显示全部区块 ✗"


def test_sheet_items_match_sections():
    """「更多」面板的每一项都必须能匹配到区块 ✓（否则点了白屏 ✗）。"""
    t = _html()
    items = set(ITEM_RE.findall(t))
    secs = {x.strip() for x in SEC_RE.findall(t)}
    assert items, "「更多」面板没有任何项 ✗"
    dead = sorted(items - secs)
    assert not dead, "以下面板项无对应区块 ✗：%s" % dead


def test_query_section_is_reachable():
    """「标的查询」必须可达 ✓ —— 经 tab 或经「更多」面板都算 ✓。"""
    t = _html()
    assert 'data-name="标的查询"' in t
    reach = ({x.strip() for x in TAB_RE.findall(t)}
             | set(ITEM_RE.findall(t)))
    assert "标的查询" in reach
