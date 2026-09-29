# -*- coding: utf-8 -*-
"""实盘持仓 vs 系统目标（第 13.2 条「我是否按规则执行」的输入）。

**只读快照、只报差异，不改任何规则。** 本脚本不产生交易指令。

用法：`PYTHONPATH=. python scripts/portfolio_check.py [YYYY-MM-DD]`
"""
import os
import sys

import pandas as pd

from fg_system import config, pipeline

# 系统标的清单（用于判断「该持仓是否在系统覆盖范围内」）。必须与 config 一致。
IN_SYSTEM = set(config.SYMBOLS) | set(config.CRYPTO_FLAT_SYMBOLS)

# ---------------------------------------------------------------- 赌注仓（第 12.24 条）
# 赌注仓 = **额外注入**、**预期 100% 归零**、系统**不给指令**的资金。
# 它**不计入**系统暴露（否则会污染第 13.2 的纪律指标），只受一个约束：上限。
BET_BUCKET = "bet"
BET_CAP = 0.05          # 投入资金（保证金）≤ 5% × 系统净值


def _system_rows(positions):
    """只取 `system` 桶。**缺 `bucket` 列时全部视为 system**（向后兼容，免迁移）。"""
    if "bucket" not in positions.columns:
        return positions
    return positions[positions["bucket"] != BET_BUCKET]


def bet_usage(accounts, positions):
    """赌注仓占用：返回 `(保证金, 系统净值, 占比, 是否超限)`；无赌注仓返回 `(0, nav, 0, False)`。

    **上限约束的是「投入资金（保证金）」，不是名义价值** —— 3x 的赌注仓
    名义可达保证金的 3 倍，但最大损失仍被保证金限定（**前提是已与系统仓位隔离**，
    见第 12.24 条：全仓下不隔离会导致强平连带平掉系统仓位，上限即失效）。
    """
    nav = float(accounts["net_value"].sum())
    if "bucket" not in positions.columns or nav <= 0:
        return 0.0, nav, 0.0, False
    bet = positions[positions["bucket"] == BET_BUCKET]
    if bet.empty:
        return 0.0, nav, 0.0, False
    col = "margin" if "margin" in bet.columns else "notional"
    margin = float(bet[col].fillna(bet["notional"]).sum())
    ratio = margin / nav
    return margin, nav, ratio, ratio > BET_CAP


def load_snapshot(date=None, accounts_path=None, positions_path=None):
    """读取指定日期（默认最新）的账户与持仓快照。"""
    a = pd.read_csv(accounts_path or config.ACCOUNTS_PATH)
    p = pd.read_csv(positions_path or config.POSITIONS_PATH)
    a["date"] = pd.to_datetime(a["date"])
    p["date"] = pd.to_datetime(p["date"])
    d = pd.to_datetime(date) if date else a["date"].max()
    return a[a["date"] == d].copy(), p[p["date"] == d].copy()


def exposure(accounts, positions):
    """返回 `(净值, 总暴露, 加密暴露, 股票暴露, 现金)`，单位与快照一致（USD/USDT 按 1:1）。

    **暴露必须按名义价值（notional）算**：BTC 永续的敞口是 `0.0299 × 标记价`
    = 2,554.84，**不是**保证金 630.34。用保证金会**严重低估杠杆**
    （本例会把加密暴露从 12.6% 报成 3.1%）。
    """
    nav = float(accounts["net_value"].sum())
    # **赌注仓不计入系统暴露**（第 12.24 条）——否则会污染第 13.2 的纪律指标。
    sys_pos = _system_rows(positions)
    notional = float(sys_pos["notional"].sum())
    crypto = float(sys_pos[sys_pos["account"] == "crypto"]["notional"].sum())
    # CONL 是加密标的但记在股票账户下（第 6.3 条的「经营 Beta 层」）。
    crypto += float(sys_pos[sys_pos["symbol"] == "CONL"]["notional"].sum())
    return nav, notional, crypto, notional - crypto, float(accounts["cash"].sum())


def main(date=None):
    accounts, positions = load_snapshot(date)
    if accounts.empty:
        print("无快照数据：%s / %s" % (config.ACCOUNTS_PATH, config.POSITIONS_PATH))
        return
    d = accounts["date"].iloc[0].date()
    nav, notional, crypto, equity, cash = exposure(accounts, positions)

    us = pipeline.run_equity_v2()
    cr = pipeline.run_crypto(write=False)
    pf = pipeline.run_portfolio(us, cr, write=False)
    _, prow, target = pipeline.pending_signal(pf)
    t_crypto = (prow["crypto_core"] or 0) + (prow["ammo_crypto"] or 0)
    t_equity = (prow["us_core"] or 0) + (prow["ammo_us"] or 0)

    print("=" * 88)
    print("实盘快照 %s（%s）" % (d, "只读，不产生指令"))
    print("=" * 88)
    print("净值 %.2f   总暴露 %.2f   现金 %.2f" % (nav, notional, cash))
    print()
    print("%-16s %10s %8s   %10s %8s   %s"
          % ("口径", "实际", "占比", "系统目标", "占比", "差异"))
    for label, act, tgt in [("总暴露", notional, target * nav),
                            ("加密", crypto, t_crypto * nav),
                            ("股票", equity, t_equity * nav),
                            ("现金", cash, (1.0 - target) * nav)]:
        print("%-16s %10.2f %7.2f%%   %10.2f %7.2f%%   %+7.2fpp"
              % (label, act, act / nav * 100, tgt, tgt / nav * 100,
                 (act - tgt) / nav * 100))
    print()
    print("持仓明细（按占净值比重降序）：")
    print("  %-6s %-16s %10s %7s   %s" % ("标的", "名称", "名义", "占比", "在系统内？"))
    for _, r in _system_rows(positions).sort_values(
            "notional", ascending=False).iterrows():
        print("  %-6s %-16s %10.2f %6.2f%%   %s"
              % (r["symbol"], r["name"], r["notional"], r["notional"] / nav * 100,
                 "✅ 是" if r["symbol"] in IN_SYSTEM else "❌ 否（系统无法给出指令）"))

    # ---- 赌注仓（第 12.24 条）：不计入系统暴露，只受上限约束 ----
    margin, _, ratio, over = bet_usage(accounts, positions)
    print()
    print("=== 赌注仓（第 12.24 条，**不计入**系统暴露）===")
    if margin <= 0:
        print("  暂无。上限 %.0f%% × 系统净值 = %.2f" % (BET_CAP * 100, BET_CAP * nav))
    else:
        print("  投入资金 %.2f  占系统净值 %.2f%%  上限 %.0f%%"
              % (margin, ratio * 100, BET_CAP * 100))
        print("  %s" % ("⚠️ **超限** —— 必须立即减到上限以内"
                        if over else "✅ 在上限内"))
        print("  ⚠️ 隔离检查（**必须人工确认**）：赌注仓与系统仓位是否在不同账户/逐仓？")
        print("     全仓下不隔离 ⇒ 强平会连带平掉系统仓位，5% 上限即失效。")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
