#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""杠杆 ETF 建仓 / 加仓计划的回测（2026-10-30）。

【为什么】`fg_system/position_plan.py` 的参数是「有道理」而非「验证过」✗ ——
12% / 20% / 6%+3%+3% 这些数字来自回本数学与纪律约束的推理，没有历史支撑 ✗。
本脚本把同一套规则放到历史上跑，比较不同参数组的收益 / 回撤 / 单标的最大亏损 ✓。

【口径】
- 单标的**独立**回测（每个标的各自一份预算），最后按等权汇总 ✓
- 成交价用当日收盘 ✓（忽略滑点与手续费 —— 对**相对比较**影响很小 ✓）
- 退出：守猪待兔系数 ≥ `shoutu_lines()` 的卖出线 ⇒ 清仓 ✓
- 相邻两次操作间隔 ≥ `min_gap_days` 个交易日 ✓（纪律 5.1）
- 样本外：按时间 70/30 切分，两段分别出指标 ✓（纪律第 8 条要求）

【用法】
    py -3.10 scripts/backtest_position_plan.py
    py -3.10 scripts/backtest_position_plan.py --json evolution/plan-backtest.json
"""
import argparse
import json
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system import config  # noqa: E402
from fg_system import position_plan as pp  # noqa: E402
from fg_system import risk as risk_mod  # noqa: E402

#: 回测标的 —— **排除 AXTX / CRCG** ✓（用户 2026-10-30 裁定）。
#: 理由：守猪待兔服务端对这两个返回 `data: []`（无历史）✗，
#: 本地只有 13 天样本 ⇒ 结论是噪声 ✗。
#: BTC 也没有守猪待兔系数 ✗（现货，不在该体系内）⇒ 一并排除。
#: 要扩样本可加同类：`--symbols YINN,GDXU,CONL,TQQQ,SOXL,UPRO`（后三个也有 600 天 ✓）
SYMBOLS = ["YINN", "GDXU", "CONL"]

#: 净值基准（归一化，只影响绝对金额不影响收益率 ✓）
NET = 10000.0

#: 变体参数 —— 与 `position_plan.PLAN` 同构，便于横向比较 ✓
VARIANTS = {
    "A_初版": {"single_cap": 0.12, "first": 0.06, "adds": (0.03, 0.03),
               "entry": -80.0, "hard_stop": -0.50, "atr_k": 1.5,
               "gap_mode": "atr"},
    "B_保守": {"single_cap": 0.08, "first": 0.04, "adds": (0.02, 0.02),
               "entry": -85.0, "hard_stop": -0.40, "atr_k": 2.0,
               "gap_mode": "atr"},
    "C_激进": {"single_cap": 0.15, "first": 0.08, "adds": (0.04, 0.03),
               "entry": -75.0, "hard_stop": -0.60, "atr_k": 1.2,
               "gap_mode": "atr"},
    # 2026-10-30 第一轮回测后的候选 ✓ —— C 的入场线（-75）+ A 的敞口（12%）
    "E_候选": {"single_cap": 0.12, "first": 0.06, "adds": (0.03, 0.03),
               "entry": -75.0, "hard_stop": -0.50, "atr_k": 1.5,
               "gap_mode": "atr"},
    # 对照组：复现「越跌越买、不止损、等额加仓」（用户 2026-10-30 反思的做法 ✗）
    "D_对照": {"single_cap": 0.20, "first": 0.06,
               "adds": (0.03, 0.03, 0.03, 0.03), "entry": -70.0,
               "hard_stop": None, "atr_k": 0.0,
               "gap_mode": "fixed", "gap_fixed": 10.0},
}


def _load():
    """读价格（长表）+ 守猪待兔系数 ✓。

    🔴 2026-10-30 修正（第一次回测跑空的根因 ✗）：
    原来只读 `shoutu_fng.csv`（**本地 06:30 采样**，只有近期几十天 ✗）
    ⇒ 10 年区间只交易 5 次、平均持仓 0.2% ✗，结论无效 ✗。
    正解：优先 `shoutu_history.csv`（**服务端权威日值**，2024-04 起、
    每只 ~600 天 ✓，由 `scripts/fetch_shoutu_history.py` 抓）
    + `shoutu_fng.csv` 覆盖更新的日期（同 `(date,symbol)` 以 fng 为准 ✓）。
    """
    px = pd.read_csv(os.path.join(REPO, "Data", "raw", "prices.csv"),
                     parse_dates=["date"])
    frames = []
    hist_p = os.path.join(REPO, "Data", "raw", "shoutu_history.csv")
    fng_p = os.path.join(REPO, "Data", "raw", "shoutu_fng.csv")
    if os.path.exists(hist_p):
        h = pd.read_csv(hist_p, parse_dates=["date"])
        h = h.rename(columns={"score": "value"})[["date", "symbol", "value"]]
        frames.append(h)
    if os.path.exists(fng_p):
        f = pd.read_csv(fng_p, parse_dates=["date"])[["date", "symbol", "value"]]
        frames.append(f)
    if not frames:
        sys.exit("✗ 缺 shoutu_history.csv / shoutu_fng.csv ⇒ 无法回测"
                 "（这两个文件只在 Mac 本地 ✗）")
    st = pd.concat(frames, ignore_index=True)
    st["symbol"] = st["symbol"].astype(str).str.replace("-USDT", "", regex=False)
    # 同 (date, symbol) 以**后出现的为准** ⇒ fng（更近的采样）覆盖 history ✓
    st = st.dropna(subset=["value"]).drop_duplicates(
        subset=["date", "symbol"], keep="last")
    return px, st


def _series(px, sym):
    """单标的价格序列（收盘，按日期升序）✓。"""
    d = px[px["symbol"] == sym][["date", "close"]].dropna()
    return d.sort_values("date").set_index("date")["close"]


def _coef(st, sym):
    """守猪待兔系数序列 ✓。"""
    d = st[st["symbol"] == sym][["date", "value"]].dropna()
    return d.sort_values("date").set_index("date")["value"]


def _gap_pct(px, sym, v):
    """该标的的加仓间距（%）✓ —— `atr` 模式用正股 ATR，`fixed` 模式用固定值。"""
    if v["gap_mode"] == "fixed":
        return float(v.get("gap_fixed") or 10.0)
    und = risk_mod.atr_pct_underlying(px, sym)
    if und is None:
        return None
    return v["atr_k"] * und * pp.leverage_of(sym) * 100.0


def _simulate(px, st, sym, v, start=None, end=None):
    """单标的模拟 ✓ —— 返回权益曲线与成交记录。"""
    close = _series(px, sym)
    coef = _coef(st, sym)
    if close.empty:
        return None
    idx = close.index
    if start is not None:
        idx = idx[idx >= start]
    if end is not None:
        idx = idx[idx <= end]
    if len(idx) < 30:
        return None

    buy_line, sell_line = config.shoutu_lines(sym)
    gap = _gap_pct(px, sym, v)
    single = NET * v["single_cap"]

    cash = NET
    qty = 0.0
    cost = 0.0                 # 持仓成本（元）
    adds_done = 0
    last_buy_px = None
    last_op_i = -10 ** 6
    equity, trades = [], []

    for i, dt in enumerate(idx):
        px_now = float(close.loc[dt])
        c = coef.get(dt)
        c = None if pd.isna(c) else float(c)

        # 卖出：系数 ≥ 卖出线 ⇒ 清仓 ✓
        if qty > 0 and c is not None and c >= sell_line:
            cash += qty * px_now
            trades.append({"date": str(dt.date()), "side": "sell",
                           "px": round(px_now, 4), "qty": round(qty, 4),
                           "reason": "coef≥%.0f" % sell_line})
            qty, cost, adds_done, last_buy_px = 0.0, 0.0, 0, None

        # 建仓 / 加仓
        if c is not None and c <= v["entry"] and (i - last_op_i) >= 5:
            held = qty * px_now
            room = single - held
            if room > 1:
                pnl = ((px_now * qty - cost) / cost * 100.0) if cost > 0 else None
                blocked = (v["hard_stop"] is not None and pnl is not None
                           and pnl <= v["hard_stop"] * 100)
                if not blocked:
                    if qty == 0:
                        amt = min(NET * v["first"], room, cash)
                        ladder_ok = True
                    else:
                        n = adds_done
                        if n >= len(v["adds"]):
                            ladder_ok = False
                        else:
                            need = gap is not None and last_buy_px and \
                                (px_now / last_buy_px - 1) * 100 <= -(gap * (n + 1))
                            ladder_ok = bool(need)
                            amt = min(NET * v["adds"][n], room, cash) if ladder_ok else 0
                    was_add = qty > 0          # 🔴 必须在加仓前判断 ✗
                    if (qty == 0 and amt > 1) or (was_add and ladder_ok and amt > 1):
                        qty += amt / px_now
                        cost += amt
                        cash -= amt
                        last_buy_px = px_now
                        last_op_i = i
                        # 🔴 只有**加仓**才推进阶梯计数 ✓ —— 首建也 ++ 会让
                        # 第一档变成「跌 2 倍间距」才触发 ✗（测试抓到的真 bug ✓）
                        if was_add:
                            adds_done += 1
                        trades.append({"date": str(dt.date()),
                                       "side": "buy", "px": round(px_now, 4),
                                       "amt": round(amt, 2),
                                       "reason": "coef%.0f" % c})

        equity.append({"date": str(dt.date()), "eq": cash + qty * px_now,
                       "held": qty * px_now})

    if not equity:
        return None
    eq = pd.DataFrame(equity).set_index("date")
    ret = (eq["eq"].iloc[-1] - NET) / NET * 100.0
    peak = eq["eq"].cummax()
    mdd = float(((eq["eq"] - peak) / peak).min() * 100.0)
    buys = [t for t in trades if t["side"] == "buy"]
    return {"symbol": sym, "variant": None, "return_pct": round(ret, 2),
            "mdd_pct": round(mdd, 2), "n_ops": len(trades),
            "n_buys": len(buys), "max_held_pct": round(
                float(eq["held"].max()) / NET * 100.0, 1),
            "avg_held_pct": round(float(eq["held"].mean()) / NET * 100.0, 1),
            "final_eq": round(float(eq["eq"].iloc[-1]), 2)}


def _run(px, st, v, start=None, end=None, label=""):
    """跑一组参数 ✓ —— 返回逐标的 + 汇总。"""
    rows = [r for r in (_simulate(px, st, s, v, start, end) for s in SYMBOLS) if r]
    if not rows:
        return None
    rets = [r["return_pct"] for r in rows]
    return {
        "variant": label,
        "symbols": rows,
        "n_symbols": len(rows),
        # 等权汇总：每个标的独立预算 ⇒ 总收益 = 各标的收益均值 ✓
        "return_pct": round(sum(rets) / len(rets), 2),
        "worst_symbol": min(rows, key=lambda r: r["return_pct"])["symbol"],
        "worst_return_pct": min(rets),
        "mdd_pct": round(min(r["mdd_pct"] for r in rows), 2),
        "total_ops": sum(r["n_ops"] for r in rows),
        "avg_held_pct": round(sum(r["avg_held_pct"] for r in rows) / len(rows), 1),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="把完整结果写到该路径")
    ap.add_argument("--symbols", default=None, help="逗号分隔，覆盖默认 6 个")
    args = ap.parse_args(argv)

    global SYMBOLS
    if args.symbols:
        SYMBOLS = [s.strip() for s in args.symbols.split(",") if s.strip()]

    px, st = _load()
    dates = sorted(set(px["date"]))
    if not dates:
        sys.exit("✗ prices.csv 为空")
    d0, d1 = dates[0], dates[-1]
    cut = dates[int(len(dates) * 0.7)]

    print("# 杠杆 ETF 建仓/加仓计划回测（2026-10-30）")
    print("标的: %s" % " / ".join(SYMBOLS))
    print("区间: %s → %s（样本外从 %s 起）\n"
          % (str(d0.date()), str(d1.date()), str(cut.date())))

    # 🔴 2026-10-30 实测教训：第一次跑出来「10 年区间只交易 5 次、平均持仓 0.2%」✗
    # —— 原因是 `shoutu_fng.csv` 的**历史覆盖很短**（只有近几十天）✗，
    # 而脚本当时**没有报覆盖**⇒ 结论看着像「规则很保守」✗ 实际是「几乎没数据」✗
    # ⇒ 必须先把覆盖打出来，覆盖不足就**明确警告** ✓。
    print("## 守猪待兔数据覆盖（决定回测是否有效 ✗）")
    cov = {}
    for s in SYMBOLS:
        c = _coef(st, s)
        cov[s] = len(c)
        if c.empty:
            print("  %-6s **无系数** ✗（该标的永远不会触发建仓 ✓）" % s)
        else:
            print("  %-6s %5d 天（%s → %s）"
                  % (s, len(c), str(c.index[0].date()), str(c.index[-1].date())))
    thin = [s for s, n in cov.items() if 0 < n < 250]
    if thin:
        print("\n⚠️ **覆盖不足 250 天的标的：%s** —— 这些标的的结论不可信 ✗"
              % "、".join(thin))
    if all(n < 250 for n in cov.values()):
        print("\n🔴 **全部标的覆盖都不足 250 天 ⇒ 本次回测不构成参数依据** ✗")
        print("   （要真验证，得先把守猪待兔历史补齐 —— 见 docs/position-plan.md）\n")
    print()

    out = {"range": [str(d0.date()), str(d1.date())],
           "oos_from": str(cut.date()), "symbols": SYMBOLS, "runs": {}}
    for name, v in VARIANTS.items():
        full = _run(px, st, v, label=name)
        oos = _run(px, st, v, start=cut, label=name)
        if not full:
            print("✗ %s：无有效样本" % name)
            continue
        out["runs"][name] = {"full": full, "oos": oos}
        print("## %s" % name)
        print("  全样本: 收益 %+6.2f%% | 最差标的 %s %+.2f%% | 回撤 %.2f%% | "
              "操作 %d 次 | 平均持仓 %.1f%%"
              % (full["return_pct"], full["worst_symbol"],
                 full["worst_return_pct"], full["mdd_pct"],
                 full["total_ops"], full["avg_held_pct"]))
        if oos:
            print("  样本外: 收益 %+6.2f%% | 最差标的 %s %+.2f%% | 回撤 %.2f%%"
                  % (oos["return_pct"], oos["worst_symbol"],
                     oos["worst_return_pct"], oos["mdd_pct"]))
        print()

    print("## 逐标的（全样本）")
    print("| 标的 | 变体 | 收益% | 回撤% | 买入次数 | 最大持仓% |")
    print("|---|---|---|---|---|---|")
    for name, r in out["runs"].items():
        for row in r["full"]["symbols"]:
            print("| %s | %s | %+.2f | %.2f | %d | %.1f |"
                  % (row["symbol"], name, row["return_pct"], row["mdd_pct"],
                     row["n_buys"], row["max_held_pct"]))

    if args.json:
        p = args.json if os.path.isabs(args.json) else os.path.join(REPO, args.json)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        print("\n完整结果: %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
