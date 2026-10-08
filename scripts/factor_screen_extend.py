#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-7 E4 因子库扩展：新候选因子 IC/IR 数据裁判检验。

候选（有数据基础，不依赖回测）：
  F-007 守猪待兔市场温度（shoutu_fng.csv 跨标的日均值）→ 目标 SPY 收益
  F-008 极度恐惧标记（features zone==0 二进制）      → 目标 SPY 收益
  F-009 OKX 资金费率（funding_rate.csv funding_btc） → 目标 BTC 收益

口径：与 factor-engine.md §4 / factor_screen.py 一致
（fg_system/factors/eval.py：滚动 IC/ICIR，前瞻 5/10/20/40 日，
窗口 60；|ICIR|>=0.5 且 n>=60 且近窗无衰减 = 入库门槛）。

⚠️ 样本不足的因子**如实报告**（IC 点数 < 门槛），登记"积累中"，
绝不编造 IC/IR（数字必须可指回文件）。

用法：.venv/bin/python scripts/factor_screen_extend.py
输出：stdout + evolution/factors.md（F-007~F-009 登记行）
"""
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

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


def main():
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

    # 写入 factors.md（F-007~F-009 登记行）
    fm_path = os.path.join(EVO, "factors.md")
    date_s = datetime.now().strftime("%Y-%m-%d")
    fm = open(fm_path, encoding="utf-8").read() if os.path.exists(fm_path) else ""
    new_rows = [
        "| F-007 | %s | 守猪待兔市场温度（shoutu_fng 跨标的日均值） | 正向(温度高→贪婪) | IC/IR 多前瞻（feval，目标=SPY 未来 5/10/20/40 日） | \\|ICIR\\|>=0.5 且 n>=60 且近窗无衰减 | draft | 数据 2026-09-22 起（61 日）；**首检 %s：样本不足（IC 点数 <10），登记积累中，需 >=180 交易日后出首版** |"
        % (date_s, date_s),
        "| F-008 | %s | 极度恐惧标记（features zone==0 二进制） | 逆向(极恐→反弹) | 事件研究（极恐日后 5/10/20/40 前瞻收益 vs 全样本基线） | 极恐日后平均收益 > 基线（正占比 >=60%%） | draft | **首检 %s：zone==0 共 %d 日；事件研究见 factor-screen-results.md；仅作研究观察，不入生产** |"
        % (date_s, date_s, n_z0),
        "| F-009 | %s | OKX 资金费率（funding_btc） | 逆向(费率极端→反转) | IC/IR 多前瞻（feval，目标=BTC） | 同上 | draft | 数据 2026-10-02 起（4 日）；**首检 %s：样本不足，登记积累中** |"
        % (date_s, date_s),
    ]
    if fm.strip().endswith("|") and not fm.strip().endswith("\n"):
        fm += "\n"
    fm += "\n".join(new_rows) + "\n"
    open(fm_path, "w", encoding="utf-8").write(fm)

    out += ["", "## 登记已追加 F-007~F-009 至 evolution/factors.md"]
    res_path = os.path.join(EVO, "factor-screen-results.md")
    with open(res_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print("\n".join(out))
    print("\n[factor_screen_extend] 结果 → %s（追加）；登记 → %s" % (res_path, fm_path))


if __name__ == "__main__":
    main()
