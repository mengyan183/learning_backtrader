# -*- coding: utf-8 -*-
"""仪表盘生成测试（§12）。"""
import os

import pandas as pd
import pytest

from fg_system.dashboard import report


def test_build_html_contains_all_blocks(tmp_path):
    idx = pd.date_range("2023-01-01", periods=300, freq="B")
    features = pd.DataFrame({
        "fg_index": 50.0, "zone": 2, "core_position": 0.35, "ammo_position": 0.10,
        "target_position": 0.45, "vix": 50.0, "term": 50.0, "price": 50.0, "breadth": 50.0,
        "circuit_breaker": False,
    }, index=idx)
    path = tmp_path / "report.html"
    report.build(features, str(path), title="测试仪表盘")
    html = path.read_text(encoding="utf-8")
    assert "<title>测试仪表盘</title>" in html or "贪婪恐惧指数" in html
    assert "损耗" in html          # 第 7 区块
    assert len(html) > 5000


def test_build_html_without_external_index(tmp_path):
    """外部指数缺失时不影响生成（§15.3）。"""
    idx = pd.date_range("2023-01-01", periods=100, freq="B")
    features = pd.DataFrame({"fg_index": 50.0, "zone": 2, "target_position": 0.4},
                            index=idx)
    path = tmp_path / "r.html"
    report.build(features, str(path))
    assert os.path.exists(path)


# ================================================================ 手机端适配
# 用户需求（2026-09-23）：**支持在手机上打开**，每次打开/刷新时主动重新计算，
# 不需要手机后台常驻。以下测试锁住"能在手机上正常看"的几个硬条件。

def _feat(n=300):
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "fg_index": 50.0, "zone": 2, "core_position": 0.35, "ammo_position": 0.10,
        "target_position": 0.45, "vix": 50.0, "term": 50.0, "price": 50.0,
        "breadth": 50.0, "circuit_breaker": False,
    }, index=idx)


def _render(tmp_path):
    return report.render_html(_feat(), prices_path=str(tmp_path / "no_prices.csv"))


def test_render_html_returns_string_and_writes_nothing(tmp_path):
    """**新接口**：`render_html` 只返回字符串，**不落盘**。

    服务端每次请求都要拿一份新鲜 HTML，若它必须写文件会引入并发写盘问题。
    """
    html = _render(tmp_path)
    assert isinstance(html, str) and html.startswith("<!DOCTYPE html")
    assert list(tmp_path.iterdir()) == [], "render_html 不得写任何文件"


def test_build_still_writes_file(tmp_path):
    """`build` 的对外行为不变（仍落盘并返回路径）。"""
    path = tmp_path / "d.html"
    out = report.build(_feat(), str(path),
                       prices_path=str(tmp_path / "no_prices.csv"))
    assert out == str(path) and path.exists()


def test_html_has_viewport_meta(tmp_path):
    """**守卫**：必须有 viewport —— 否则手机按 980px 桌面宽度渲染再整体缩小，
    字**小到看不清**。这是"能在手机上打开"的第一硬条件。
    """
    html = _render(tmp_path)
    assert 'name="viewport"' in html
    assert "width=device-width" in html


def test_html_uses_only_local_static_assets(tmp_path):
    """**守卫**：不得引用任何外部网络资源（CDN / 字体 / 脚本）。

    手机通过局域网访问时可能没有外网，外部资源会加载失败导致样式全丢；
    Flask 迁移后静态资源走本地 `/static/`（服务器自身提供，离线可用），
    因此**允许** `<script src="/static/...">` / `<link href="/static/...">`，
    但**禁止**任何指向外站的 src/href，也禁止 CDN。
    SVG 命名空间 `www.w3.org` 是 XML 标识符，**不是网络请求**，需排除。
    """
    import re
    html = _render(tmp_path)
    body = re.sub(r"https?://www\.w3\.org/[^\s\"'<>]*", "", html)
    assert "http://" not in body, "存在外部 http 引用"
    assert "https://" not in body, "存在外部 https 引用"
    for m in re.finditer(r"""(?:src|href)=["']([^"']+)["']""", html):
        url = m.group(1)
        if url.startswith(("http://", "https://", "//")):
            raise AssertionError("存在外部资源引用: %s" % url)
        if ("<script" in html[:m.start()][-30:] or "stylesheet" in html[:m.start()][-50:]):
            assert url.startswith("/static/"), "静态资源必须指向本地 /static/: %s" % url


def test_html_tables_are_horizontally_scrollable(tmp_path):
    """**守卫**：每个表格都要套横向滚动容器 —— 否则宽表在窄屏上溢出、
    把整页撑宽，用户得左右拖整页才能看全。
    """
    html = _render(tmp_path)
    n_scroll = html.count('<div class="scroll">')
    n_table = html.count("<table class=")
    assert n_table > 0, "没有表格？测试数据变了"
    assert n_scroll == n_table, "有表格没被滚动容器包住（%d 表 / %d 容器）" % (
        n_table, n_scroll)


def test_html_has_mobile_breakpoint(tmp_path):
    """**守卫**：必须有窄屏断点，且窄屏下收紧边距（24px 在手机上太浪费）。

    Flask 迁移后样式在独立 `static/style.css`（模板以 <link> 引用），
    因此断言模板引用了 /static/style.css 且该文件内含 @media 断点。
    """
    html = _render(tmp_path)
    # 允许带 cache-buster 版本参数（`/static/style.css?v=…`），前缀匹配即可
    assert 'href="/static/style.css' in html
    css_path = os.path.join(os.path.dirname(report.__file__),
                            "static", "style.css")
    css = open(css_path, encoding="utf-8").read()
    assert "@media" in css
    assert "max-width:600px" in css.replace(" ", "")


def test_all_tables_wrapped_with_price_data(tmp_path):
    """**回归**：有价格数据时第 5/6/7 区块也会渲染表格，必须同样被包住。

    上面的测试用**不存在的** prices 路径，会让这些区块降级、不出表格，
    因此覆盖不到它们。此测试补上这一缺口（用真实数据实测为 5 表 / 5 容器）。
    """
    idx = pd.date_range("2023-01-01", periods=300, freq="B")
    rows = [{"date": d, "symbol": s, "open": 100.0, "high": 101.0, "low": 99.0,
             "close": 100.0, "volume": 1000000.0}
            for s in ("TQQQ", "SOXL", "UPRO", "QQQ", "SOXX", "SMH", "SPY", "RSP", "IWM")
            for d in idx]
    p = tmp_path / "prices.csv"
    pd.DataFrame(rows).to_csv(p, index=False)

    html = report.render_html(_feat(), prices_path=str(p))
    n_table = html.count("<table class=")
    assert n_table > 0
    assert html.count('<div class="scroll">') == n_table

