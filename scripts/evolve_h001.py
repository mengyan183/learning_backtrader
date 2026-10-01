#!/usr/bin/env python3
"""
H-001 验证脚本：20 交易日假说判定（自我进化闭环的"变体验证"环节）。

假说（evolution/hypotheses.md H-001）：
    深度浮亏持仓（AXTX/CRCG，浮亏率 ≤ -30%）构成账户净值的系统性拖累。
检验方法：
    每日记录 AXTX/CRCG 市值与账户净值，跟踪 20 个交易日，
    计算两者日变动相关性及贡献度。
不成立判据（触发其一即证伪 falsified）：
    1. 20 个观察日内，AXTX/CRCG 市值合计较首个观察日反弹 ≥ 10%
    2. AXTX/CRCG 市值日变动与净值日变动的 Pearson 相关系数 ρ ≥ -0.3
        （无显著负相关 ⇒ "系统性拖累"不成立）

状态机：open → verifying（累计观察点 < 20）→ adopted / falsified
口径说明：观察点 = Data/positions.csv 中 AXTX/CRCG 的按日期去重记录；
         净值 = Data/accounts.csv stock 账户 net_value（按日期去重）。
         周末重复价格点保留（价格不变，对 ρ 影响可忽略，注释于 2026-10-01 录入）。
"""
import os
import sys
import csv
from collections import defaultdict
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POS_CSV = os.path.join(BASE, "Data", "positions.csv")
ACC_CSV = os.path.join(BASE, "Data", "accounts.csv")
HYP = os.path.join(BASE, "evolution", "hypotheses.md")
MEM_DIR = os.path.join(BASE, "evolution", "memory")

WATCH = {"AXTX", "CRCG"}
MIN_OBS = 20
REBOUND_FALSIFY = 0.10   # 市值合计反弹 ≥10% → 证伪
RHO_FALSIFY = -0.3       # ρ ≥ -0.3 → 证伪


def load_series():
    """返回 (市值合计序列, 净值序列)，均按日期升序、日期去重。"""
    mv_by_date, nv_by_date = defaultdict(float), {}
    with open(POS_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("symbol") in WATCH and row.get("date"):
                try:
                    mv_by_date[row["date"]] += float(row.get("market_value") or 0)
                except ValueError:
                    pass
    with open(ACC_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("account") == "stock" and row.get("date"):
                try:
                    nv_by_date[row["date"]] = float(row.get("net_value") or 0)
                except ValueError:
                    pass
    dates = sorted(mv_by_date)
    mv = [mv_by_date[d] for d in dates]
    nv = [nv_by_date[d] for d in dates if d in nv_by_date]
    dates = [d for d in dates if d in nv_by_date]
    return dates, mv, nv


def pearson(x, y):
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    return num / den if den else 0.0


def update_hypotheses(status, note):
    lines = open(HYP).read().splitlines()
    out = []
    for ln in lines:
        if ln.strip().startswith("| H-001"):
            ln = ln.replace("| open |", f"| {status} |")
            out.append(ln)
        else:
            out.append(ln)
    open(HYP, "w").write("\n".join(out) + "\n")
    # 追加备注到 H-001 行尾的备注列由人工维护，结论写入 memory 日志
    mem = os.path.join(MEM_DIR, date.today().isoformat() + ".md")
    with open(mem, "a") as f:
        f.write(f"\n## H-001 自动判定（{date.today().isoformat()}）\n{note}\n")


def main():
    dates, mv, nv = load_series()
    n = len(dates)
    print(f"[H-001] 观察点：{n}/{MIN_OBS}（日期范围 {dates[0] if dates else '-'} → {dates[-1] if dates else '-'}）")
    if n < MIN_OBS:
        print(f"[H-001] 仍在 verifying：累计 {n} 个观察点，需 {MIN_OBS} 个。下次运行自动重检。")
        return 0
    base_mv = mv[0]
    rebound = (mv[-1] - base_mv) / base_mv if base_mv else 0.0
    dmv = [b - a for a, b in zip(mv, mv[1:])]
    dnv = [b - a for a, b in zip(nv, nv[1:])]
    rho = pearson(dmv, dnv)
    cond1 = rebound >= REBOUND_FALSIFY
    cond2 = rho >= RHO_FALSIFY
    note = (f"终点市值 {mv[-1]:.2f} vs 起点 {base_mv:.2f}，反弹 {rebound*100:.1f}%"
            f"（判据 ≥10%）；ρ(d市值, d净值)={rho:.3f}（判据 ≥-0.3）；"
            f"触发1={cond1}，触发2={cond2}")
    if cond1 or cond2:
        update_hypotheses("falsified", f"**证伪**：{note}")
        print(f"[H-001] 证伪 falsified：{note}")
    else:
        update_hypotheses("adopted", f"**成立（未发现反证）**：{note}")
        print(f"[H-001] 成立 adopted（未发现反证）：{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
