#!/usr/bin/env python3
"""
通用假说验证器（H-002 ~ H-009）。

自我进化闭环「⑤变体验证」的执行器：
- 能出结论的假说 → 按不成立判据给出 adopted / falsified（附证据）；
- 数据不足的假说 → 明确缺什么、何时可验证，状态置 verifying；
- 结果写回 evolution/hypotheses.md（状态 + 备注），并追加当日 memory 日志。

口径纪律（与 evolution-plan.md §6 一致）：
  证伪即成果；数据不足不硬凑结论（宁可 verifying 等数据）。
"""
import csv
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "Data", "raw")
DATA = os.path.join(BASE, "Data")
HYP = os.path.join(BASE, "evolution", "hypotheses.md")
MEM_DIR = os.path.join(BASE, "evolution", "memory")

LEVER_ETF = ["YINN", "GDXU", "CRCG", "CONL", "AXTX"]


def _positions():
    return pd.read_csv(os.path.join(DATA, "positions.csv"),
                       parse_dates=["date"])


def _accounts():
    return pd.read_csv(os.path.join(DATA, "accounts.csv"),
                       parse_dates=["date"])


def _close(symbol):
    """prices.csv 日线 close（按 symbol）。"""
    df = pd.read_csv(os.path.join(RAW, "prices.csv"), dtype={"symbol": str},
                     parse_dates=["date"])
    sub = df[df["symbol"] == symbol].set_index("date")["close"].astype(float)
    return sub.sort_index()


def _btc_close():
    df = pd.read_csv(os.path.join(RAW, "crypto_underlying.csv"),
                     parse_dates=["date"])
    return df.set_index("date")["close"].astype(float).sort_index()


# ---------------------------------------------------------------- H-002
def check_h002():
    """股票账户负现金持续 5 交易日（判据：5 日内现金<0 天数<=2 → falsified）。"""
    acc = _accounts()
    stock = acc[acc["account"] == "stock"].sort_values("date")
    neg = stock[stock["cash"] < 0]
    n_neg = len(neg)
    n_total = len(stock)
    # 观察窗口：2026-10-02 起连续交易日（数据仅 10-02 一天）
    if n_total < 5:
        return {
            "id": "H-002", "status": "verifying",
            "evidence": "仅 %d 个交易日快照（10-02 起现金 %s），需 5 个交易日；当前现金<0 天数 %d/%d" % (
                n_total, ", ".join(map(str, stock["cash"].tolist())), n_neg, n_total),
            "note": "待 2026-10-09 前后累计 5 个交易日后再判；负现金持续（-981.66/-876.11/-879.99）",
        }
    falsified = n_neg <= 2
    return {
        "id": "H-002", "status": "falsified" if falsified else "adopted",
        "evidence": "5 个交易日内现金<0 天数 %d/5" % n_neg,
        "note": "",
    }


# ---------------------------------------------------------------- H-003
def check_h003():
    """杠杆 ETF 在信号低区间的日收益绝对值均值 vs BTC 现货。

    口径：假说指定区间 2026-09-17 ~ 2026-10-01；「信号第 5 列」数据源
    （portfolio_features.csv）未恢复，无法按信号列分段 —— 取整个区间近似，
    待信号列恢复后可再分段复核。
    判据：杠杆产品日收益绝对值均值不高于 BTC 现货 → falsified。
    """
    start, end = "2026-09-17", "2026-10-01"
    btc = _btc_close().pct_change(fill_method=None).abs().loc[start:end]
    btc_mean = float(btc.mean())
    rows = []
    for s in LEVER_ETF:
        if s == "CONL":
            # CONL 自身行情 2026-10-02 经 FutuOpenD 补录（US.CONL 前复权 690 行）；
            # 若自身缺失才回退 2×COIN 近似。
            close = _close(s)
            if close.empty:
                base = _close("COIN")
                if base.empty:
                    rows.append((s, None)); continue
                m = float((2.0 * base).pct_change(fill_method=None).abs().loc[start:end].mean())
                rows.append((s, m))
            else:
                m = float(close.pct_change(fill_method=None).abs().loc[start:end].mean())
                rows.append((s, m))
            continue
        close = _close(s)
        if close.empty:
            rows.append((s, None)); continue
        m = float(close.pct_change(fill_method=None).abs().loc[start:end].mean())
        rows.append((s, m))
    lever_means = [m for _, m in rows if m is not None]
    if not lever_means:
        return {"id": "H-003", "status": "verifying",
                "evidence": "杠杆价格数据缺失，无法验证", "note": ""}
    max_l = max(lever_means)
    falsified = max_l <= btc_mean
    detail = "; ".join("%s=%.4f" % (s, m) if m is not None else "%s=缺失" % s
                       for s, m in rows)
    return {
        "id": "H-003", "status": "falsified" if falsified else "adopted",
        "evidence": "区间 %s~%s：BTC 日收益|均值|=%.4f；杠杆产品 %s；最大=%.4f" % (
            start, end, btc_mean, detail, max_l),
        "note": "口径：信号第5列未恢复，整区间近似；%s" % (
            "杠杆波动 > BTC → 未被证伪" if not falsified else "杠杆波动不高于 BTC → 证伪"),
    }


# ---------------------------------------------------------------- H-004
def check_h004():
    """信号回落期（09-25 65.26 → 09-29 44.43）持仓净浮亏扩大。

    口径：09-25/09-29 持仓快照缺失（positions 仅 09-22/10-01/10-02），
    用 09-22（信号高位附近）vs 10-02（信号低位后）近似；浮亏=Σ qty×(price−cost)。
    判据：10-02 合计浮亏 ≤ 09-22 → falsified。
    """
    pos = _positions()
    pnl_by_date = {}
    for d, g in pos.groupby(pos["date"].dt.date):
        pnl_by_date[d.isoformat()] = float(
            (g["qty"] * (g["price"] - g["cost"])).sum())
    dates = sorted(pnl_by_date)
    if len(dates) < 2:
        return {"id": "H-004", "status": "verifying",
                "evidence": "持仓快照仅 %s，需两个可比日期" % dates, "note": ""}
    d0, d1 = dates[0], dates[-1]
    p0, p1 = pnl_by_date[d0], pnl_by_date[d1]
    # 浮亏金额取绝对值：-1033 → -3419 即浮亏扩大（更负）。
    falsified = abs(p1) <= abs(p0)
    return {
        "id": "H-004", "status": "falsified" if falsified else "adopted",
        "evidence": "持仓浮亏 %s=%.2f → %s=%.2f（%s）" % (
            d0, p0, d1, p1, "未扩大" if falsified else "扩大"),
        "note": "口径：09-25/09-29 快照缺失，以 %s↔%s 近似（信号 65.26→44.43 回落期）" % (d0, d1),
    }


# ---------------------------------------------------------------- H-005 / H-006 / H-007
def check_h005():
    return {"id": "H-005", "status": "verifying",
            "evidence": "position_multiplier 数据源（portfolio_features.csv）未恢复，无法分箱统计",
            "note": "待 portfolio_features.csv 恢复后按 fg 分箱（<40/40-50/50-55/55-70/>70）统计一致率"}


def check_h006():
    n = _accounts()[_accounts()["account"] == "stock"]["date"].nunique()
    return {"id": "H-006", "status": "verifying",
            "evidence": "股票账户快照仅 %d 个交易日（需 ≥60），无法计算斯皮尔曼相关" % n,
            "note": "待账户快照积累 ≥60 交易日后验证（约 3 个月）"}


def check_h007():
    return {"id": "H-007", "status": "verifying",
            "evidence": "信号尾部第 5/6 列布尔位数据源（portfolio_features.csv）未恢复",
            "note": "待信号列恢复后按布尔位分组比较最大回撤"}


def check_h008():
    n = _positions()["date"].nunique()
    return {"id": "H-008", "status": "verifying",
            "evidence": "持仓每日快照仅 %d 个交易日（需 ≥40），无法回归杠杆占比 vs 日波动" % n,
            "note": "待每日快照积累 ≥40 交易日后验证"}


def check_h009():
    n = _positions()["date"].nunique()
    return {"id": "H-009", "status": "verifying",
            "evidence": "持仓每日快照仅 %d 个交易日，且需 T+10 前瞻收益（需 ≥10 日历史快照）" % n,
            "note": "待快照积累后验证占比>28% vs <20% 的 T+10 负收益比例差异"}


CHECKS = [check_h002, check_h003, check_h004, check_h005,
          check_h006, check_h007, check_h008, check_h009]


def update_hypotheses(results):
    """把结果写回 hypotheses.md：状态列 + 备注追加（按 | 分段定位，行首 id 匹配）。"""
    with open(HYP, encoding="utf-8") as f:
        lines = f.readlines()
    today = dt.date.today().isoformat()
    for r in results:
        hid = r["id"]
        hit = False
        for i, ln in enumerate(lines):
            if not ln.startswith("| %s |" % hid):
                continue
            parts = ln.split("|")
            if len(parts) < 9:
                print("  [warn] %s 行结构异常：%r" % (hid, ln)); break
            parts[6] = " %s " % r["status"]
            note = "%s 验证：%s" % (today, r["evidence"])
            if r["note"]:
                note += "；" + r["note"]
            if "验证：" not in parts[7]:
                parts[7] = parts[7].rstrip() + "；" + note
            lines[i] = "|".join(parts)
            hit = True
            break
        if not hit:
            print("  [warn] %s 行未匹配，跳过" % hid)
    with open(HYP, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print("[hypotheses.md] 状态已更新")


def append_memory(results):
    os.makedirs(MEM_DIR, exist_ok=True)
    path = os.path.join(MEM_DIR, "%s.md" % dt.date.today().isoformat())
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n## 假说批量验证（evolve_verify）\n")
        for r in results:
            f.write("- %s → **%s**：%s" % (r["id"], r["status"], r["evidence"]))
            if r["note"]:
                f.write("（%s）" % r["note"])
            f.write("\n")
    print("[memory] 已追加 %s" % path)


def main():
    results = [c() for c in CHECKS]
    for r in results:
        print("[%s] %s：%s" % (r["id"], r["status"], r["evidence"]))
    update_hypotheses(results)
    append_memory(results)


if __name__ == "__main__":
    main()
