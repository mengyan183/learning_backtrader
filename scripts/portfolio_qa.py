#!/usr/bin/env python3
"""持仓问答工具：输出持仓/贪恐/风险摘要（供 OpenClaw portfolio-qa 技能调用）
用法:
  .venv/bin/python scripts/portfolio_qa.py --summary    # 全量摘要(持仓+贪恐+账户)
  .venv/bin/python scripts/portfolio_qa.py --pnl YINN   # 单标的浮盈亏
  .venv/bin/python scripts/portfolio_qa.py --risk       # 风险摘要(集中度/最大亏损/回撤)
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from scripts.invest_research import build_snapshot  # noqa: E402


def fmt_pnl(sym, snap):
    for r in snap["positions"]:
        if r["symbol"].lower() == sym.lower():
            pnl = r["pnl"]
            pct = r["pnl_pct"]
            if pnl is None:
                return f"{r['symbol']} {r['name']}: 无最新行情(现价=None)，成本 {r['cost']}，数量 {r['qty']}，市值 {r['mv']}"
            return (f"{r['symbol']} {r['name']}: 成本 {r['cost']}，现价 {r['last_close']}，"
                    f"浮盈亏 {pnl} USD ({pct}%)，市值 {r['mv']}")
    return f"未找到持仓 {sym}"


def summary_text(snap):
    lines = [f"数据日期: {snap['date']}"]
    if snap.get("fg"):
        f = snap["fg"]
        lines.append(f"系统贪恐指数: {f['fg_index']} [{f['zone']}] 目标仓位: {f['target_position']} 回撤: {f['drawdown']:.2%} 熔断: {'是' if f['circuit_breaker'] else '否'}")
    if snap.get("shoutu"):
        lines.append(f"守猪待兔({snap['shoutu_date']}): " + " ".join(f"{k}={v}" for k, v in snap["shoutu"].items()))
    lines.append("持仓:")
    for r in snap["positions"]:
        pnl = f"{r['pnl']}USD ({r['pnl_pct']}%)" if r["pnl"] is not None else "无行情"
        lines.append(f"  {r['symbol']} {r['name']}: qty={r['qty']} 成本={r['cost']} 现价={r['last_close']} 浮盈亏={pnl} 市值={r['mv']}")
    lines.append(f"账户净值: {snap.get('accounts')}")
    return "\n".join(lines)


def risk_text(snap):
    lines = ["风险摘要:"]
    pos = snap["positions"]
    total_mv = sum(r["mv"] for r in pos)
    # 加密相关占比
    crypto_syms = {"CONL", "CRCG", "BTC"}
    crypto_mv = sum(r["mv"] for r in pos if r["symbol"] in crypto_syms)
    lines.append(f"  组合总市值(持仓) {total_mv:.0f}；加密相关(CONL/CRCG/BTC)占比 {crypto_mv / total_mv:.1%}" if total_mv else "  无持仓数据")
    # 浮亏最大的标的
    losers = sorted([r for r in pos if r["pnl"] is not None], key=lambda x: x["pnl"])
    if losers:
        lines.append("  最大浮亏标的:")
        for r in losers[:3]:
            lines.append(f"    {r['symbol']}: {r['pnl']}USD ({r['pnl_pct']}%)")
    if snap.get("fg"):
        f = snap["fg"]
        lines.append(f"  系统回撤 {f['drawdown']:.2%}，熔断{'已触发' if f['circuit_breaker'] else '未触发'}，目标仓位 {f['target_position']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--risk", action="store_true")
    ap.add_argument("--pnl", metavar="SYMBOL")
    args = ap.parse_args()
    snap = build_snapshot()
    if args.pnl:
        print(fmt_pnl(args.pnl, snap))
    elif args.risk:
        print(risk_text(snap))
    else:
        print(summary_text(snap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
