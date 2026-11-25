#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YINN 加仓档差回测：**每档 −X%** 哪个 X 更合理 ✓（2026-11-25）。

【问题】
  用户当前用「链式档差」：每次比**上一次加仓价**再跌 30% 加一笔 ✗
  问：30% 这个数是否合理？还是该按首建成本的 30%/60%/90%？

【为什么不能只看一条路径】
  YINN 2016-2026 只有**一条**历史路径 ✗
  ⇒ 单看「从某个点起跌多少」的结论是路径依赖的，不能推广 ✓
  ⇒ 本脚本用**滚动起点**（每 10 个交易日一个起点）模拟，
     统计「档差 X 在不同入场时点下的表现」✓

【口径】
  · 入场：起点价买入 1 份（净值归一为 1.0）
  · 加仓：价格比**上一次成交价**再跌 X% ⇒ 再买 1 份（等额，不按金额）
  · 持有期：252 个交易日（1 年）
  · 不加止损、不清仓（与纪律 4.6 一致）
  · 对比基准：同期**一次性买入并持有**

【输出】
  每个 X：平均加仓次数 / 跑完（价格跌破最后一档仍继续跌）/ 期末收益 / 相对买持的超额
"""
from __future__ import annotations

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fg_system import config  # noqa: E402

STEPS = (0.20, 0.25, 0.30, 0.40, 0.50, 0.60)
HOLD = 252          # 持有 1 年
STRIDE = 10         # 每 10 个交易日一个起点
MAX_RUNGS = 6       # 最多 6 档（1 首建 + 5 加仓）


def _load(since=None):
    """读 YINN 收盘序列（默认**全样本**，2016-09 起）。

    🔴 2026-11-25 更正：此前判断「`prices.csv` 的 YINN 跨拆股未复权」是**错的** ✗
       扫全部 36 个标的的单日跳变后确认：**没有任何一条符合拆股特征**
       （拆股 = 单向跳变 + 次日不回补；实测的 10 条全都有回补）✗

       真实情况：2016-09 的 368 → 2026-11 的 14，**10 年 −96% 是真实的**
       ⇒ 这是 **3× ETF 的 vol decay 实证**（每年约 −20%），不是数据错误 ✓
       ⇒ 最大回撤 −98.7%、50% 分位回撤 −80% **都是真实的** ✓

    ⚠️ 但这恰恰说明「按绝对价格判断便宜」有问题 ✗
       3× ETF 的绝对价格会因衰减持续下降 ⇒ **价格低 ≠ 便宜** ✓
       ⇒ 用 ETF 价格定档，会把「衰减」误当成「标的跌了」✗
    """
    p = os.path.join(ROOT, "Data", "raw", "prices.csv")
    df = pd.read_csv(p, parse_dates=["date"])
    y = df[df["symbol"] == "YINN"][["date", "close"]].dropna()
    if since:
        y = y[y["date"] >= pd.Timestamp(since)]
    return y.sort_values("date").reset_index(drop=True)


def _simulate(prices, step):
    """从起点开始模拟；返回 (加仓次数, 期末总份数, 平均成本, 期末价)。"""
    entry = prices[0]
    last_fill = entry
    fills = [entry]
    for px in prices[1:]:
        if len(fills) >= MAX_RUNGS:
            break
        if px <= last_fill * (1 - step):
            fills.append(px)
            last_fill = px
    avg = sum(fills) / len(fills)
    return len(fills) - 1, len(fills), avg, prices[-1]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    # 🔴 2026-11-25 更正：默认**全样本** ✓
    #   此前默认 2020-04-01 是基于「未复权」的**错误判断** ✗
    #   （扫 36 个标的确认无拆股跳变 ⇒ 368→14 是真实的 vol decay）✓
    ap.add_argument("--since", default=None,
                    help="起始日（默认全样本；传如 2020-04-01 可只看近段）")
    args = ap.parse_args()
    y = _load(args.since)
    print("YINN 数据：%d 行，%s → %s"
          % (len(y), y["date"].min().date(), y["date"].max().date()))

    # ── ① 历史回撤分布（决定「几档够用」）─────────────────────
    s = y.set_index("date")["close"]
    peak = s.cummax()
    dd = (s / peak - 1.0) * 100
    print("\n=== ① 历史回撤分布（从历史峰值）===")
    for q in (50, 75, 90, 95, 99):
        print("  %2d%% 分位回撤：%6.1f%%" % (q, dd.quantile(q / 100)))
    print("  最大回撤：%.1f%%（%s）"
          % (dd.min(), dd.idxmin().date()))

    # ── ② 滚动起点模拟 ──────────────────────────────────────
    print("\n=== ② 滚动起点（每 %d 日）· 持有 %d 日 · 最多 %d 档 ==="
          % (STRIDE, HOLD, MAX_RUNGS))
    print("档差   平均加仓  平均成本/首建  期末收益  买持收益  超额")
    rows = []
    for step in STEPS:
        n_adds, costs, rets, bhs = [], [], [], []
        for i in range(0, len(y) - HOLD, STRIDE):
            w = y["close"].iloc[i:i + HOLD].tolist()
            if len(w) < HOLD:
                continue
            adds, n, avg, last = _simulate(w, step)
            n_adds.append(adds)
            costs.append(avg / w[0])
            rets.append((last / avg - 1) * 100)
            bhs.append((last / w[0] - 1) * 100)
        if not rets:
            continue
        rows.append((step, sum(n_adds) / len(n_adds),
                     sum(costs) / len(costs),
                     sum(rets) / len(rets), sum(bhs) / len(bhs),
                     sum(rets) / len(rets) - sum(bhs) / len(bhs)))
    for step, a, c, r, b, e in rows:
        print("%4.0f%%   %5.2f 次   %6.3f      %+7.1f%%  %+7.1f%%  %+6.1fpp"
              % (step * 100, a, c, r, b, e))

    print("\n判读：")
    print("  · 「平均加仓」太少（<1.5）⇒ 档差过大，一年内几乎不加仓 ✗")
    print("  · 「平均加仓」太多（>4）⇒ 档差过密，弹药很快打光 ✗")
    print("  · 「超额」为正 ⇒ 分批加仓优于一次性买持 ✓（但样本是单一路径）✗")
    return 0


if __name__ == "__main__":
    sys.exit(main())
