# -*- coding: utf-8 -*-
"""第 12.58 条 A/B：`putcall` 的 ffill 要不要加限幅。

背景（2026-11-20 评审）
    `Data/raw/putcall.csv` 存在 2019-10-07~2023-12-29 的 **1066 交易日空洞**
    （见 `docs/mac-tasks.md` MT-88）。生产用**无上限** `ffill()` ⇒ 空洞被冻结成
    常数；常数序列的 `rolling_pct` 恒为 1.0 ⇒ 分数恒为 0（极度恐惧）⇒ 会触发
    极恐加仓 ✗

但直接改成 `ffill(limit=5)` 有致命副作用（本机实测）
    `rolling_pct(min_periods=756)` 要求窗口内 756 个值全非 NaN ⇒ 空洞结束后还要
    再等 756 个交易日才有值 ⇒ 全样本只剩 12 个有效日、OOS 为 0 天 ✗
    ⇒ 所以必须在**补齐数据之后**再评估，而不是直接改代码。

本脚本：同一份 prices、同一个 OOS 起点，只换 ffill 口径，跑两轨对比。
**不写任何生产文件**（`pipeline.run(write=False)`）。

用法
    python scripts/putcall_ffill_compare.py                # 信号 + 组合回测（有 backtrader 就跑）
    python scripts/putcall_ffill_compare.py --no-backtest   # 只比信号（Windows 自动降级）
    python scripts/putcall_ffill_compare.py --limit 3

为什么默认跑回测：Mac 侧走 `run_script` 时**无法传 args**（`dispatch_task.py`
的 `--param` 只支持字符串）⇒ 默认全跑，Windows 上 `backtrader` 缺失会优雅降级 ✓
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system import config, pipeline  # noqa: E402
from fg_system.factors import putcall as pc_mod  # noqa: E402
from fg_system.factors.base import rolling_pct  # noqa: E402

ZONE_EDGES = [0, 20, 40, 60, 80, 100]
ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


def _limited_raw(limit):
    """生产口径 + ffill 限幅（其余逐行一致，便于 A/B 只差一个变量）。"""

    def raw(self, wide):
        col = pc_mod.PutCallFactor.COL
        if col not in wide.columns:
            return pd.Series(float("nan"), index=wide.index)
        s = wide[col].astype(float).ffill(limit=limit)
        return 1.0 - rolling_pct(s, config.RANK_WINDOW)

    return raw


def _run(limit=None):
    """跑一遍 pipeline；limit=None ⇒ 用生产原实现（保证基准不漂移）。"""
    orig = pc_mod.PutCallFactor.raw
    if limit is not None:
        pc_mod.PutCallFactor.raw = _limited_raw(limit)
    try:
        return pipeline.run(write=False)
    finally:
        pc_mod.PutCallFactor.raw = orig


def _stats(name, out):
    fg = out["fg_index"].dropna()
    pc = out["putcall"] if "putcall" in out.columns else None
    tgt = out["target_position"].dropna()
    z = pd.cut(fg, bins=ZONE_EDGES, labels=ZONE_NAMES, include_lowest=True)
    shares = z.value_counts(normalize=True).reindex(ZONE_NAMES) * 100
    st = {
        "name": name,
        "putcall_days": 0 if pc is None else int(pc.notna().sum()),
        "putcall_zero_pct": (None if pc is None
                             else round(float((pc.dropna() == 0).mean() * 100), 1)),
        "fg_mean": round(float(fg.mean()), 2),
        "fg_std": round(float(fg.std()), 2),
        "target_mean": round(float(tgt.mean()) * 100, 2),
        "turnover_pp": round(float(tgt.diff().abs().sum()) * 100, 1),
        "zones": {k: round(float(v), 1) for k, v in shares.items()},
    }
    return st


def _portfolio(feats, prices, oos_start):
    try:
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import portfolio_backtest as pb
        return pb.build_portfolio(feats, prices, oos_start=oos_start)
    except Exception as exc:                      # noqa: BLE001
        return {"error": "%s" % exc}


def _oos_start():
    """OOS 起点从回测脚本取，不在本脚本另写一份（口径唯一来源）。"""
    try:
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import portfolio_backtest as pb
        return pb.OOS_START
    except Exception:                             # noqa: BLE001
        return "2024-10-04"


def _show(st):
    print("\n=== [%s] 信号 ===" % st["name"])
    print("  putcall 有效天数   %d" % st["putcall_days"])
    print("  putcall 恰为 0 占比 %s%%" % st["putcall_zero_pct"])
    print("  fg_index 均值/标准差 %.2f / %.2f" % (st["fg_mean"], st["fg_std"]))
    print("  target 均值 %.2f pp | 换手 %.1f pp"
          % (st["target_mean"], st["turnover_pp"]))
    print("  五档占比 %s" % st["zones"])


def _show_bt(name, bt):
    if "error" in bt:
        print("\n=== [%s] 组合回测 —— %s ===" % (name, bt["error"]))
        return
    m = bt["metrics"]
    p, b = m["portfolio"], m["buyhold"]
    print("\n=== [%s] 组合回测（OOS 自 %s）===" % (name, bt["oos_start"]))
    for tag, key in (("OOS", "oos"), ("IS", "is")):
        pm, bm = p[key], b[key]
        print("  %-4s 年化 %7.2f%% | 回撤 %7.2f%% | Sharpe %5.2f || B0 年化 %7.2f%%"
              % (tag, pm["annual_return"] * 100, pm["max_drawdown"] * 100,
                 pm["sharpe"], bm["annual_return"] * 100))


def main(argv=None):
    ap = argparse.ArgumentParser(description="putcall ffill 限幅 A/B（第 12.58 条）")
    ap.add_argument("--limit", type=int, default=config.STALE_MAX_DAYS,
                    help="限幅天数（默认 config.STALE_MAX_DAYS=%d）"
                         % config.STALE_MAX_DAYS)
    ap.add_argument("--no-backtest", action="store_true",
                    help="只比信号，跳过组合回测（Windows 缺 backtrader 时可显式指定）")
    args = ap.parse_args(argv)

    if args.limit <= 0:
        print("⛔ --limit 必须为正整数")
        return 2

    print("基准：无上限 ffill（生产现状）；对照：ffill(limit=%d)" % args.limit)
    old = _run(None)
    new = _run(args.limit)

    so, sn = _stats("old（无上限）", old), _stats("new（limit=%d）" % args.limit, new)
    _show(so)
    _show(sn)

    print("\n=== 差异（new − old）===")
    print("  putcall 有效天数   %+d（%d → %d）"
          % (sn["putcall_days"] - so["putcall_days"],
             so["putcall_days"], sn["putcall_days"]))
    print("  fg_index 均值      %+.2f（%.2f → %.2f）"
          % (sn["fg_mean"] - so["fg_mean"], so["fg_mean"], sn["fg_mean"]))
    print("  target 均值        %+.2f pp（%.2f → %.2f）"
          % (sn["target_mean"] - so["target_mean"],
             so["target_mean"], sn["target_mean"]))
    print("  换手               %+.1f pp（%.1f → %.1f）"
          % (sn["turnover_pp"] - so["turnover_pp"],
             so["turnover_pp"], sn["turnover_pp"]))
    for z in ZONE_NAMES:
        print("  %-6s 占比       %+.1f pp（%.1f%% → %.1f%%）"
              % (z, sn["zones"][z] - so["zones"][z],
                 so["zones"][z], sn["zones"][z]))

    # 判据（先写死，避免事后挑解释）：
    #   限幅后有效天数 < 基准的 80% ⇒ 视为「因子被删除」，**不可采纳**
    base_days = max(1, so["putcall_days"])
    if sn["putcall_days"] < 0.8 * base_days:
        print("\n⛔ 判定：限幅使 putcall 有效天数掉到 %.0f%%（%d → %d）"
              "⇒ 等同静默删除该因子，**不可采纳** ✗"
              % (100.0 * sn["putcall_days"] / base_days,
                 so["putcall_days"], sn["putcall_days"]))
        print("   正确顺序：先补齐数据（MT-88）→ 再评估限幅 ✓")
        return 3

    print("\n✅ 判定：限幅未显著削减因子覆盖，可进入回测对比 ✓")

    if args.no_backtest:
        return 0

    print("\n" + "=" * 62)
    print("组合回测（同一份 prices、同一个 OOS 起点，只换 ffill 口径）")
    print("=" * 62)
    prices = pd.read_csv(os.path.join(REPO, "Data", "raw", "prices.csv"),
                         parse_dates=["date"])
    oos = _oos_start()
    bts = {"old": _portfolio(old, prices, oos), "new": _portfolio(new, prices, oos)}
    for k in ("old", "new"):
        _show_bt(k, bts[k])

    ok = [k for k in ("old", "new") if "error" not in bts[k]]
    if len(ok) == 2:
        b0 = {k: bts[k]["metrics"]["buyhold"]["oos"]["annual_return"] for k in ok}
        same = len(set(round(v, 6) for v in b0.values())) == 1
        print("\n同窗口自检：B0 年化 %s ⇒ %s"
              % (["%.2f%%" % (v * 100) for v in b0.values()],
                 "一致 ✓" if same else "**不一致，结果不可比** ✗"))
        a = bts["old"]["metrics"]["portfolio"]["oos"]
        b = bts["new"]["metrics"]["portfolio"]["oos"]
        print("  [new] 年化 %+7.2f pp（%.2f%% → %.2f%%）"
              % ((b["annual_return"] - a["annual_return"]) * 100,
                 a["annual_return"] * 100, b["annual_return"] * 100))
        print("  [new] 回撤 %+7.2f pp | Sharpe %+6.2f（%.2f → %.2f）"
              % ((b["max_drawdown"] - a["max_drawdown"]) * 100,
                 b["sharpe"] - a["sharpe"], a["sharpe"], b["sharpe"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
