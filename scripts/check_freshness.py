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
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEATURES = os.path.join(REPO, "Data", "features.csv")
PRICES = os.path.join(REPO, "Data", "raw", "prices.csv")
WARN = os.path.join(REPO, "Data", "freshness_warning.txt")
MAX_LAG_DAYS = 3  # 交易日容忍度（吸收周末/节假日）


def _last_date(path, col="date"):
    if not os.path.exists(path):
        return None
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-1][col] if rows else None


def main():
    fd = _last_date(FEATURES)
    pd_ = _last_date(PRICES)
    if not fd:
        warn = "⚠️ 数据停更风险：features.csv 不存在"
    elif not pd_:
        warn = ""
    else:
        d1 = date.fromisoformat(str(fd)[:10])
        d2 = date.fromisoformat(str(pd_)[:10])
        lag = (d2 - d1).days
        warn = (f"⚠️ 数据停更风险：指数数据 {fd}，最新行情 {pd_}（滞后 {lag} 天，正常 ≤{MAX_LAG_DAYS}）"
                if lag > MAX_LAG_DAYS else "")
    with open(WARN, "w", encoding="utf-8") as f:
        f.write(warn + "\n")
    print(warn or f"数据新鲜：features={fd} prices={pd_}")


if __name__ == "__main__":
    main()
