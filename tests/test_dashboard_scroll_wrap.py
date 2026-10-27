# -*- coding: utf-8 -*-
"""`report._wrap_scroll` + 模板注释字面标签检查（2026-10-27）。

🔴 两次事故的护栏：

1. **script 块**里 JS 动态拼接的 table 标记被包上滚动容器 ⇒
   双引号撞破外层 JS 字符串 ⇒ `SyntaxError` ⇒ 整段脚本失效 ✗
   （表现：图表/档位带不渲染、底部 tab 点不动 ✗）
2. **HTML 注释**里的举例被包 / 被计数 ⇒ 干扰「标签配对」断言 ✗
"""
import importlib.util
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(REPO, "fg_system", "dashboard", "templates", "index.html")


def _load():
    spec = importlib.util.spec_from_file_location(
        "dash_report",
        os.path.join(REPO, "fg_system", "dashboard", "report.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rp = _load()


# ---------------------------------------------------------------- 包裹行为
def test_static_table_wrapped():
    out = rp._wrap_scroll('<table class="card"><tr><td>x</td></tr></table>')
    assert out == ('<div class="scroll"><table class="card">'
                   '<tr><td>x</td></tr></table></div>')


def test_single_quoted_table_wrapped():
    """JS 里常见单引号写法，静态 HTML 也要能包 ✓。"""
    out = rp._wrap_scroll("<table class='card'><tr></tr></table>")
    assert out.startswith('<div class="scroll">')
    assert out.endswith("</div>")


def test_non_card_table_not_wrapped():
    out = rp._wrap_scroll('<table class="other"><tr></tr></table>')
    assert out == '<table class="other"><tr></tr></table>'


# ---------------------------------------------------------------- 受保护区
def test_script_block_untouched():
    """🔴 核心：script 块**原样返回** ✗（包了就是 SyntaxError ✗）。"""
    src = '<script>var s = "<table class=\'card\'>";</script>'
    assert rp._wrap_scroll(src) == src


def test_style_block_untouched():
    src = '<style>/* <table class="card"> */</style>'
    assert rp._wrap_scroll(src) == src


def test_comment_untouched():
    src = '<!-- <table class="card"><tr></tr></table> -->'
    assert rp._wrap_scroll(src) == src


def test_pre_block_untouched():
    src = '<pre><table class="card"><tr></tr></table></pre>'
    assert rp._wrap_scroll(src) == src


def test_textarea_block_untouched():
    src = '<textarea><table class="card"><tr></tr></table></textarea>'
    assert rp._wrap_scroll(src) == src


def test_mixed_only_static_wrapped():
    """混合输入：保护区里的 2 处不动 ✓，只有静态的 1 处被包 ✓。"""
    html = ('<!-- <table class="card"></table> -->'
            '<script>var s = "<table class=\'card\'>";</script>'
            '<table class="card"><tr><td>real</td></tr></table>')
    out = rp._wrap_scroll(html)
    assert out.count('<div class="scroll">') == 1
    assert '<div class="scroll"><table class="card"><tr><td>real' in out


# ---------------------------------------------------------------- 模板约束
def test_no_tag_literals_inside_html_comments():
    """🔴 模板 HTML 注释里**不得**出现字面标签 ✗。

    为什么：注释内容同样会被正则 / 标签计数扫描到 ✗ ——
    字面 script 标签曾撞坏「script 配对」断言 ✗，
    字面 table 标签会被 scroll 正则误包 ✗。
    本测试是为了**不靠记性** ✓：一写就红 ✓。
    """
    html = open(TEMPLATE, encoding="utf-8").read()
    bad = []
    for m in re.finditer(r"<!--.*?-->", html, re.S):
        if re.search(r"<[a-zA-Z/]", m.group(0)):
            bad.append(m.group(0)[:80].replace("\n", " "))
    assert not bad, "注释里有字面标签：%s" % bad
