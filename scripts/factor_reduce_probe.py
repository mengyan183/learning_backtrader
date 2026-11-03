#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**风控型因子专用裁判**：减仓触发回测 ✓（2026-11-02 用户裁定）。

【为什么需要单独的裁判】

`factor_backtest_probe` 的口径是「因子 → 仓位 0.2~1.0 线性映射」✗
⇒ 它要求因子能**决定仓位比例** ✗

但已有三条因子的失败方式**完全一样** ✗：

| 因子 | 回撤 | 绝对收益 | 结论 |
|---|---|---|---|
| F-016 BAA10Y | ✓ 改善 | ✗ 跑输 | Z |
| F-018 ENE | ✓ 6/6 改善 | ✗ 只 GDXU 赚钱 | draft（减仓触发）|
| F-020 P/C>1.2 | ✓ **+14.8pp** | ✗ 跑输 11.8pp | Z |

⇒ 它们的共同能力是「**识别危险时刻**」✗ 不是「决定仓位比例」✗
⇒ 用「满仓吃 beta」的口径去测，必然得出「跑输 B0」✗ **是口径错配，不是因子无效** ✗

【规则】（与 `backtest_ene_reduce.py` 一致 ✓）

    pos  = 因子信号 ∈ [0,1]（1 = 最危险 / 最该减仓）
    仓位 = 1 − pos × reduce_ratio

    reduce_ratio = 0（=B0 买入持有）/ 0.5 / 0.7 / 1.0

  ⇒ 连续函数、无跳变 ⇒ 换手温和 ✓

【口径】
  - T 日信号 shift(1) → T+1 生效（防前视 ✓）
  - 换仓成本 0.0008 / 单位换手 ✓
  - 全样本 + 前后半段（防「某段行情贡献全部收益」✗）

用法：
  .venv/bin/python scripts/factor_reduce_probe.py --factor ene
  .venv/bin/python scripts/factor_reduce_probe.py --factor f020 --symbols SPY
  .venv/bin/python scripts/factor_reduce_probe.py --factor f020 --json out.json
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

DATA = REPO / "Data"
COST = 0.0008
RATIOS = (0.0, 0.5, 0.7, 1.0)
DEFAULT_SYMBOLS = ("SPY", "YINN", "GDXU", "CONL", "QQQ")


def _prices():
    return pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])


def _close(prices, sym):
    s = prices[prices["symbol"] == sym].set_index("date")["close"].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def _metrics(ret, pos):
    """年化 / 回撤 / Sharpe / Calmar / 平均仓位 ✓。"""
    ret = ret.dropna()
    if len(ret) < 30:
        return None
    nav = (1.0 + ret).cumprod()
    yrs = len(ret) / 252.0
    annual = nav.iloc[-1] ** (1.0 / yrs) - 1.0 if yrs > 0 else np.nan
    peak = nav.cummax()
    mdd = float((nav / peak - 1.0).min())
    vol = float(ret.std() * np.sqrt(252))
    sharpe = float(ret.mean() * 252 / vol) if vol > 0 else np.nan
    return {
        "annual_return": float(annual), "max_drawdown": mdd,
        "sharpe": sharpe,
        "calmar": float(annual / abs(mdd)) if mdd < 0 else np.nan,
        "avg_pos": float(pos.mean()),
        "n_days": int(len(ret)),
    }


def _run(close, pos, ratio, trend_filter=False, ma_n=200):
    """按 `仓位 = 1 − pos×ratio` 回测 ✓。

    :param trend_filter: **趋势过滤** ✓（2026-11-02 用户裁定）
        🔴 为什么需要：F-018 / F-020 都只在「标的本身在跌」时有效 ✗
           （YINN -23.56%→-11.43% ✓、CONL -44.03%→-23.35% ✓）
           而在盈利标的上减仓是净损失 ✗
           （SPY +13.75%→+7.76%、GDXU +54.09%→+32.38% ✗）
        ⇒ 加一层「**只在均线之下才允许减仓**」的门 ✓
           均线之上 ⇒ 强制满仓（不因因子信号减仓）✓
           均线之下 ⇒ 按因子信号减仓 ✓
        ⇒ 这样「上涨时不少赚、下跌时才减仓」✓
    """
    p = pos.reindex(close.index).ffill()
    r = close.pct_change()
    w = (1.0 - p * ratio).clip(0.0, 1.0)
    if trend_filter:
        ma = close.rolling(ma_n, min_periods=ma_n).mean()
        # 均线之上 ⇒ 仓位强制 1.0（不减仓）✓；之下 ⇒ 用因子仓位 ✓
        above = (close > ma).reindex(close.index).fillna(False)
        # 🔴 2026-11-02 踩坑：`w.where(~above, 1.0)` 会把**原本 NaN** 的仓位
        # 也填成 1.0 ✗ —— `where` 只按条件选值，不管原值是否缺失 ✗
        # 实测 GDXU：无过滤 n_days=695，有过滤 **796**（多 101 天 ✗）
        # ⇒ 那 101 天是 `pos` 的 252 日分位窗预热期（本无信号 ✗）
        # ⇒ 被当成「满仓」计入年化 ⇒ B0 从 +54.09% 掉到 +7.86% ✗ 假象 ✗
        # ⇒ 用 `mask(above & w.notna(), 1.0)`：**只在有信号处**强制满仓 ✓
        w = w.mask(above & w.notna(), 1.0)
    w = w.shift(1)                                    # T → T+1 ✓
    turn = w.diff().abs().fillna(0.0)
    ret = w * r - turn * COST
    return _metrics(ret, w)


def _signal(prices, sym, factor):
    """取因子信号 ∈ [0,1]（1 = 最危险）✓。"""
    if factor == "ene":
        from fg_system.factors import ene as fene
        return fene.ene_pos(prices, sym)
    if factor == "gold":
        # F-021 黄金相对强度 ✓（2026-11-03）
        # `gold_ratio_pct` ∈ [0,1]（1 = 金矿股相对最强 ✗）
        # ⚠️ **实测方向是「逆向」** ✗ —— 比值高 ⇒ 后续跑输 ✗
        #    但本脚本要的是「**危险度**」（1 = 最该减仓 ✓）
        #    ⇒ **取反**：`1 - pct` ✓ 比值高 = 危险度高 ✓
        from fg_system.factors import gold_ratio as _fgr
        pct = _fgr.gold_ratio_pct(prices)
        return (1.0 - pct).rename("gold_danger")
    if factor in ("f020", "f020_pct"):
        # ⚠️ 两个用途方向相反，别混 ✗：
        #   ① 作「择时信号」：P/C 高 = 极恐 = 逆向看多 ✗
        #   ② 作「减仓触发」：P/C 高 = 极恐 = **该减仓保命** ✓
        # 本脚本是 ② ⇒ 返回「危险度」（1 = 最危险 = 最该减仓）✓
        d = pd.read_csv(DATA / "raw" / "putcall.csv", parse_dates=["date"])
        s = d.set_index("date")["total_ratio"].astype(float)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        if factor == "f020":
            # 二进制：`P/C > 1.2` ✗ 触发仅 1.7% ⇒ 平均仓位 99% ⇒ 无效 ✗
            return (s > 1.2).astype(float)
        # 🔴 2026-11-02 用户裁定：改**连续信号** ✓ —— P/C 的滚动分位
        # 理由：二进制信号太稀疏（1.7%）⇒ 减仓触发几乎不改变仓位 ✗
        #      而 F-018 ENE 之所以有效，正因为 `pos` 是**连续 0~1** ✓
        # 分位窗 252 日（约 1 年）✓ —— P/C 无长期漂移，1 年足够 ✓
        return s.rolling(252, min_periods=120).apply(
            lambda x: (x.iloc[-1] >= x).mean(), raw=False)
    raise SystemExit("未知 factor：%s（支持 ene / f020 / f020_pct）" % factor)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", default="ene", help="ene / f020")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--json", metavar="PATH", help="把结果写到 JSON")
    ap.add_argument("--trend-filter", action="store_true",
                    help="只在 MA200 之下才允许减仓（均线之上强制满仓）✓")
    args = ap.parse_args(argv)

    syms = [x.strip() for x in args.symbols.split(",") if x.strip()]
    prices = _prices()
    out = {}
    print("# 风控型因子减仓触发回测（factor=%s；仓位 = 1 − pos×ratio）"
          % args.factor)
    print("# 成本 %.4f/单位换手；T 信号 shift(1) → T+1 生效" % COST)
    print("# ratio=0 即 B0 买入持有 ✓\n")

    for sym in syms:
        close = _close(prices, sym)
        if len(close) < 300:
            print("## %s —— 样本 %d 不足，跳过" % (sym, len(close)))
            continue
        try:
            sig = _signal(prices, sym, args.factor)
        except SystemExit:
            raise
        except Exception as e:              # noqa: BLE001
            print("## %s —— 信号失败（%s），跳过" % (sym, e))
            continue
        sig = sig.reindex(close.index).ffill()
        if sig.dropna().empty:
            print("## %s —— 无信号，跳过" % sym)
            continue

        print("## %s（%s → %s，%d 天）%s"
              % (sym, close.index[0].date(), close.index[-1].date(), len(close),
                 "  [趋势过滤 MA200]" if args.trend_filter else ""))
        print("| ratio | 年化 | 回撤 | Sharpe | Calmar | 平均仓位 |")
        print("|---|---|---|---|---|---|")
        out[sym] = {}
        for ratio in RATIOS:
            m = _run(close, sig, ratio, trend_filter=args.trend_filter)
            if not m:
                continue
            tag = "B0" if ratio == 0 else "减仓%.0f%%" % (ratio * 100)
            out[sym][tag] = m
            print("| %.1f | %+.2f%% | %.2f%% | %.2f | %.2f | %.0f%% |"
                  % (ratio, m["annual_return"] * 100, m["max_drawdown"] * 100,
                     m["sharpe"], m["calmar"], m["avg_pos"] * 100))
        # 判读：减仓是否**改善 Calmar**（风控型因子的正确判据 ✓）
        b0 = out[sym].get("B0") or {}
        best = max((m["calmar"], t) for t, m in out[sym].items() if t != "B0")
        if b0.get("calmar") is not None:
            verdict = ("✓ 有风控价值" if best[0] > b0["calmar"]
                       else "✗ 无风控价值")
            print("  ⇒ Calmar：B0 %.2f → 最优 %.2f（%s）%s"
                  % (b0["calmar"], best[0], best[1], verdict))
        print()

    if args.json:
        p = Path(args.json)
        if not p.is_absolute():
            p = REPO / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2,
                                default=str), encoding="utf-8")
        print("[已写 %s]" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
