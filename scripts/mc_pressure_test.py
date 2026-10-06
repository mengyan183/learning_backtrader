#!/usr/bin/env python3
"""Monte Carlo 熔断压力模拟（P6，不依赖回测文件）。

用 features.csv 的 fg_index 历史（2016-2026）做**无参数重采样（bootstrap）**：
以最新指数为起点，随机抽取历史日收益生成 N 条未来 H 交易日路径，统计：
  - 触发极贪熔断（fg_index ≥ config.EXTREME_GREED_TRIGGER=85）的概率
  - 触及极恐线（fg_index ≤ 20）的概率
  - 路径内最大回撤分布（P50 / P95）

用途：极端档位的先验频率估计 + 熔断触发前的压力提示（研究参考，非实盘指令）。
知识库来源：QuantPy《Monte Carlo simulation》等量化回测沉淀。

用法：
    .venv/bin/python scripts/mc_pressure_test.py
    .venv/bin/python scripts/mc_pressure_test.py --paths 20000 --horizon 60
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fg_system import config  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=10000, help="模拟路径数")
    ap.add_argument("--horizon", type=int, default=30, help="未来交易日数")
    ap.add_argument("--seed", type=int, default=20261006)
    args = ap.parse_args()

    feat = pd.read_csv(REPO / "Data" / "features.csv", parse_dates=["date"])
    valid = feat.dropna(subset=["fg_index"]).sort_values("date")
    if len(valid) < 260:
        print("fg_index 历史不足（需要 ≥260 个有效交易日）")
        return 1

    idx = valid["fg_index"].astype(float).values
    last = float(idx[-1])
    last_date = str(valid["date"].iloc[-1].date())

    # 日收益：截尾去极端（1%/99% 分位），避免单日跳变破坏采样分布
    rets = np.diff(idx)
    lo, hi = np.percentile(rets, 1.0), np.percentile(rets, 99.0)
    rets = rets[(rets >= lo) & (rets <= hi)]

    rng = np.random.default_rng(args.seed)
    hit_greed = hit_fear = 0
    maxdd = np.empty(args.paths)

    for i in range(args.paths):
        path = last + np.cumsum(rng.choice(rets, size=args.horizon, replace=True))
        hit_greed += int(path.max() >= config.EXTREME_GREED_TRIGGER)
        hit_fear += int(path.min() <= 20.0)
        peak = np.maximum.accumulate(path)
        maxdd[i] = float((path / peak - 1.0).min())

    n = args.paths
    print("=" * 62)
    print("Monte Carlo 熔断压力模拟（研究参考，非实盘指令）")
    print("=" * 62)
    print("起始指数 %.1f（数据日 %s）· 模拟 %d 条 × %d 交易日路径"
          % (last, last_date, n, args.horizon))
    print("日收益分布：历史 %d 个交易日 · 截尾 1%%/99%% 后均值 %+.3f / 标准差 %.3f"
          % (len(rets), rets.mean(), rets.std()))
    print("-" * 62)
    print("极贪熔断（≥%.0f）触发概率: %.1f%%" % (config.EXTREME_GREED_TRIGGER,
                                               hit_greed / n * 100.0))
    print("极恐线（≤20）触及概率:    %.1f%%" % (hit_fear / n * 100.0))
    print("路径最大回撤  P50: %.1f%%  |  P95: %.1f%%"
          % (np.percentile(maxdd, 50) * 100.0, np.percentile(maxdd, 95) * 100.0))
    print("-" * 62)
    print("解读：")
    if hit_greed / n > 0.10:
        print("  ⚠ 未来 %d 日内触发极贪熔断概率偏高 —— 贪婪档位下追高风险显著"
              % args.horizon)
    else:
        print("  → 未来 %d 日内极贪熔断概率不高，贪婪档位属低概率尾部事件"
              % args.horizon)
    print("  P95 回撤提示：极端行情下的指数回落幅度参考（对照账户回撤容忍度）")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
