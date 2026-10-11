#!/usr/bin/env python3
"""R1.1 因子评测协议：IC/RankIC + 分层净值 + 多空对冲 + 含成本双口径（Qlib 蓝图自实现）。

用法：
  .venv/bin/python scripts/factor_screen.py                # 全量：候选+生产因子+观察池 legacy
  .venv/bin/python scripts/factor_screen.py --factors-only # 只跑候选+生产因子（不含观察池）
输出：stdout markdown + evolution/factor-screen-results.md + evolution/factor-screen-results.json

评测对象（R1.1 验收）：
  - 生产六因子：features.csv 的 vix/term/price/breadth/fed/putcall（0-100 因子分）→ SPY
  - 候选因子：F-007 守猪待兔市场温度 → SPY；F-009 资金费率 → 样本不足如实报告；
              F-010 新闻情绪 → SPY；F-011 Put-Call total_ratio（正向）→ SPY
  - 观察池 legacy：fg_index × OBSERVE_SYMBOLS（兼容旧报告口径）

口径（factor-engine.md §4 / Qlib 蓝图）：
  - IC = Pearson 滚动相关；RankIC = Spearman（rank 后 Pearson）
  - 分层：信号对自身 756 日滚动分位分 5 桶（无前视），输出桶均值/顶底差/单调性
  - 多空：顶桶做多 − 底桶做空（非重叠调仓），净值/年化/回撤；含成本=每期扣 2×fee（默认10bp）
  - 门槛：|ICIR| ≥ 0.5 且 n ≥ 60 且近窗（120）无衰减

纪律：只做数据取证，不改策略、不进白名单；结果仅供人工审阅，入库仍需回测+审批。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DATA = REPO / "Data"
EVO = REPO / "evolution"

from fg_system import config  # noqa: E402
from fg_system.factors import eval as feval  # noqa: E402
from fg_system.factors import protocol as fproto  # noqa: E402

HORIZONS = (5, 10, 20, 40)
WINDOW = 60
N_BUCKETS = 5
FEE = fproto.DEFAULT_FEE


# ---------------------------------------------------------------- 数据加载

def _load(path):
    return pd.read_csv(path, parse_dates=["date"])


def _close(df, symbol):
    s = df[df["symbol"] == symbol].set_index("date")["close"].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def _daily(s, ref_index):
    """对齐到目标交易日并前向填充（仅用于低频日频因子如 F-007/F-010）。"""
    return s.reindex(ref_index).ffill()


# ---------------------------------------------------------------- 因子信号构造（纯函数，测试可 import）

def factor_f007_market_temperature(shoutu_df, ref_index):
    """F-007 守猪待兔市场温度：跨标的 value 日均值 → 日频信号（逆向：温度越高越贪婪）。"""
    if shoutu_df is None or len(shoutu_df) == 0 or "value" not in shoutu_df.columns:
        return pd.Series(dtype=float)
    mkt = shoutu_df.groupby("date")["value"].mean().sort_index()
    return _daily(mkt, ref_index)


def factor_f009_funding(funding_df):
    """F-009 OKX 资金费率：funding_btc → 信号（逆向：费率极端→反转）。样本仅数日，如实报告。"""
    if funding_df is None or len(funding_df) == 0 or "funding_btc" not in funding_df.columns:
        return pd.Series(dtype=float)
    s = funding_df.set_index("date")["funding_btc"].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def factor_f010_news(news_df, ref_index, score_col="mkt_score"):
    """F-010 新闻情绪：大盘净情绪分 mkt_score → 日频信号（正向）。"""
    if news_df is None or len(news_df) == 0 or score_col not in news_df.columns:
        return pd.Series(dtype=float)
    s = news_df.set_index("date")[score_col].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return _daily(s, ref_index)


def factor_f011_putcall(putcall_df, ratio_col="total_ratio"):
    """F-011 Put-Call 情绪：CBOE 总 P/C ratio → 信号（逆向：P/C 高→恐慌→反弹）。

    不 ffill：日频完整序列，ffill 会产生大段恒定值致滚动窗零方差（factor_screen_extend 实测）。
    """
    if putcall_df is None or len(putcall_df) == 0:
        return pd.Series(dtype=float)
    col = ratio_col if ratio_col in putcall_df.columns else (
        "putcall_total" if "putcall_total" in putcall_df.columns else None)
    if col is None:
        return pd.Series(dtype=float)
    s = putcall_df.set_index("date")[col].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def factor_f013_stablecoin_usage(usage_df, ref_index=None, col="usage_30d"):
    """F-013 稳定币使用效率（M2.4）：usage_30d → 日频信号（正向）。

    不 ffill：低频日频序列缺失即缺失（样本不足如实报告，滚动窗避免零方差）。
    """
    if usage_df is None or len(usage_df) == 0 or col not in usage_df.columns:
        return pd.Series(dtype=float)
    s = usage_df.set_index("date")[col].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if ref_index is not None:
        return s.reindex(ref_index)
    return s


# ---------------------------------------------------------------- 报告渲染

def _fmt(x, nd=3, suf=""):
    return f"{x:+.3f}" if isinstance(x, float) and not np.isnan(x) else "—"


def _fmt_pct(x):
    return f"{x*100:.1f}%" if isinstance(x, float) and not np.isnan(x) else "—"


def _report_md(report, include_layers=True):
    """单因子报告 → markdown 行（紧凑）。"""
    lines = []
    v = report["verdict"]
    status = v["status"] if v else "样本不足"
    head = (f"## {report['factor_id']} {report.get('name','')} → {report['target']} "
            f"（{report['direction']}）  **{status}**")
    if report["n_days"] == 0:
        return [head, "- 样本 0，无评测。"]
    lines.append(f"{head}\n- 样本：{report['n_days']} 交易日（{report['sample_start']} → {report['sample_end']}）")
    lines.append("")
    lines.append("| horizon | Pearson IC | ICIR | RankIC | RankICIR | n | 近窗 RankICIR | 顶底差 | 单调性 | 多空年化 | 多空回撤 | 含成本年化 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for h in HORIZONS:
        ic = report["ic"].get(h, {})
        rec = report["recent"].get(h, {})
        lay = (report["layers"].get(h) or {})
        ls = report["long_short"].get(h)
        lines.append(
            f"| {h} | {_fmt(ic.get('pearson_ic_mean'))} | {_fmt(ic.get('pearson_icir'),2)} "
            f"| {_fmt(ic.get('rank_ic_mean'))} | {_fmt(ic.get('rank_icir'),2)} "
            f"| {ic.get('n') or 0} | {_fmt((rec or {}).get('icir'),2)} "
            f"| {_fmt_pct(lay.get('top_minus_bottom')) if lay else '—'} "
            f"| {_fmt(lay.get('monotonic_spearman'),2) if lay else '—'} "
            f"| {_fmt_pct(ls.get('annualized')) if ls else '—'} "
            f"| {_fmt_pct(ls.get('max_dd')) if ls else '—'} "
            f"| {_fmt_pct(ls.get('annualized_net')) if ls else '—'} |")
    if v:
        lines += ["", f"> 判定：{v['detail']}"]
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="R1.1 因子评测协议（Qlib 蓝图）")
    ap.add_argument("--factors-only", action="store_true",
                    help="只跑候选+生产因子（不跑观察池 legacy）")
    args = ap.parse_args(argv)

    prices = _load(DATA / "raw" / "prices.csv")
    features = _load(config.FEATURES_PATH)
    spy = _close(prices, "SPY")

    # ---- 因子信号装配
    units = []
    # 生产六因子（features 0-100 因子分，目标 SPY；高分=贪婪→未来跌→全部逆向）
    for col in ("vix", "term", "price", "breadth", "fed", "putcall"):
        s = features.set_index("date")[col].astype(float)
        s = s[~s.index.duplicated(keep="last")].sort_index().dropna()
        units.append({"factor_id": f"prod-{col}", "name": f"生产因子 {col}（0-100）",
                      "signal": s, "target": "SPY", "direction": "逆向",
                      "close": spy})
    # F-007 守猪待兔市场温度
    sf = _load(DATA / "raw" / "shoutu_fng.csv")
    units.append({"factor_id": "F-007", "name": "守猪待兔市场温度（跨标的日均值）",
                  "signal": factor_f007_market_temperature(sf, spy.index),
                  "target": "SPY", "direction": "逆向", "close": spy})
    # F-009 资金费率（样本不足如实报告；无 BTC 价格序列 → 目标仍标 SPY 但不评测）
    fr = _load(DATA / "raw" / "funding_rate.csv")
    f9 = factor_f009_funding(fr)
    units.append({"factor_id": "F-009", "name": "OKX 资金费率（funding_btc）",
                  "signal": f9, "target": "BTC（无价格序列→仅样本报告）",
                  "direction": "逆向", "close": pd.Series(dtype=float)})
    # F-010 新闻情绪
    ns = _load(DATA / "raw" / "news_sentiment.csv")
    units.append({"factor_id": "F-010", "name": "新闻情绪（mkt_score）",
                  "signal": factor_f010_news(ns, spy.index),
                  "target": "SPY", "direction": "正向", "close": spy})
    # F-011 Put-Call（putcall.csv total_ratio；IC 实测为正：P/C 高=恐慌→未来涨→正向）
    pc = _load(DATA / "raw" / "putcall.csv")
    units.append({"factor_id": "F-011", "name": "Put-Call（total_ratio）",
                  "signal": factor_f011_putcall(pc),
                  "target": "SPY", "direction": "正向", "close": spy})
    # F-013 稳定币使用效率（M2.4；H-030 背离先验：使用效率升→贪婪虚高→后续跌；首检 IC 全负）
    su = _load(DATA / "raw" / "stablecoin_usage.csv")
    units.append({"factor_id": "F-013", "name": "稳定币使用效率（usage_30d）",
                  "signal": factor_f013_stablecoin_usage(su, spy.index),
                  "target": "SPY", "direction": "逆向", "close": spy})

    reports = []
    out = ["# 因子评测协议报告（R1.1 · Qlib 蓝图）", "",
           f"- 生成：{datetime.now().strftime('%Y-%m-%d %H:%M')} · scripts/factor_screen.py",
           "- 口径：IC=Pearson 滚动相关（window=60）；RankIC=Spearman；",
           "  分层=信号 756 日滚动分位 5 桶（无前视）；多空=顶桶做多−底桶做空（非重叠调仓）；",
           f"  含成本=每期扣 2×{FEE}（单边 10bp）；门槛 |ICIR|≥0.5 且 n≥60 且近窗无衰减。",
           "- 数据：prices.csv（SPY）、features.csv、shoutu_fng.csv、funding_rate.csv、",
           "  news_sentiment.csv、putcall.csv。", ""]

    # 候选 + 生产因子
    out.append("## 一、候选因子（F 系列）")
    for u in units:
        rep = fproto.screen_report(u["signal"], u["close"], factor_id=u["factor_id"],
                                   target=u["target"], direction=u["direction"],
                                   horizons=HORIZONS, window=WINDOW,
                                   n_buckets=N_BUCKETS, fee=FEE)
        # F-009：无 BTC 价格序列 → 保留信号样本窗口如实报告（不评测）
        if u["factor_id"] == "F-009" and len(u["signal"]) and rep["n_days"] == 0:
            sig = u["signal"].dropna()
            rep["n_days"] = int(len(sig))
            rep["sample_start"] = sig.index.min().strftime("%Y-%m-%d")
            rep["sample_end"] = sig.index.max().strftime("%Y-%m-%d")
            rep["verdict"] = {"status": "accumulating",
                              "detail": "目标 BTC 无价格序列（prices.csv 无 BTC），仅报告样本窗口，IC/IR 待数据到位后评测",
                              "best_horizon": None, "passed": []}
        rep["name"] = u["name"]
        reports.append(rep)
        out += _report_md(rep)
        out.append("")
    out.append("## 二、生产因子（features 0-100 因子分）")
    for u in units:
        if not u["factor_id"].startswith("prod-"):
            continue
        rep = fproto.screen_report(u["signal"], u["close"], factor_id=u["factor_id"],
                                   target=u["target"], direction=u["direction"],
                                   horizons=HORIZONS, window=WINDOW,
                                   n_buckets=N_BUCKETS, fee=FEE)
        rep["name"] = u["name"]
        reports.append(rep)
        out += _report_md(rep)
        out.append("")

    # 观察池 legacy（fg_index × OBSERVE_SYMBOLS，兼容旧报告）
    if not args.factors_only:
        out.append("## 三、观察池 legacy（系统 fg_index × 观察池标的）")
        signal = features.dropna(subset=["fg_index"]).set_index("date")["fg_index"].astype(float)
        for sym in config.OBSERVE_SYMBOLS:
            c = _close(prices, sym)
            if len(c) == 0:
                out += [f"### {sym}", "- 无价格数据，跳过。", ""]
                continue
            rep = fproto.screen_report(signal, c, factor_id=f"fg_index×{sym}",
                                       target=sym,
                                       direction="正向" if sym == "SQQQ" else "逆向",
                                       horizons=HORIZONS, window=WINDOW,
                                       n_buckets=N_BUCKETS, fee=FEE)
            rep["name"] = "系统市场级指数"
            reports.append(rep)
            out += _report_md(rep)
            out.append("")

    out += ["---", "> 由 scripts/factor_screen.py 生成 · 只读取证，未改策略、未进白名单；",
            "> 结果仅供人工审阅，入库仍需回测+审批。"]
    text = "\n".join(out)
    print(text)

    md_path = EVO / "factor-screen-results.md"
    md_path.write_text(text + "\n", encoding="utf-8")
    json_path = EVO / "factor-screen-results.json"
    json_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    print(f"\n[factor_screen] md → {md_path}\n[factor_screen] json → {json_path}")


if __name__ == "__main__":
    sys.exit(main())
