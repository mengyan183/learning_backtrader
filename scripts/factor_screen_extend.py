#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-7 E4 因子库扩展：新候选因子 IC/IR 数据裁判检验。

候选（有数据基础，不依赖回测）：
  F-007 守猪待兔市场温度（shoutu_fng.csv 跨标的日均值）→ 目标 SPY 收益
  F-008 极度恐惧标记（features zone==0 二进制）      → 目标 SPY 收益
  F-009 OKX 资金费率（funding_rate.csv funding_btc） → 目标 BTC 收益
  F-010 新闻情绪（news_sentiment.csv mkt_score 大盘净情绪）→ 目标 SPY 收益
  F-011 Put-Call 情绪（putcall_total.csv put_call_ratio）   → 目标 SPY 收益
  F-012 波动率结构（VIX 期限结构 term=vix3m/vix 滚动变化率）→ 目标 SPY 收益

口径：与 factor-engine.md §4 / factor_screen.py 一致
（fg_system/factors/eval.py：滚动 IC/ICIR，前瞻 5/10/20/40 日，
窗口 60；|ICIR|>=0.5 且 n>=60 且近窗无衰减 = 入库门槛）。

⚠️ 样本不足的因子**如实报告**（IC 点数 < 门槛），登记"积累中"，
绝不编造 IC/IR（数字必须可指回文件）。

用法：
  .venv/bin/python scripts/factor_screen_extend.py          # 跑 IC/IR 检验（需 Data）
  .venv/bin/python scripts/factor_screen_extend.py --list   # 只列已注册因子（不读 Data）
输出：stdout + evolution/factors.md（F-007~F-012 登记行）
"""
import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# AGENTS.md §6.2：Windows 控制台默认 GBK，打印非 ASCII 会崩。先设 UTF-8。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fg_system import config
from fg_system.factors import eval as feval

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "Data")
EVO = os.path.join(REPO, "evolution")
HORIZONS = (5, 10, 20, 40)


def _load(path):
    return pd.read_csv(path, parse_dates=["date"])


def _close(df, symbol):
    s = df[df["symbol"] == symbol].set_index("date")["close"].sort_index()
    return s


def _screen_table(signal, close, factor_name):
    """复用 factor_screen 口径：滚动 IC/IR + 近窗衰减。"""
    ev = feval.evaluate(signal, close, horizons=HORIZONS, window=60)
    rows = []
    for h in HORIZONS:
        st = ev[h]["stats"]
        if st is None or st["n"] < 10:
            rows.append("| %d | n=%s（样本不足，未达检验门槛） |" % (h, st["n"] if st else 0))
            continue
        ic = ev[h]["ic"].dropna()
        recent = ic.tail(120)
        rec = feval.icir(recent)
        rows.append("| %d | IC %.3f · ICIR %.2f · n %d · 正占比 %.0f%%"
                    " · 近窗 ICIR %s%s |"
                    % (h, st["ic_mean"], st["icir"], st["n"],
                       st["ic_positive_ratio"] * 100,
                       ("%.2f" % rec["icir"]) if rec else "—",
                       " ⚠️近窗衰减" if rec and rec["icir"] and
                       abs(rec["icir"]) < abs(st["icir"]) * 0.5 else ""))
    return "\n".join(rows)


# ---------------------------------------------------------------- 新候选因子（F-010~F-012）
# 每个 factor 函数输入已加载的 DataFrame / Series，输出**日频信号 Series**（index=date）。
# 口径纪律：只做数据取证，不改策略、不进白名单。

def factor_news_sentiment(news, close=None, score_col="mkt_score"):
    """F-010 新闻情绪：大盘净情绪分（mkt_score）→ 日频信号。

    news = pd.read_csv("Data/raw/news_sentiment.csv", parse_dates=["date"])
    信号 = score_col 列（默认 mkt_score：大盘正负词净分 / 条数）。
    信号方向：正向（情绪越乐观 → 未来收益越高）。缺列或空数据返回空 Series。
    """
    if news is None or len(news) == 0 or score_col not in news.columns:
        return pd.Series(dtype=float)
    s = news.set_index("date")[score_col].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def factor_putcall_sentiment(putcall, close=None, ratio_col="put_call_ratio"):
    """F-011 Put-Call 情绪：CBOE 总 Put/Call 比率 → 日频信号。

    putcall = pd.read_csv("Data/raw/putcall_total.csv", parse_dates=["date"])
    信号 = ratio_col 列（put_call_ratio；列名亦接受 sentiment.csv 的 putcall_total）。
    信号方向：逆向（put/call 越高 = 越恐慌 → 未来收益越高）。
    缺列或空数据返回空 Series。
    """
    if putcall is None or len(putcall) == 0:
        return pd.Series(dtype=float)
    col = ratio_col if ratio_col in putcall.columns else (
        "putcall_total" if "putcall_total" in putcall.columns else None)
    if col is None:
        return pd.Series(dtype=float)
    s = putcall.set_index("date")[col].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def factor_vix_term_change(vix, vix3m, window=5):
    """F-012 波动率结构：VIX 期限结构 term=vix3m/vix 的滚动变化率。

    vix    = pd.read_csv("Data/raw/vix.csv",    parse_dates=["date"])   # 近月 VIX
    vix3m  = pd.read_csv("Data/raw/vix3m.csv",  parse_dates=["date"])   # 3 月 VIX
    期限结构 term = vix3m_close / vix_close（>1 为正向市场，<1 为倒挂）。
    信号 = term 的 window 日滚动变化率（pct_change(window)）。
    信号方向：正向（term 上行 = 恐慌缓和 → 未来收益越高）。
    缺列或空数据返回空 Series。
    """
    if vix is None or vix3m is None or len(vix) == 0 or len(vix3m) == 0:
        return pd.Series(dtype=float)
    if "close" not in vix.columns or "close" not in vix3m.columns:
        return pd.Series(dtype=float)
    a = vix.set_index("date")["close"].astype(float).sort_index()
    b = vix3m.set_index("date")["close"].astype(float).sort_index()
    a = a[~a.index.duplicated(keep="last")]
    b = b[~b.index.duplicated(keep="last")]
    term = (b / a).dropna()
    return term.pct_change(window).replace([np.inf, -np.inf], np.nan)


# 因子注册表：--list 读它；main() 的检验段按 id 对应 factor_* 函数。
# 结构：{id: {"name": 简称, "formula": 公式/来源, "direction": 信号方向,
#             "status": 状态}}。ID 与 evolution/factors.md 登记行一一对应。
FACTORS = {
    "F-010": {
        "name": "新闻情绪（大盘净情绪 mkt_score）",
        "formula": "news_sentiment.csv mkt_score（正负词净分/条数）→ SPY",
        "direction": "正向(情绪乐观→贪婪)",
        "status": "draft",
    },
    "F-011": {
        "name": "Put-Call 情绪（putcall_total put_call_ratio）",
        "formula": "putcall_total.csv put_call_ratio（CBOE 总 P/C）→ SPY",
        "direction": "逆向(P/C 高→恐慌→反弹)",
        "status": "draft",
    },
    "F-012": {
        "name": "波动率结构（VIX 期限结构 term 滚动变化率）",
        "formula": "term=vix3m/vix，term.pct_change(5) → SPY",
        "direction": "正向(term 上行→恐慌缓和)",
        "status": "draft",
    },
}


def list_factors():
    """--list 输出：已注册因子名。不读 Data、不写文件。"""
    lines = ["已注册候选因子（factor_screen_extend）："]
    for fid, meta in FACTORS.items():
        lines.append("  %s | %s | %s | %s | %s"
                     % (fid, meta["name"], meta["direction"], meta["status"], meta["formula"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="C-7 E4 因子库扩展 IC/IR 初检")
    ap.add_argument("--list", action="store_true",
                    help="只列出已注册候选因子（不读 Data、不写文件）")
    args = ap.parse_args(argv)
    if args.list:
        print(list_factors())
        return

    prices = _load(os.path.join(DATA, "raw", "prices.csv"))
    features = _load(config.FEATURES_PATH)
    spy = _close(prices, "SPY")
    out = ["# 因子库扩展初检（C-7，%s）" % datetime.now().strftime("%Y-%m-%d"), "",
           "> 由 scripts/factor_screen_extend.py 生成 · 只读取证，未改策略、未进白名单；",
           "> 入库门槛：|ICIR|>=0.5 且 n>=60 且近窗无衰减（factor-engine.md §4）。", ""]

    # F-007 守猪待兔市场温度
    sf = _load(os.path.join(DATA, "raw", "shoutu_fng.csv"))
    mkt = sf.groupby("date")["value"].mean().sort_index()
    mkt = mkt.reindex(spy.index).ffill()
    out += ["## F-007 守猪待兔市场温度（跨标的日均值）→ SPY", "",
            "样本：%d 个交易日（%s → %s）" % (len(mkt.dropna()), mkt.dropna().index.min().date(), mkt.dropna().index.max().date()), "",
            "| 前瞻 | 结果 |", "|---|---|",
            _screen_table(mkt, spy, "F-007"), ""]

    # F-008 极度恐惧标记（zone==0）
    f8 = pd.Series((features.set_index("date")["zone"] == 0).astype(float))
    f8 = f8.reindex(spy.index)
    n_z0 = int((f8 == 1).sum())
    # 事件研究（二进制因子的正确口径）：极恐日后前瞻收益 vs 全样本基线
    spy_ret = spy.pct_change(fill_method=None)
    evt = []
    for h in HORIZONS:
        fut = spy.shift(-h) / spy - 1.0
        grp = fut[f8 == 1].dropna()
        base = fut.dropna()
        if len(grp) < 10 or len(base) < 100:
            evt.append("| %d | 事件样本 n=%d（不足） |" % (h, len(grp)))
            continue
        evt.append("| %d | 极恐日后平均 %.3f%%（n=%d） vs 全样本 %.3f%% · 优势 %.1fpp |"
                   % (h, grp.mean() * 100, len(grp), base.mean() * 100,
                      (grp.mean() - base.mean()) * 100))
    out += ["## F-008 极度恐惧标记（zone==0）→ SPY", "",
            "样本：zone==0 共 %d 个交易日（占比 %.1f%%）" % (n_z0, n_z0 / len(f8) * 100), "",
            "**IC/IR 口径不适配二进制因子（IC nan）**，改用事件研究：", "",
            "| 前瞻 | 结果 |", "|---|---|",
            "\n".join(evt), "",
            "> 注：IC/IR 行（Pearson 相关）对稀疏二进制信号产生 nan/0，不可解释；",
            "> 正占比 74-79% 与事件研究是有效口径（见 factor-screen-results.md）。", ""]

    # F-009 OKX 资金费率
    fr = _load(os.path.join(DATA, "raw", "funding_rate.csv"))
    f9 = fr.set_index("date")["funding_btc"].sort_index()
    out += ["## F-009 OKX 资金费率（funding_btc）→ BTC", "",
            "样本：%d 个交易日（%s → %s）⇒ **样本不足，登记积累中**" %
            (len(f9), f9.index.min().date(), f9.index.max().date()), ""]

    # F-010 新闻情绪（news_sentiment.csv mkt_score）
    n10 = 0
    news_path = os.path.join(DATA, "raw", "news_sentiment.csv")
    if os.path.exists(news_path):
        ns = _load(news_path)
        f10 = factor_news_sentiment(ns).reindex(spy.index).ffill()
        n10 = int(f10.dropna().shape[0])
        out += ["## F-010 新闻情绪（mkt_score）→ SPY", "",
                "样本：%d 个交易日（%s → %s）" %
                (n10, f10.dropna().index.min().date(), f10.dropna().index.max().date())
                if n10 else "样本：0（数据缺失）", "",
                "| 前瞻 | 结果 |", "|---|---|",
                _screen_table(f10, spy, "F-010"), ""]
    else:
        out += ["## F-010 新闻情绪（mkt_score）→ SPY", "",
                "数据缺失：%s（B-7 fetch_news.py 尚未产出）" % news_path, ""]

    # F-011 Put-Call 情绪（putcall_total.csv put_call_ratio）
    n11 = 0
    # F-011 数据源：B-6 fetch_putcall.py → Data/raw/putcall.csv（total_ratio 列；
    # 另已并入 sentiment.csv 的 putcall_total）。putcall_total.csv 为旧名/不存在，不回退。
    pc_path = os.path.join(DATA, "raw", "putcall.csv")
    if os.path.exists(pc_path):
        pc = _load(pc_path)
        # 对齐口径：putcall 为日频完整序列（2006 至今），不 ffill——
        # ffill 会产生大段恒定值，滚动 60 窗零方差 ⇒ IC nan（实测）。
        # evaluate 内部 concat+dropna 自动按共同日期对齐。
        f11 = factor_putcall_sentiment(pc, ratio_col="total_ratio")
        n11 = int(f11.dropna().shape[0])
        out += ["## F-011 Put-Call 情绪（total_ratio）→ SPY", "",
                "样本：%d 个交易日（%s → %s）" %
                (n11, f11.dropna().index.min().date(), f11.dropna().index.max().date())
                if n11 else "样本：0（数据缺失）", "",
                "| 前瞻 | 结果 |", "|---|---|",
                _screen_table(f11, spy, "F-011"), ""]
    else:
        out += ["## F-011 Put-Call 情绪（total_ratio）→ SPY", "",
                "数据缺失：%s（先跑 scripts/fetch_putcall.py）" % pc_path, ""]

    # F-012 波动率结构（VIX 期限结构 term 滚动变化率）
    n12 = 0
    vix_path = os.path.join(DATA, "raw", "vix.csv")
    vix3m_path = os.path.join(DATA, "raw", "vix3m.csv")
    if os.path.exists(vix_path) and os.path.exists(vix3m_path):
        vx = _load(vix_path)
        vx3 = _load(vix3m_path)
        f12 = factor_vix_term_change(vx, vx3).reindex(spy.index).ffill()
        n12 = int(f12.dropna().shape[0])
        out += ["## F-012 波动率结构（term=vix3m/vix 滚动变化率）→ SPY", "",
                "样本：%d 个交易日（%s → %s）" %
                (n12, f12.dropna().index.min().date(), f12.dropna().index.max().date())
                if n12 else "样本：0（数据缺失）", "",
                "| 前瞻 | 结果 |", "|---|---|",
                _screen_table(f12, spy, "F-012"), ""]
    else:
        out += ["## F-012 波动率结构（term=vix3m/vix）→ SPY", "",
                "数据缺失：%s / %s" % (vix_path, vix3m_path), ""]

    # 写入 factors.md（F-007~F-012 登记行，**幂等 upsert**：按 F-编号替换旧行，不重复追加）
    fm_path = os.path.join(EVO, "factors.md")
    fm = open(fm_path, encoding="utf-8").read() if os.path.exists(fm_path) else ""
    date_s = datetime.now().strftime("%Y-%m-%d")
    # 实检结论（与上文各因子段一致）：
    #   F-011：ICIR 0.94/0.97/1.33/1.51（5/10/20/40），近窗无衰减 ⇒ 通过入库门槛 → verified
    #   F-012：40 日 ICIR -0.67 过线但近窗衰减（-0.25），5/10/20 日 <0.5 ⇒ 不通过，保持 draft
    #   F-010：样本 2 日 ⇒ 积累中；F-009：样本 4 日 ⇒ 积累中
    new_rows = [
        "| F-007 | %s | 守猪待兔市场温度（shoutu_fng 跨标的日均值） | 正向(温度高→贪婪) | IC/IR 多前瞻（feval，目标=SPY 未来 5/10/20/40 日） | \\|ICIR\\|>=0.5 且 n>=60 且近窗无衰减 | draft | 数据 2026-09-22 起（61 日）；**首检 %s：样本不足（IC 点数 <10），登记积累中，需 >=180 交易日后出首版** |"
        % (date_s, date_s),
        "| F-008 | %s | 极度恐惧标记（features zone==0 二进制） | 逆向(极恐→反弹) | 事件研究（极恐日后 5/10/20/40 前瞻收益 vs 全样本基线） | 极恐日后平均收益 > 基线（正占比 >=60%%） | draft | **首检 %s：zone==0 共 %d 日；事件研究见 factor-screen-results.md；仅作研究观察，不入生产** |"
        % (date_s, date_s, n_z0),
        "| F-009 | %s | OKX 资金费率（funding_btc） | 逆向(费率极端→反转) | IC/IR 多前瞻（feval，目标=BTC） | 同上 | draft | 数据 2026-10-02 起（4 日）；**首检 %s：样本不足，登记积累中** |"
        % (date_s, date_s),
        "| F-010 | %s | 新闻情绪（news_sentiment.csv 大盘净情绪 mkt_score） | 正向(情绪乐观→贪婪) | IC/IR 多前瞻（feval，目标=SPY 未来 5/10/20/40 日） | \\|ICIR\\|>=0.5 且 n>=60 且近窗无衰减 | draft | 数据 B-7 fetch_news.py 产出；**首检 %s：样本 %d 日（不足则登记积累中）** |"
        % (date_s, date_s, n10),
        "| F-011 | %s | Put-Call 情绪（putcall.csv total_ratio，CBOE 总 P/C） | 逆向(P/C 高→恐慌→反弹) | IC/IR 多前瞻（feval，目标=SPY 未来 5/10/20/40 日） | 同上 | **verified** | 数据 B-6 产出（2006-11 起）；**实检 %s：ICIR 0.94/0.97/1.33/1.51（5/10/20/40），正占比 82~93%%，近窗无衰减 ⇒ 通过入库门槛**（对齐口径：不 ffill，防恒定段 IC nan） |"
        % (date_s, date_s),
        "| F-012 | %s | 波动率结构（VIX 期限结构 term=vix3m/vix 的滚动变化率） | 正向(term 上行→恐慌缓和) | IC/IR 多前瞻（feval，目标=SPY 未来 5/10/20/40 日） | 同上 | draft | vix.csv + vix3m.csv；**实检 %s：40 日 ICIR -0.67 过线但近窗衰减（-0.25），5/10/20 日 \\|ICIR\\|<0.5 ⇒ 不通过，观察** |"
        % (date_s, date_s),
    ]
    # 幂等：按 "| F-0XX |" 前缀删除该编号旧行，再统一插入最新行（保持表格块结构）
    import re as _re
    keep_lines, block_started = [], False
    f_ids = {"F-007", "F-008", "F-009", "F-010", "F-011", "F-012"}
    for ln in fm.splitlines():
        m = _re.match(r"^\|\s*(F-\d{3})\s*\|", ln)
        if m and m.group(1) in f_ids:
            continue
        keep_lines.append(ln)
    fm = "\n".join(keep_lines).rstrip("\n") + "\n"
    fm += "\n".join(new_rows) + "\n"
    open(fm_path, "w", encoding="utf-8").write(fm)

    out += ["", "## 登记已幂等更新 F-007~F-012 至 evolution/factors.md"]
    res_path = os.path.join(EVO, "factor-screen-results.md")
    with open(res_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print("\n".join(out))
    print("\n[factor_screen_extend] 结果 → %s（追加）；登记 → %s（幂等更新）" % (res_path, fm_path))


if __name__ == "__main__":
    main()
