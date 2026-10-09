# -*- coding: utf-8 -*-
"""阶段 1️⃣ 规则敏感性分析（roadmap 量化升级路径 2026-10-09 拆解）。

目标：现有规则全部参数化后进回测，输出每参数 IC/收益/回撤敏感性表 + 敏感区间标注。
纪律：**只测量不改参**——本脚本运行时覆盖 config 参数，绝不写回 config.py；
     若要调参，走阶段 2 变体 + OOS 不劣化 + 人工审批（C-2/C-3）。

用法（Windows 端，纯本地计算，不需要公网）：
    .venv/bin/python scripts/sensitivity_scan.py                 # 默认 4 组参数全扫
    .venv/bin/python scripts/sensitivity_scan.py --group zone    # 只扫档位买卖线
    .venv/bin/python scripts/sensitivity_scan.py --quick         # 每参数少量网格（冒烟）

产出：
    evolution/sensitivity/sensitivity_<参数>_<标的>.md  每参数每标的一张表
    evolution/sensitivity/README.md                     汇总敏感区间一览

实现：**复用 pipeline.run(write=False) 重算 target_position**（与每日链同源，
     不复制状态机）；再走 backtrader（runner.build_cerebro）回测。
"""
# pylint: disable=protected-access
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fg_system import config
from fg_system import pipeline
from fg_system.backtest import runner

# ================================================================ 参数网格定义
# 每组: (参数名, 基准值, 网格值列表, 说明)
# 基准值 = 当前 config 值（只测量不改参的对照基线）。
ZONE_GRID = {
    "label": "档位买卖线（ZONE_EDGES 两端）",
    "param": "zone_edges",
    "baseline": list(config.ZONE_EDGES),
    "grid": [  # 只移动两端（恐惧边/贪婪边），中位 40/60 保持
        [15, 40, 60, 85],   # 两端外扩 → 更容易进入中间档
        [20, 40, 60, 80],   # 基准
        [25, 40, 60, 75],   # 两端内收 → 更难进入中间档
        [20, 40, 60, 85],
        [15, 40, 60, 80],
    ],
    "note": "档位边界只影响 zone 归属 → saturation → 目标仓位；对照 baseline 看档位阈值敏感度。",
}

CORE_GRID = {
    "label": "目标仓位（CORE_CAP 上限）",
    "param": "core_cap",
    "baseline": config.CORE_CAP,
    "grid": [0.25, 0.35, 0.45, 0.55, 0.65],
    "note": "CORE_CAP 直接缩放全部目标仓位；结合 AMMO_CAP=0.20 看组合上限约束。",
}

CIRCUIT_GRID = {
    "label": "熔断线（EXTREME_GREED_TRIGGER / EXTREME_FEAR_TRIGGER）",
    "param": "circuit",
    "baseline": (config.EXTREME_GREED_TRIGGER, config.EXTREME_FEAR_TRIGGER),
    "grid": [
        (80, 10),   # 贪婪侧更敏感
        (85, 10),   # 基准
        (90, 10),   # 贪婪侧更钝
        (85, 5),    # 恐惧侧更敏感
        (85, 15),   # 恐惧侧更钝
    ],
    "note": "熔断只在极端档触发，样本稀少 → 敏感性可能不显著，如实标注。",
}

# 减仓阈值（P1 1% 规则）— 挂在 config 的减仓相关参数上（如 P1 1% 阈值）
TRIM_GRID = {
    "label": "减仓阈值（P1 1% 规则）",
    "param": "trim",
    "baseline": getattr(config, "P1_TRIM_THRESHOLD", 0.01),
    "grid": [0.005, 0.01, 0.015, 0.02, 0.03],
    "note": "P1 减仓规则按组合日波动/仓位阈值触发；网格在 0.5%~3% 间扫描。",
}

GROUPS = {"zone": ZONE_GRID, "core": CORE_GRID, "circuit": CIRCUIT_GRID, "trim": TRIM_GRID}

# 回测用标的（敏感性按标的分别出表）
SYMBOLS = getattr(config, "SYMBOLS", ["TQQQ", "SOXL", "UPRO", "QQQ"])


# ================================================================ 参数覆盖与重算
def apply_params(group, value):
    """运行时覆盖 config 参数（仅内存，不写回 config.py）。"""
    if group == "zone":
        config.ZONE_EDGES = value
        config.ZONE_SATURATION = [1.0, 0.75, 0.5, 0.25, 0.0]
    elif group == "core":
        config.CORE_CAP = value
    elif group == "circuit":
        config.EXTREME_GREED_TRIGGER, config.EXTREME_FEAR_TRIGGER = value
    elif group == "trim":
        if hasattr(config, "P1_TRIM_THRESHOLD"):
            config.P1_TRIM_THRESHOLD = value


def restore_params(group):
    """恢复 config 参数到基准值（内存级恢复）。"""
    apply_params(group, GROUPS[group]["baseline"])


def recompute_targets(features, group, value):
    """用覆盖后的参数重算 target_position 序列。

    复用 `pipeline.run(write=False)`——与每日链同一条代码路径（loader→factors→
    index→signal→target_position，含 shift(1) 防前视），保证"敏感性分析里的规则 =
    生产里的规则"。返回带重算 target_position 的 features DataFrame。
    """
    apply_params(group, value)
    try:
        out = pipeline.run(write=False)
    finally:
        restore_params(group)
    # 与 features 原始行对齐：pipeline.run 用同一 raw 数据，索引应一致
    df = features.copy()
    df["target_position"] = out["target_position"].reindex(df.index)
    return df


def _sensitivity_metric(features, symbol):
    """对单个 (组, 参数值, 标的) 跑回测，返回指标字典。

    指标：年化收益 / 最大回撤 / Sharpe / 与 fg_index 的 IC（方向看正向贡献）。
    """
    f = features.copy()
    p = pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"), parse_dates=["date"])
    p = p[p["symbol"] == symbol].set_index("date").sort_index()
    f = f.join(p[["open", "high", "low", "close", "volume"]], how="inner")
    if len(f) < 60:  # 数据不足直接返回空（如标的刚上市）
        return {}

    strat, returns = runner.run_single(f, symbol)
    m = runner.performance_metrics(returns) if returns is not None else {}
    # IC：fg_index 对次日收益的秩相关（与 E4 因子检验同口径）
    ic = float("nan")
    if returns is not None and len(returns) > 30:
        aligned = pd.concat([f["fg_index"].shift(1), returns.rename("ret")], axis=1).dropna()
        if len(aligned) > 30:
            ic = float(aligned["fg_index"].corr(aligned["ret"], method="spearman"))
    return {"annual_return": m.get("annual_return"), "max_drawdown": m.get("max_drawdown"),
            "sharpe": m.get("sharpe"), "ic": ic}


# ================================================================ 输出
def sensitivity_table(group, symbol, results):
    """results: [(param_value, metrics_dict)] → DataFrame（表）。

    敏感度标注：相对基准值的偏离 ≥5% 且 ≥0.02（年化收益）→ 敏感，否则稳定。
    基准值 = GROUPS[group]["baseline"]（当前 config 值，只测量不改参的对照）。
    """
    baseline = GROUPS[group]["baseline"]
    rows = []
    for val, m in results:
        row = {"参数值": val}
        row.update({k: (round(v, 4) if isinstance(v, (int, float)) and not (
            isinstance(v, float) and np.isnan(v)) else "—") for k, v in m.items()})
        rows.append(row)
    df = pd.DataFrame(rows)
    if "annual_return" in df and len(df) >= 3:
        ar = pd.to_numeric(df["annual_return"], errors="coerce")
        if ar.notna().sum() >= 3:
            # 基准行的年化收益（网格中参数值==baseline 的那一行）
            base_ar = None
            for _, r in df.iterrows():
                if isinstance(r["参数值"], (list, tuple)) and list(r["参数值"]) == list(baseline):
                    base_ar = pd.to_numeric(r["annual_return"], errors="coerce")
                    break
                if r["参数值"] == baseline:
                    base_ar = pd.to_numeric(r["annual_return"], errors="coerce")
                    break
            if base_ar is not None and not pd.isna(base_ar):
                dev = (ar - base_ar).abs()
                df["敏感度"] = np.where(dev >= max(0.02, abs(base_ar) * 0.05), "敏感", "稳定")
            else:
                df["敏感度"] = "—"  # 网格里没有基准行时，保守不给标注
    return df


def write_report(group, symbol, df, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    g = GROUPS[group]
    path = os.path.join(out_dir, f"sensitivity_{group}_{symbol}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# {g['label']} — {symbol} 敏感性表\n\n")
        fh.write(f"- 参数：`{g['param']}`（基准 {g['baseline']}）\n")
        fh.write(f"- 说明：{g['note']}\n\n")
        fh.write("| 参数值 | 年化收益 | 最大回撤 | Sharpe | IC | 敏感度 |\n")
        fh.write("|---|---|---|---|---|---|\n")
        for _, row in df.iterrows():
            fh.write("| %s | %s | %s | %s | %s | %s |\n" % (
                row["参数值"], row.get("annual_return", "—"), row.get("max_drawdown", "—"),
                row.get("sharpe", "—"), row.get("ic", "—"), row.get("敏感度", "—")))
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", choices=sorted(GROUPS), help="只扫指定组（默认全部）")
    ap.add_argument("--symbols", nargs="*", default=None, help="回测标的（默认 config.SYMBOLS 子集）")
    ap.add_argument("--quick", action="store_true", help="冒烟：每组只跑 2 个参数值")
    args = ap.parse_args()

    features_path = getattr(config, "FEATURES_PATH", "Data/features.csv")
    features = pd.read_csv(features_path, parse_dates=["date"]).set_index("date")
    if "fg_index" not in features.columns or "drawdown" not in features.columns:
        sys.exit("❌ features.csv 缺少 fg_index/drawdown 列（先跑 pipeline 生成）")

    out_dir = os.path.join(os.path.dirname(features_path), "..", "evolution", "sensitivity")
    out_dir = os.path.abspath(out_dir)
    symbols = args.symbols or [s for s in SYMBOLS if s in set(
        pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"))["symbol"])][:4]

    groups = [args.group] if args.group else list(GROUPS)
    summary = []
    for group in groups:
        g = GROUPS[group]
        grid = g["grid"]
        if args.quick and len(grid) > 2:
            grid = [grid[0], grid[-1]]
        for symbol in symbols:
            print(f"⏳ 扫描 {g['param']} × {symbol}（{len(grid)} 个参数值）…")
            results = []
            for value in grid:
                recomputed = recompute_targets(features, group, value)
                results.append((value, _sensitivity_metric(recomputed, symbol)))
            df = sensitivity_table(group, symbol, results)
            path = write_report(group, symbol, df, out_dir)
            summary.append((group, symbol, path))
            print(f"  ✅ {os.path.basename(path)}")

    # 汇总 README
    readme = os.path.join(out_dir, "README.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write("# 规则敏感性分析汇总（阶段 1️⃣）\n\n")
        fh.write("> 生成时间：%s。纪律：只测量不改参；结论进文档，调参走阶段 2 变体 + 审批。\n\n"
                 % pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"))
        for group, symbol, path in summary:
            fh.write(f"- `{group}` × `{symbol}` → [{os.path.basename(path)}]({os.path.basename(path)})\n")
    print(f"\n🧾 汇总：{readme}")
    print("下一步：把敏感区间结论整理进 evolution/sensitivity/README.md（或直接人工评审）")


if __name__ == "__main__":
    main()
