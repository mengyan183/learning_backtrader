#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据新鲜度护栏（每日链在 pipeline.run 之后执行）。

检查 features.csv 尾行日期与最新行情交易日（prices.csv 尾行）的滞后；
超过阈值则写 Data/freshness_warning.txt —— invest_research.py 生成简报时
读取该文件，有警告则在简报顶部标注"数据停更风险"。

本次事故背景（2026-10-05 修复）：每日链曾长期无行情更新步骤，
features.csv 停在 09-29 而无任何告警。此脚本为同类事故的自动暴露机制。
"""
import csv
import os
import sys
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEATURES = os.path.join(REPO, "Data", "features.csv")
PRICES = os.path.join(REPO, "Data", "raw", "prices.csv")
WARN = os.path.join(REPO, "Data", "freshness_warning.txt")
MAX_LAG_DAYS = 3  # 交易日容忍度（吸收周末/节假日）

# 🔴 覆盖补强（S-0）：原实现只查 features.csv / prices.csv，漏掉了 pipeline 的
# 另一个关键产物 portfolio_features.csv —— 实测 2026-09 该文件与 features 一同
# 停在 09-18 却无任何告警（与 2026-10-05 事故同型）。下面把"需新鲜的关键产物"
# 显式列出：尾行滞后 > MAX_LAG_DAYS ⇒ issue（退出码非零）。
EXTRA_FRESH = [
    ("组合特征", os.path.join(REPO, "Data", "portfolio_features.csv")),
]
# 参考产物：**只报尾行日期**，不判 issue（快照/历史类，滞后属正常但必须可见）。
REF_PRODUCTS = [
    ("守猪待兔", os.path.join(REPO, "Data", "raw", "shoutu_history.csv")),
    ("持仓快照", os.path.join(REPO, "Data", "positions.csv")),
    ("账户快照", os.path.join(REPO, "Data", "accounts.csv")),
]


def _rel(path):
    """相对 REPO 的展示路径 ✓；跨盘（Windows C:/D:）时 relpath 会抛 ValueError ✗
    ⇒ 退回绝对路径 ✓（只影响告警文案，不影响判据 ✓）。"""
    try:
        return os.path.relpath(path, REPO)
    except ValueError:
        return path


def _last_date(path, col="date"):
    if not os.path.exists(path):
        return None
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-1][col] if rows else None


def main():
    fd = _last_date(FEATURES)
    pd_ = _last_date(PRICES)
    issues = []
    today = date.today()
    if not fd:
        issues.append("features.csv 不存在")
    else:
        d1 = date.fromisoformat(str(fd)[:10])
        lag_today = (today - d1).days
        if lag_today > MAX_LAG_DAYS:
            issues.append(f"指数数据 {fd} 距今天已 {lag_today} 天未更新（正常 ≤{MAX_LAG_DAYS}）")
        if pd_:
            d2 = date.fromisoformat(str(pd_)[:10])
            if (d2 - d1).days > MAX_LAG_DAYS:
                issues.append(f"指数落后最新行情 {pd_} 共 {(d2 - d1).days} 天")
            lagp = (today - d2).days
            if lagp > MAX_LAG_DAYS:
                issues.append(f"行情数据 {pd_} 距今天已 {lagp} 天未更新")
    if not pd_ and fd:
        issues.append("prices.csv 不存在")
    for label, path in EXTRA_FRESH:
        ld = _last_date(path)
        if not ld:
            issues.append("%s（%s）不存在" % (label, _rel(path)))
        else:
            lag = (today - date.fromisoformat(str(ld)[:10])).days
            if lag > MAX_LAG_DAYS:
                issues.append("%s（%s）尾行 %s，距今 %d 天（容忍 %d）"
                              % (label, _rel(path), ld, lag, MAX_LAG_DAYS))
    refs = []
    for label, path in REF_PRODUCTS:
        ld = _last_date(path)
        refs.append("%s=%s" % (label, ld or "缺失"))
    if refs:
        print("参考产物尾行：" + " · ".join(refs))
    warn = "；".join(issues)
    with open(WARN, "w", encoding="utf-8") as f:
        f.write(warn + "\n")
    print(warn or f"数据新鲜：features={fd} prices={pd_}")
    # R-7：有告警必须**返回非零** —— 否则每日链拿不到停更信号，
    # 停更的唯一可见出口只剩简报（结合 G-1 修好前的看板盲区，等于全盲）。
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
