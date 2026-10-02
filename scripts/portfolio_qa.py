#!/usr/bin/env python3
"""持仓问答工具：输出持仓/贪恐/风险/假说/漂移/情绪/因子摘要（供 OpenClaw portfolio-qa 技能调用）
用法:
  .venv/bin/python scripts/portfolio_qa.py --summary     # 全量摘要(持仓+贪恐+账户)
  .venv/bin/python scripts/portfolio_qa.py --pnl YINN    # 单标的浮盈亏
  .venv/bin/python scripts/portfolio_qa.py --risk        # 风险摘要(集中度/最大亏损/回撤)
  .venv/bin/python scripts/portfolio_qa.py --hypotheses  # 假说状态(H-001~H-009)
  .venv/bin/python scripts/portfolio_qa.py --drift       # 漂移监控(最近一次IC/ICIR)
  .venv/bin/python scripts/portfolio_qa.py --sentiment   # 情绪子信号(VIX/资金费率)
  .venv/bin/python scripts/portfolio_qa.py --factors     # 四因子最新分解
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import pandas as pd  # noqa: E402

from scripts.invest_research import build_snapshot  # noqa: E402


def hypotheses_text():
    """解析 evolution/hypotheses.md 表格 → 简明状态清单。"""
    path = REPO / "evolution" / "hypotheses.md"
    if not path.exists():
        return "假说登记文件缺失（evolution/hypotheses.md）"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(H-\d{3})\s*\|\s*(\S+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.*)$", line)
        if not m:
            continue
        hid, date, hypo, method, falsify, status, note = m.groups()
        brief = hypo.strip()[:46]
        rows.append(f"{hid} [{status}] {brief}")
    if not rows:
        return "假说登记表为空"
    return "假说状态:\n" + "\n".join(rows)


def drift_text():
    """跑漂移监控器（无推送）取最近报告。"""
    py = REPO / ".venv/bin/python"
    out = subprocess.run([str(py), str(REPO / "scripts/drift_monitor.py")],
                         capture_output=True, text=True, timeout=120)
    return (out.stdout or out.stderr).strip() or "漂移监控无输出"


def sentiment_text():
    """情绪子信号：VIX 最新 + 变化率 + BTC/ETH 资金费率（资金费率独立读取避免与 VIX 行错位）。"""
    path = REPO / "Data/raw/sentiment.csv"
    if not path.exists():
        return "情绪子信号数据缺失（运行 scripts/fetch_sentiment.py）"
    s = pd.read_csv(path, parse_dates=["date"]).dropna(subset=["vix"]).tail(1)
    if s.empty:
        return "情绪子信号数据为空"
    last = s.iloc[0]
    chg = last.get("vix_chg")
    out = [f"情绪子信号({last['date'].date()}):",
           f"  VIX {last['vix']:.2f}" + (f" ({chg:+.1f}%)" if pd.notna(chg) else "")]
    fr_path = REPO / "Data/raw/funding_rate.csv"
    if fr_path.exists():
        fr = pd.read_csv(fr_path, parse_dates=["date"]).dropna(subset=["funding_btc", "funding_eth"]).tail(1)
        if not fr.empty:
            row = fr.iloc[0]
            out.append(f"  资金费率({row['date'].date()}):")
            for k, label in (("funding_btc", "BTC"), ("funding_eth", "ETH")):
                v = row.get(k)
                out.append(f"    {label}: {v:.4f}%" if pd.notna(v) else f"    {label}: —")
        else:
            out.append("  资金费率: 暂无数据")
    else:
        out.append("  资金费率: 数据缺失")
    return "\n".join(out)


def factors_text():
    """四因子最新分解（features.csv 最新有效行）。"""
    feat = pd.read_csv(REPO / "Data/features.csv", parse_dates=["date"])
    valid = feat.dropna(subset=["fg_index"]).tail(1)
    if valid.empty:
        return "因子数据不可用"
    last = valid.iloc[0]
    out = [f"四因子分解({pd.Timestamp(last['date']).date()}):"]
    for k, label in (("vix", "波动率 VIX"), ("term", "期限利差"),
                     ("price", "价格动量"), ("breadth", "市场广度")):
        v = last.get(k)
        out.append(f"  {label}: {v:.2f}" if pd.notna(v) else f"  {label}: —")
    if pd.notna(last.get("zone")):
        out.append(f"  档位: {int(last['zone'])}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--risk", action="store_true")
    ap.add_argument("--pnl", metavar="SYMBOL")
    ap.add_argument("--hypotheses", action="store_true")
    ap.add_argument("--drift", action="store_true")
    ap.add_argument("--sentiment", action="store_true")
    ap.add_argument("--factors", action="store_true")
    args = ap.parse_args()
    if args.hypotheses:
        print(hypotheses_text())
    elif args.drift:
        print(drift_text())
    elif args.sentiment:
        print(sentiment_text())
    elif args.factors:
        print(factors_text())
    else:
        snap = build_snapshot()
        if args.pnl:
            print(fmt_pnl(args.pnl, snap))
        elif args.risk:
            print(risk_text(snap))
        else:
            print(summary_text(snap))
    return 0


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


if __name__ == "__main__":
    sys.exit(main())
