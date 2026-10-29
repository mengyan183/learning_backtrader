# -*- coding: utf-8 -*-
"""仪表盘生成测试（§12）。"""
import os
import re

import pandas as pd
import pytest

from fg_system.dashboard import report


def _strip_scripts(html):
    """剥掉 <script>...</script>，只留静态 HTML。

    动态 table 拼在 JS 字符串里，**不应**被 scroll 后处理包裹——否则
    `<div class="scroll">` 的双引号会撞破外层 JS 字符串 ⇒ SyntaxError ⇒
    整段脚本失效（图表不渲染、tab 点不动，2026-10-27 事故）。
    """
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


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
    # MT-67：豁免**用户主动点击**的官方跳转 <a href>（不拉外部资源 ✓，
    # 与 CDN/字体/脚本自动加载性质不同）；其余外部 http(s) 仍禁止 ✓
    ALLOWED_LINK_HOSTS = ("fe.szdt.tech",)
    body = re.sub(r'href="https?://fe\.szdt\.tech/[^"]*"', "", body)
    assert "http://" not in body, "存在外部 http 引用"
    assert "https://" not in body, "存在外部 https 引用"
    for m in re.finditer(r"""(?:src|href)=["']([^"']+)["']""", html):
        url = m.group(1)
        if url.startswith(("http://", "https://", "//")):
            if any(host in url for host in ALLOWED_LINK_HOSTS):
                continue  # 官方跳转白名单 ✓
            raise AssertionError("存在外部资源引用: %s" % url)
        if ("<script" in html[:m.start()][-30:] or "stylesheet" in html[:m.start()][-50:]):
            assert url.startswith("/static/"), "静态资源必须指向本地 /static/: %s" % url


def test_html_tables_are_horizontally_scrollable(tmp_path):
    """**守卫**：静态表格都要套横向滚动容器 —— 否则宽表在窄屏上溢出、
    把整页撑宽，用户得左右拖整页才能看全。script 内动态表格不参与此约束。
    """
    html = _render(tmp_path)
    static = _strip_scripts(html)
    n_scroll = static.count('<div class="scroll">')
    n_table = static.count("<table class=")
    assert n_table > 0, "没有静态表格？测试数据变了"
    assert n_scroll == n_table, "有静态表格没被滚动容器包住（%d 表 / %d 容器）" % (
        n_table, n_scroll)
    # 动态 table（JS 字符串）绝不能被包进 <div class="scroll">，否则双引号撞破字符串
    assert 'innerHTML = "<div class="scroll"' not in html, \
        "JS 字符串里的动态表格被 scroll 后处理误包，会引发 SyntaxError"


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


def test_sticky_header_and_style_floor():
    """**守卫**：粘性表头靠三件事同时成立 ✓ —— 少一件就**静默失效** ✗。

    1) `table.card th` 必须 `position:sticky`；
    2) `div.scroll` 必须是纵向滚动容器 ✓ 否则 sticky 没有可粘的上下文 ✗；
    3) `table.card` **不能**有 `overflow:hidden` ✗ 它自己会变成滚动容器 ✗。

    另锁两件 2026-10-27 改过的事：body 不再有径向光晕 ✓、
    reduced-motion 覆盖全局 transition ✓（原来只覆盖了 sheet ✗）。
    """
    css = open(os.path.join(os.path.dirname(report.__file__),
                            "static", "style.css"), encoding="utf-8").read()
    flat = css.replace(" ", "").replace("\n", "")
    assert "table.cardth" in flat and "position:sticky" in flat
    assert "div.scroll{overflow:auto" in flat and "max-height:70vh" in flat
    card = flat.split("table.card{")[1].split("}")[0]
    assert "overflow:hidden" not in card, \
        "table.card 上的 overflow:hidden 会让粘性表头失效（它自己成了滚动容器）"
    body = flat.split("body{")[1].split("}")[0]
    assert "radial-gradient" not in body, "body 的径向光晕是装饰，已删，别加回来"
    assert "prefers-reduced-motion:reduce" in flat
    assert "transition-duration:.01ms!important" in flat
    # 注释里的「星号+斜杠」会提前闭合注释 ✗ ⇒ 吞掉紧跟的第一条规则 ✗
    # （2026-10-27 踩过两次：input 规则被吞，输入框一直白底，且 cssRules 里查不到 ✗）
    bad = [ln for ln in css.splitlines() if "*/" in ln[:-2]]
    assert not bad, "注释符出现在行中间，会提前闭合注释并吞掉下一条规则：%r" % bad[:3]


def test_index_gran_selector_defaults_to_week(tmp_path):
    """历史采样四档（周/月/年/全部）✓，**默认周线** ✓。

    2026-10-29：1765 个日点画在 330px 宽上，一个像素挤 5 个点，既看不清又拖慢首绘 ✗。
    """
    html = _render(tmp_path)
    for g in ("week", "month", "year", "all"):
        assert 'data-gran="%s"' % g in html, "缺 %s 档 ✗" % g
    assert 'class="idxwin btn-xs on" data-gran="week"' in html, "默认档不是周线 ✗"
    # 周/月/年必须是 **K 线**（每根 = 该周期 开/高/低/收），不是「取第一个点」✗
    assert 'type: "candlestick"' in html, "周/月/年又退回折线了 ✗（市面软件是 K 线）"
    assert "notMerge: true" in html, \
        "折线 ↔ K 线切换必须 notMerge ✗（否则 line 的样式残留到蜡烛上）"


def test_inline_json_rounds_floats_and_drops_factor_dates(tmp_path):
    """**守卫**：内联 JSON 必须收敛小数位 + 因子图不带日期 ✓。

    2026-10-28 实测：首页 HTML **473 KB**，其中 FACTORS 独占 281 KB ——
    `45.23809523809524`（18 字符）× 1765 点 × 5 条 ✗，外加 5×1765 个日期 ✗，
    而因子 sparkline 的日期轴是 `show:false`，**根本不显示** ✗。
    """
    idx = pd.date_range("2023-01-01", periods=60, freq="B")
    feats = pd.DataFrame({"fg_index": 50.123456789, "zone": 2,
                          "target_position": 0.123456789012345,
                          "vix": 50.987654321}, index=idx)
    html = report.render_html(feats, prices_path=str(tmp_path / "none.csv"))
    assert "50.123456789" not in html, "指数值又按全精度写进内联 JSON 了 ✗"
    assert "0.123456789012345" not in html, "仓位值又按全精度写进内联 JSON 了 ✗"
    m = re.search(r"var FACTORS = (.*?);\n", html, re.S)
    assert m, "模板里找不到 FACTORS"
    assert not re.search(r"\d{4}-\d{2}-\d{2}", m.group(1)), \
        "FACTORS 又带上日期字符串了 ✗（日期轴不显示）"


def test_sync_mobile_override_comes_after_base_rules():
    """**守卫**：同步页的窄屏覆盖必须写在**基础规则之后** ✓。

    CSS 同等特异性下**后写者赢** ✗ —— 2026-10-28 实测：把 `.kv-list` 的单列覆盖
    放进文件前面那个 `@media (max-width:600px)` 块里，被后面的基础规则压掉 ✗
    ⇒ 390px 下仍是 `156px 156px` 两列、`.task-row` 第三列被压成 0 ✗。
    """
    css = open(os.path.join(os.path.dirname(report.__file__),
                            "static", "style.css"), encoding="utf-8").read()
    assert css.rindex("@media (max-width:600px)") > css.index(".kv-list{"), \
        "同步页的窄屏覆盖写在了基础规则之前 ⇒ 会被压掉 ✗"


def test_hero_admits_stale_signal():
    """**守卫**：信号日超容差 ⇒ hero 必须自曝「非当前」✓。

    原来 hero 只写「信号日」，52px 的分数永远像当下的 ✗
    （2026-10-27 实测：页面时间 10-27、信号日 10-12，差 15 天，用户可能按旧读数下单 ✗）。
    """
    def _feats(days_ago):
        idx = pd.date_range(end=pd.Timestamp.now().normalize()
                            - pd.Timedelta(days=days_ago), periods=5, freq="D")
        return pd.DataFrame({"fg_index": [50.0] * 5, "zone": [2] * 5}, index=idx)

    old = report._state_card(_feats(15))
    assert "stale-flag" in old, "过期信号必须挂 stale-flag ✗"
    assert "数据停更 15 天" in old and "非当前" in old
    assert "hero-num stale" in old, "过期的分数必须降级显示（不再像当下）✗"

    fresh = report._state_card(_feats(0))
    assert "stale-flag" not in fresh, "新鲜信号不得误报过期 ✗"
    assert "hero-num stale" not in fresh


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
    static = _strip_scripts(html)
    n_table = static.count("<table class=")
    assert n_table > 0
    assert static.count('<div class="scroll">') == n_table


def test_fresh_param_is_one_shot(tmp_path):
    """**守卫**：`?fresh=1` 必须**一次性** ✓。

    2026-10-28 手机端实测：点「强制重算整页」后地址栏永远留着 `?fresh=1` ✗
    ⇒ 之后每次刷新、每次从主屏图标打开都强制重算（几秒白屏 ✗）。
    """
    html = _render(tmp_path)
    assert "replaceState" in html, "缺「用完把 ?fresh=1 从地址栏摘掉」的处理 ✗"
    assert "/[?&]fresh=1/" in html, "判断条件必须只认 fresh=1 ✓（别把别的参数一起清掉）"


def test_task_list_shows_output_for_done_tasks(tmp_path):
    """✅ 的任务也要显示 `output` ✓。

    2026-10-28 手机端实测：`clean_sync_partial` 只显示「✅ · 0s」✗
    ⇒ 看不出它到底删了什么（0 秒既可能是「删了 2 个」也可能是「什么都没找到」✗）。
    """
    html = _render(tmp_path)
    assert 'x.status === "failed" && x.output' not in html, \
        "成功任务又只显示状态、不显示结果了 ✗"
    assert "x.output" in html


def test_echarts_is_lazy_loaded(tmp_path):
    """**守卫**：echarts（1MB）不得随首屏加载 ✓。

    它曾是 `<head>` 里的阻塞脚本 ⇒ 首屏那个 52px 的数字要等 1MB 解析完 ✗。
    现在按需注入：首页 hero 是纯 HTML/CSS ✓，切页/展开折叠才拉 ✓。
    """
    html = _render(tmp_path)
    assert '<script src="/static/echarts.min.js"' not in html, \
        "echarts 又变成首屏阻塞脚本了 ✗"
    assert "needEcharts" in html, "按需加载器缺失 ✗"
    assert "/static/echarts.min.js" in html, "按需加载器必须指向本地静态资源 ✗"
    assert "drawH30(30);\n" not in html, "Human 3.0 图表又变成加载即画了 ✗"

