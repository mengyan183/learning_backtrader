# -*- coding: utf-8 -*-
"""自包含 HTML 仪表盘（§12）。

7 个区块：当前状态卡 / 指数曲线与档位带 / 四因子分解 / 目标仓位与买卖点
          / 损耗监控 / 损耗归因 / 外部指数对照。

曲线用**内联 SVG** 绘制（不依赖 CDN，离线可用）；同时把数据以 JSON 内嵌，
方便后续换用 Plotly 等方案。外部指数与损耗数据缺失时降级显示，不阻断生成。
"""
import json
import os
import re

import numpy as np
import pandas as pd

from fg_system import config
from fg_system import leverage
from fg_system.dashboard import pwa

ZONE_COLORS = ["#8b0000", "#d9534f", "#f0ad4e", "#5cb85c", "#006400"]
ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


def _holdings_block(features):
    """持仓标的看板：我的持仓 × 市场贪恐环境 × 系统覆盖与指令（只读快照）。

    数据口径：
    - 持仓 = Data/positions.csv 最新日期行（sync_positions.py 产出）
    - 净值 = Data/accounts.csv 最新 stock 行
    - 市场贪恐 = features 最新 fg_index（**市场级**；标的级系数数据源
      szdt.tech/universe 未覆盖 GDXU/YINN/CONL/CRCG/AXTX，故不虚造标的级系数）
    - 系统覆盖 = config.SYMBOLS ∪ CRYPTO_FLAT_SYMBOLS（与 portfolio_check 同口径）
    """
    out = ["<p style='font-size:12px;color:#8b949e'>贪恐系数为<b>市场级 fg_index</b>"
           "（标的级系数数据源未覆盖下列持仓 ETF，不虚造）；持仓来自实盘快照，只读；"
           "浮盈亏按红涨绿跌着色。</p>"]
    try:
        pos = pd.read_csv(config.POSITIONS_PATH)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return "".join(out) + "<p>持仓快照不可用（Data/positions.csv 缺失）</p>"
    if pos.empty:
        return "".join(out) + "<p>持仓快照为空</p>"
    latest = pos[pos["date"] == pos["date"].max()]
    try:
        acc = pd.read_csv(config.ACCOUNTS_PATH)
        acc = acc[(acc["account"] == "stock") & (acc["date"] == acc["date"].max())]
        net = float(acc.iloc[-1]["net_value"]) if not acc.empty else None
    except Exception:
        net = None

    # 市场贪恐环境（最新）
    fg, zone = None, "—"
    valid = features.dropna(subset=["fg_index"])
    if not valid.empty:
        fg = float(valid.iloc[-1]["fg_index"])
        zi = int(np.clip(np.searchsorted([20, 40, 60, 80], fg, side="right"), 0, 4))
        zone = ZONE_NAMES[zi]
    env_cell = ("%s %s" % (("%.0f" % fg), zone)) if fg is not None else "—"

    in_system = set(config.SYMBOLS) | set(config.CRYPTO_FLAT_SYMBOLS)
    cards = []
    for _, r in latest.iterrows():
        sym = str(r.get("symbol", "")).strip()
        name = str(r.get("name", "")).strip()
        mv = _num(r.get("market_value"))
        qty = _num(r.get("qty"))
        price = _num(r.get("price"))
        cost = _num(r.get("cost"))
        pnl = ((price - cost) / cost * 100.0) if cost and cost > 0 and price else None
        ratio = (mv / net * 100.0) if net and mv is not None else None
        in_s = sym in in_system
        if in_s:
            advise = "系统可给指令（目标见区块5）"
        else:
            advise = "系统无指令（覆盖范围外）"
        pnl_cls = ("up" if pnl and pnl >= 0 else "down") if pnl is not None else ""
        pnl_txt = ("%+.1f%%" % pnl) if pnl is not None else "—"
        cards.append(
            "<div class='h-card'>"
            "<div class='h-top'><span class='h-sym'>%s</span>"
            "<span class='h-pnl %s'>%s</span></div>"
            "<div class='h-name'>%s</div>"
            "<div class='h-mid'>市值 %s · 占净值 %s · 数量 %s</div>"
            "<div class='h-tags'>"
            "<span class='tag tag-zone' style='background:%s'>贪恐 %s</span>"
            "<span class='tag %s'>%s</span>"
            "<span class='tag tag-adv'>%s</span>"
            "</div></div>"
            % (sym, pnl_cls, pnl_txt, name, _fmt(mv),
               ("%.1f%%" % ratio) if ratio is not None else "—", _fmt(qty),
               ZONE_COLORS[zi], env_cell,
               ("tag-in" if in_s else "tag-out"), ("✅ 系统覆盖" if in_s else "❌ 范围外"),
               advise))
    if not cards:
        return "".join(out) + "<p>无持仓记录</p>"
    return "".join(out) + "<div class='h-grid'>" + "".join(cards) + "</div>"


def _num(v):
    try:
        f = float(v)
        return f if np.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _fmt(v):
    if v is None:
        return "—"
    return ("%d" % v) if float(v).is_integer() else ("%.2f" % v)


# ------------------------------------------------------------------ 区块
def _state_card(features):
    valid = features.dropna(subset=["fg_index"])
    if valid.empty:
        return "<p>指数无效（warmup 未完成）</p>"
    row = valid.iloc[-1]
    zone = int(row["zone"]) if not pd.isna(row.get("zone")) else 2
    target = row.get("target_position")
    cb = bool(row.get("circuit_breaker", False))
    fg = float(row["fg_index"])
    items = [
        ("核心仓", "%.1f%%" % ((row.get("core_position") or 0) * 100)),
        ("弹药仓", "%.1f%%" % ((row.get("ammo_position") or 0) * 100)),
        ("目标总仓位", "%.1f%%" % ((target or 0) * 100)),
        ("熔断状态", "熔断中" if cb else "正常"),
    ]
    stat = "".join(
        "<div class='stat'><div class='stat-label'>%s</div><div class='stat-value%s'>%s</div></div>"
        % (k, " bad" if (k == "熔断状态" and v == "熔断中") else "", v)
        for k, v in items)
    return """
    <div class="hero">
      <div class="hero-date">信号日 %s</div>
      <div class="hero-fg"><span class="hero-num">%.1f</span>
        <span class="zone" style="background:%s">%s</span></div>
      <div class="stat-grid">%s</div>
    </div>""" % (valid.index[-1].strftime("%Y-%m-%d"), fg, ZONE_COLORS[zone],
                 ZONE_NAMES[zone], stat)


def _loss_block(prices):
    if prices is None or prices.empty:
        return "<p>数据不可用</p>"
    try:
        table = leverage.attribution_table(prices)
    except Exception as exc:                      # 数据缺失不应阻断仪表盘
        return "<p>损耗归因不可用：%s</p>" % exc
    if table.empty:
        return "<p>损耗归因数据不足</p>"
    html = ["<table class='card'><tr><th>杠杆ETF</th><th>标的</th><th>标的年化σ</th>"
            "<th>波动率拖累/年</th><th>产品损耗/年</th><th>合计/年</th></tr>"]
    for _, r in table.iterrows():
        html.append("<tr><td>%s</td><td>%s</td><td>%.1f%%</td><td>%.2f%%</td>"
                    "<td>%.2f%%</td><td><b>%.2f%%</b></td></tr>"
                    % (r["leveraged"], r["underlying"], r["sigma"] * 100,
                       r["vol_decay_annual"] * 100, r["product_cost_annual"] * 100,
                       r["total_annual"] * 100))
    html.append("</table>")
    return "".join(html)


def _decay_rate_block(features, prices):
    """第 5 区块：损耗监控（§4.5 约束 4：只观测，不参与仓位计算）。"""
    lines = []
    for lev, und in config.UNDERLYING_MAP.items():
        if prices is None or prices.empty:
            rate = float("nan")
        else:
            s = prices[prices["symbol"] == und].set_index("date")["close"].sort_index()
            rate = leverage.current_decay_rate(
                s.pct_change().dropna(),
                n=config.LEVERAGE_RATIO[lev],
                product_rate=config.PRODUCT_COST_RATE.get(lev, 0.0),
            )
        lines.append("<tr><td>%s</td><td>%s</td><td>%.2f%%</td></tr>"
                     % (lev, und, rate * 100 if rate == rate else float("nan")))
    return ("<table class='card'><tr><th>杠杆ETF</th><th>标的</th>"
            "<th>当前损耗速率（年化，近20日σ）</th></tr>" + "".join(lines) + "</table>")


def _svg_line(points, width=900, height=260, pad=36, y_min=None, y_max=None,
              color="#1f77b4", bands=None):
    """内联 SVG 折线；points 为 [(date_str, value)]，跳过 NaN。"""
    pts = [(d, float(v)) for d, v in points if v is not None and float(v) == float(v)]
    if len(pts) < 2:
        return "<p>数据点不足，无法绘图</p>"

    xs = list(range(len(pts)))
    vals = [v for _, v in pts]
    if y_min is None:
        y_min = min(vals)
    if y_max is None:
        y_max = max(vals)
    if y_max == y_min:
        y_max, y_min = y_max + 1.0, y_min - 1.0

    def sx(i):
        return pad + (width - 2 * pad) * i / (len(pts) - 1)

    def sy(v):
        return height - pad - (height - 2 * pad) * (v - y_min) / (y_max - y_min)

    parts = []
    # 档位带（背景横条）
    if bands:
        for lo, hi, col in bands:
            top = sy(min(hi, y_max))
            bot = sy(max(lo, y_min))
            if bot > top:
                parts.append('<rect x="%d" y="%.1f" width="%d" height="%.1f" fill="%s" '
                             'opacity="0.13"/>' % (pad, top, width - 2 * pad, bot - top, col))

    # 边框 + 网格（深色主题：细半透明）
    parts.append('<rect class="frame" x="%d" y="%d" width="%d" height="%d" fill="none" '
                 'stroke="rgba(255,255,255,0.1)"/>' % (pad, pad, width - 2 * pad, height - 2 * pad))
    for gy in (0.25, 0.5, 0.75):
        parts.append('<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f" '
                     'stroke-dasharray="3,3"/>'
                     % (pad, pad + gy * (height - 2 * pad), width - pad,
                        pad + gy * (height - 2 * pad)))

    # 面积渐变 + 折线
    area = ("%s%.1f,%.1f " % ("M", sx(0), sy(vals[0]))
            + " ".join("L%.1f,%.1f" % (sx(i), sy(v)) for i, v in enumerate(vals))
            + " L%.1f,%.1f Z" % (sx(len(vals) - 1), sy(vals[-1])))
    parts.append(
        '<defs><linearGradient id="grad%s" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%%" stop-color="%s" stop-opacity="0.28"/>'
        '<stop offset="100%%" stop-color="%s" stop-opacity="0.0"/>'
        '</linearGradient></defs>'
        '<path d="%s" fill="url(#grad%s)" stroke="none"/>' % (color.replace("#", "c"), color, color, area, color.replace("#", "c")))
    d = " ".join("%s%.1f,%.1f" % ("M" if i == 0 else "L", sx(i), sy(v))
                 for i, (_, v) in enumerate(pts))
    parts.append('<path d="%s" fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round" '
                 'stroke-linecap="round"/>' % (d, color))

    # 轴标签
    parts.append('<text x="%d" y="%d" font-size="11">%s</text>'
                 % (pad, height - 12, pts[0][0]))
    parts.append('<text x="%d" y="%d" font-size="11" text-anchor="end">%s</text>'
                 % (width - pad, height - 12, pts[-1][0]))
    parts.append('<text x="%d" y="%d" font-size="11">%.1f</text>'
                 % (pad - 6, pad + 4, y_max))
    parts.append('<text x="%d" y="%d" font-size="11" fill="#8b949e">%.1f</text>'
                 % (pad - 6, height - pad + 4, y_min))
    return '<svg class="chart" viewBox="0 0 %d %d" preserveAspectRatio="xMidYMid meet">%s</svg>' % (
        width, height, "".join(parts))


def _factors_block(valid):
    keys = [k for k in ["vix", "term", "price", "breadth"] if k in valid.columns]
    if not keys:
        return "<p>因子数据不可用</p>"
    out = []
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    for i, k in enumerate(keys):
        pts = [(d.strftime("%Y-%m-%d"), float(v))
               for d, v in valid[k].items() if not pd.isna(v)]
        out.append("<h3 style='font-size:13px;margin:10px 0 2px'>%s</h3>" % k)
        out.append(_svg_line(pts, height=140, color=colors[i % len(colors)]))
    return "".join(out)


def _position_block(valid):
    if "target_position" not in valid.columns:
        return "<p>仓位数据不可用</p>"
    pos = valid["target_position"].dropna()
    if pos.empty:
        return "<p>目标仓位数据不足</p>"
    pts = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in pos.items()]
    svg = _svg_line(pts, height=200, y_min=0.0, y_max=1.0, color="#d62728")
    # 买卖点：信号档位发生变化的日期
    changes = pos.diff().fillna(0.0)
    events = changes[changes.abs() >= config.REBALANCE_THRESHOLD].tail(20)
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%.1f%%</td></tr>"
                   % (d.strftime("%Y-%m-%d"),
                      "加仓" if v > 0 else "减仓", abs(v) * 100)
                   for d, v in events.items())
    return svg + ("<table class='card'><tr><th>日期</th><th>方向</th><th>调整幅度</th></tr>%s"
                  "</table>" % rows if rows else "<p>区间内无调仓事件</p>")


def _buy_and_hold_block(features, prices):
    """净值对比表：策略（目标仓位拟合）vs 买入持有。"""
    if prices is None or prices.empty:
        return "<p>数据不可用</p>"
    valid = features.dropna(subset=["fg_index", "target_position"])
    if valid.empty:
        return "<p>数据不可用</p>"
    rows = []
    for symbol in config.SYMBOLS:
        p = prices[prices["symbol"] == symbol].set_index("date").sort_index()["close"]
        bh = p.pct_change().dropna()
        # target_position 在 pipeline 已整体 shift(1)（T 日执行 T-1 信号），
        # 此处不可再 shift，否则会退化为 T-2 信号、与 runner 口径不一致。
        ret = valid["target_position"].fillna(0.0).reindex(bh.index).fillna(0.0)
        strat_ret = ret * bh
        rows.append({
            "symbol": symbol,
            "strat_total": float((1.0 + strat_ret).prod() - 1.0),
            "bh_total": float((1.0 + bh).prod() - 1.0),
        })
    html = ["<table class='card'><tr><th>标的</th><th>策略累计收益（目标仓位拟合）</th>"
            "<th>买入持有累计收益</th></tr>"]
    for r in rows:
        html.append("<tr><td>%s</td><td>%.1f%%</td><td>%.1f%%</td></tr>"
                    % (r["symbol"], r["strat_total"] * 100, r["bh_total"] * 100))
    html.append("</table>")
    return "".join(html)


# ------------------------------------------------------------------ 主入口
def render_html(features, title="贪婪恐惧指数仪表盘", prices_path=None):
    """生成仪表盘 HTML **字符串**（**不落盘**）。

    与 `build` 的分工：`build` 写文件（CLI 用），`render_html` 只返回字符串 ——
    **服务端每次请求都要一份新鲜 HTML**，见 `fg_system/dashboard/server.py`。
    """
    prices_path = prices_path or os.path.join(config.RAW_DIR, "prices.csv")

    try:
        prices = pd.read_csv(prices_path, parse_dates=["date"])
    except (FileNotFoundError, pd.errors.EmptyDataError):
        prices = pd.DataFrame(columns=["date", "symbol", "close"])

    valid = features.dropna(subset=["fg_index"])
    index_points = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in valid["fg_index"].items()]
    external = _load_external_index()

    bands = []
    edges = [-1e9] + list(config.ZONE_EDGES) + [1e9]
    for i in range(5):
        bands.append((edges[i], edges[i + 1], ZONE_COLORS[i]))

    index_svg = _svg_line(index_points, bands=bands, y_min=0.0, y_max=100.0)

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>%(title)s</title>
%(pwa_head)s
<style>
:root{{
  --bg:#0b0e14;--card:rgba(22,27,38,.72);--border:rgba(255,255,255,.07);
  --text:#e6edf3;--sub:#8b949e;--accent:#58a6ff;--up:#f85149;--down:#3fb950;
  --chip:rgba(255,255,255,.06);--radius:14px;
}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
  margin:0;padding:18px;background:radial-gradient(1200px 600px at 20%% -10%%,#16202e 0%%,var(--bg) 55%%) fixed;
  color:var(--text);-webkit-text-size-adjust:100%%;font-variant-numeric:tabular-nums}}
.wrap{{max-width:1080px;margin:0 auto}}
h1{{font-size:21px;font-weight:700;margin:2px 0 4px;letter-spacing:.3px}}
.sub{{color:var(--sub);font-size:12px;margin:0 0 18px}}
h2{{font-size:14px;margin:22px 0 10px;padding:10px 14px;background:var(--card);
  border:1px solid var(--border);border-radius:var(--radius);border-left:3px solid var(--accent);
  display:flex;align-items:center;gap:8px}}
h2 .no{{background:var(--chip);border:1px solid var(--border);border-radius:6px;
  padding:0 7px;font-size:11px;color:var(--sub);font-weight:600}}
.sec{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px;margin:0 0 12px}}
table.card{{border-collapse:collapse;width:100%%;background:transparent;border-radius:10px;overflow:hidden}}
table.card th,table.card td{{border-bottom:1px solid var(--border);padding:8px 12px;font-size:13px;text-align:left}}
table.card th{{background:var(--chip);color:var(--sub);font-weight:600;font-size:12px}}
table.card tr:last-child td{{border-bottom:none}}
div.scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%%}}
.zone{{display:inline-block;padding:3px 10px;border-radius:20px;color:#fff;font-size:12px;font-weight:600}}
/* 状态卡 hero */
.hero{{display:flex;flex-direction:column;gap:12px}}
.hero-date{{color:var(--sub);font-size:12px}}
.hero-fg{{display:flex;align-items:baseline;gap:12px}}
.hero-num{{font-size:44px;font-weight:800;line-height:1}}
.stat-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.stat{{background:var(--chip);border:1px solid var(--border);border-radius:10px;padding:10px 12px}}
.stat-label{{color:var(--sub);font-size:11px;margin-bottom:4px}}
.stat-value{{font-size:17px;font-weight:700}}
.stat-value.bad{{color:var(--up)}}
/* 持仓卡片网格 */
.h-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
.h-card{{background:var(--chip);border:1px solid var(--border);border-radius:12px;padding:12px 14px}}
.h-top{{display:flex;justify-content:space-between;align-items:center}}
.h-sym{{font-size:16px;font-weight:800;letter-spacing:.3px}}
.h-pnl{{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}}
.h-pnl.up{{color:var(--up)}} .h-pnl.down{{color:var(--down)}}
.h-name{{color:var(--sub);font-size:12px;margin:2px 0 8px}}
.h-mid{{font-size:12px;color:var(--text);margin-bottom:10px}}
.h-tags{{display:flex;flex-wrap:wrap;gap:6px}}
.tag{{display:inline-block;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:600;color:#fff}}
.tag-zone{{opacity:.95}}
.tag-in{{background:rgba(63,185,80,.25);color:var(--down);border:1px solid rgba(63,185,80,.4)}}
.tag-out{{background:rgba(139,148,158,.2);color:var(--sub);border:1px solid var(--border)}}
.tag-adv{{background:var(--chip);color:var(--text);border:1px solid var(--border)}}
/* 图表 */
svg.chart{{display:block;max-width:100%%;height:auto;background:transparent;border-radius:10px}}
svg.chart text{{fill:var(--sub)}}
svg.chart .grid{{stroke:rgba(255,255,255,.06)}}
svg.chart .frame{{stroke:rgba(255,255,255,.1)}}
/* 其它区块内表格间距 */
.sec table.card{{margin:4px 0 0}}
@media (max-width:780px){{
  .h-grid{{grid-template-columns:repeat(2,1fr)}}
}}
@media (max-width:600px){{
  body{{padding:12px}}
  h1{{font-size:18px}}
  .hero-num{{font-size:38px}}
  .stat-grid{{grid-template-columns:repeat(2,1fr)}}
  .h-grid{{grid-template-columns:1fr}}
  table.card th,table.card td{{padding:6px 10px;font-size:12px}}
}}
</style></head><body>
<div class="wrap">
<h1>%(title)s</h1>
<p class="sub">生成 %(now)s · 有效指数 %(valid_days)d 天 · 区间 %(span)s</p>

<h2><span class="no">1</span>当前状态卡</h2>
<div class="sec">%(card)s</div>

<h2><span class="no">2</span>持仓标的看板</h2>
<div class="sec">%(holdings)s</div>

<h2><span class="no">3</span>指数曲线与档位带（fg_index）</h2>
<div class="sec">%(index_svg)s</div>

<h2><span class="no">4</span>四因子分解</h2>
<div class="sec">%(factors)s</div>

<h2><span class="no">5</span>目标仓位与买卖点</h2>
<div class="sec">%(position)s</div>

<h2><span class="no">6</span>净值对比（策略 vs 买入持有）</h2>
<div class="sec">%(nav)s</div>

<h2><span class="no">7</span>损耗监控（§4.5 约束 4）</h2>
<div class="sec">%(decay)s</div>

<h2><span class="no">8</span>损耗归因（§11.6 强制输出）</h2>
<div class="sec">%(loss)s</div>

<h2><span class="no">9</span>外部指数对照（人工录入，可留空，§15.3）</h2>
<div class="sec"><p>%(external_note)s</p></div>

<script>
const INDEX = %(index_json)s;
const FACTORS = %(factors_json)s;
const POSITION = %(position_json)s;
const EXTERNAL = %(external_json)s;
</script>
</div>
</body></html>
""" % {
        "title": title,
        "now": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "valid_days": len(valid),
        "span": ("%s ~ %s" % (valid.index[0].strftime("%Y-%m-%d"),
                              valid.index[-1].strftime("%Y-%m-%d")) if len(valid) else "无"),
        "card": _state_card(features),
        "holdings": _holdings_block(features),
        "index_svg": index_svg,
        "factors": _factors_block(valid),
        "position": _position_block(valid),
        "nav": _buy_and_hold_block(features, prices),
        "decay": _decay_rate_block(features, prices),
        "loss": _loss_block(prices),
        "external_note": ("已录入 %d 条外部指数记录" % len(external)
                          if external else "未录入（不影响其他功能）"),
        "index_json": _json(index_points),
        "factors_json": _json({
            k: [(d.strftime("%Y-%m-%d"), float(v)) for d, v in valid[k].items()]
            for k in ["vix", "term", "price", "breadth"] if k in valid.columns
        }),
        "position_json": _json([
            (d.strftime("%Y-%m-%d"), float(v))
            for d, v in valid["target_position"].dropna().items()
        ]) if "target_position" in valid.columns else _json([]),
        "external_json": _json(external),
        # 「添加到主屏幕」所需标签（manifest / 图标 / theme-color）——
        # 让手机**不需要 APK** 也能有独立图标，见 pwa 模块 docstring。
        "pwa_head": pwa.HEAD_TAGS,
    }

    # 每个表格套横向滚动容器：窄屏下宽表不撑破页面（手机端必需）。
    # 用后处理而不是改各个 _*_block：表格分散在 6 处，集中处理不会漏。
    return re.sub(r"""(<table class=['"]card['"]>.*?</table>)""",
                  r'<div class="scroll">\1</div>', html, flags=re.S)


def build(features, path=None, title="贪婪恐惧指数仪表盘", prices_path=None):
    """生成自包含 HTML 并**落盘**，返回文件路径。

    外部指数与损耗数据缺失时降级显示，不阻断生成。
    """
    path = path or os.path.join(config.REPORTS_DIR, "dashboard.html")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    html = render_html(features, title=title, prices_path=prices_path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


def _load_external_index():
    """读取人工录入的外部指数（date,value,note），缺失返回空列表。"""
    try:
        df = pd.read_csv(config.EXTERNAL_INDEX_PATH, parse_dates=["date"])
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return []
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in zip(df["date"], df["value"])]


# ================================================================ v2 加密区块

_LAYER_LABELS = {
    "btc_beta": "BTC 纯 Beta（BITX/BITU）",
    "stock_high_beta": "币股高 Beta（MSTX/MSTU）",
    "stock_ops_beta": "币股经营 Beta（CONL）",
}

_GREED_TIER_LABELS = {
    0: "正常", 1: "第 1 档（2/3）", 2: "第 2 档（1/3）", 3: "第 3 档（1/4）",
}


def _crypto_block(crypto_features, coinglass_value=None):
    """加密子系统区块的 HTML 片段。

    coinglass 数值来自**人工录入**（设计 §10.3）——coinglass 的前端 API 有统一
    鉴权层，无法程序化获取；该数值**永远不参与仓位计算**，仅用于复盘对照。
    """
    valid = crypto_features.dropna(subset=["crypto_fg_index"]) \
        if "crypto_fg_index" in crypto_features.columns else crypto_features.iloc[0:0]
    if valid.empty:
        return ("<h2>加密贪婪恐惧指数</h2>"
                "<p>无有效信号（warmup 未完成——CF1 贪恐指数 2018-02 起，"
                "叠加 756 日滚动窗口，加密信号约在 2021-02 才生效）</p>")

    last = valid.iloc[-1]
    rows = [
        ("加密贪恐指数", "%.1f" % last["crypto_fg_index"]),
        ("趋势过滤", "生效（上限减半）" if last.get("trend_blocked") else "未触发"),
        ("极贪减仓档位", _GREED_TIER_LABELS.get(int(last.get("greed_tier", 0) or 0), "—")),
        ("加密核心仓", "%.2f%%" % ((last.get("core_position") or 0) * 100)),
        ("BTC 回撤（弹药基准）", "%.2f%%" % ((last.get("drawdown") or 0) * 100)),
    ]

    html = ["<h2>加密贪婪恐惧指数</h2>", "<table class='card'>"]
    for k, v in rows:
        html.append("<tr><td>%s</td><td>%s</td></tr>" % (k, v))
    html.append("</table>")

    html.append("<h3>分层仓位上限</h3><table class='card'>")
    html.append("<tr><th>层</th><th>上限</th></tr>")
    for layer, label in _LAYER_LABELS.items():
        v = last.get("layer_%s" % layer)
        html.append("<tr><td>%s</td><td>%s</td></tr>"
                    % (label, "%.2f%%" % (v * 100) if v is not None and v == v else "—"))
    html.append("</table>")

    html.append("<h3>coinglass 人工对照</h3>")
    if coinglass_value is None:
        html.append(
            "<p>未录入。每日从 coinglass 页面读取后填入 "
            "<code>Data/raw/external_index.csv</code>（字段 date,value,note）。"
            "该数值<b>不参与任何仓位计算</b>，仅用于复盘对照。</p>")
    else:
        html.append("<p>coinglass 当日值：<b>%.1f</b>（alternative.me：%.1f）</p>"
                    % (coinglass_value, last["crypto_fg_index"]))
    return "\n".join(html)


def build_v2(us_features, crypto_features, path=None, coinglass_value=None):
    """v2 仪表盘：v1 全部区块 + 加密区块 + coinglass 人工对照。

    复用 v1 的 `build()` 产出大盘部分（v1 渲染逻辑零改动），再注入加密区块。
    """
    path = path or os.path.join(config.REPORTS_DIR, "dashboard_v2.html")
    build(us_features, path=path)

    with open(path, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("</body>",
                        _crypto_block(crypto_features, coinglass_value) + "\n</body>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
