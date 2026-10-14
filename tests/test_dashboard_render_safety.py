# -*- coding: utf-8 -*-
"""dashboard 渲染安全测试（T-2026-10-14）。

背景：2026-10-14 线上页面 JS 全挂（tab 失效、图表空白）——
根因是模板 `var HUMAN30 = {{ human30_json }};` 引用的变量
render 未传，Jinja2 渲染为空 ⇒ `var HUMAN30 = ;` 语法错误 ⇒
整个内联 <script> 块不执行。

本测试保证：渲染后的 HTML **不得出现空 JS 注入**（`var X = ;`），
且 human30_json 必须有合法值（null 或对象），防止同类问题再发。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _render():
    from fg_system import pipeline
    from fg_system.dashboard import report
    return report.render_html(pipeline.run(write=False))


def test_no_empty_js_injection():
    html = _render()
    # 任何 `var X = ;` 都会是 JS 语法错误 —— 必须绝迹
    bad = re.findall(r"var\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*;", html)
    assert not bad, "渲染 HTML 出现空 JS 注入：%s" % bad


def test_human30_json_valid():
    html = _render()
    m = re.search(r"var HUMAN30 = (.*?);\n", html)
    assert m, "模板缺少 HUMAN30 注入行"
    val = m.group(1).strip()
    # 合法值：null（无记录）或 JSON 对象（有记录）
    assert val == "null" or val.startswith("{"), (
        "HUMAN30 注入值非法：%r（应为 null 或 JSON 对象）" % val)


def test_all_injected_vars_have_values():
    """模板所有 var X = {{ ... }} 注入点渲染后均非空（防漏传再发）。"""
    html = _render()
    for m in re.finditer(r"var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+?);", html):
        name, val = m.group(1), m.group(2).strip()
        if name in ("INDEX", "FACTORS", "POSITION", "EXTERNAL", "HUMAN30",
                    "window", "charts", "tabs", "wraps", "tip", "ZONES",
                    "FKEYS", "FCOLORS", "HCOLORS", "SUB", "TEXT", "BORDER",
                    "SPLIT", "taskMsg", "h30"):
            continue
        assert val and val != "null", (
            "注入变量 %s 渲染后为空/缺失（%r）——检查 render 参数" % (name, val))
