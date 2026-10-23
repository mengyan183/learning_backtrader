#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""假说验证脚本：A-3 原两案（H-005 / H-007）+ WT-05 修订口径批量（H-024/025/027/029/032）
+ WT-07 覆盖全部 open 假说。

**WT-07 覆盖清单（2026-10-10，`evolution/hypotheses.md` 全部 open 行）**

一个统一框架，三种判定方式（`HYPOTHESES[id]["kind"]`）：

  - ``trigger``：**复用 WT-05 通用触发率框架**。子集内 trend_blocked_us /
    trend_blocked_crypto 的 True 占比 ≥50% 判成立与否。
    覆盖：H-024 / H-025 / H-029 / H-032（WT-05）+ **H-037 / H-040**（WT-07）。
  - ``custom``：形态与触发率不同，单独实现。
    **H-010 / H-012**（极值依赖 / 切换点判据）+ H-013~H-015 / H-019~H-021
    + **H-031**（fed 方向变化 × CRCL 后续收益 t 检验）
    + **H-065**（股债 60 日滚动相关 × 双口径「流动性挤压期」，见下）。
  - ``pending``：**数据源未接入或样本不足** ⇒ 走「等待数据」分支，dry-run 报
    「数据缺失（路径）」，不硬凑结论。
    覆盖：H-006 / H-008 / H-009 / H-011 / H-016 / H-017 / H-018 / H-022 / H-023
    / H-026 / H-028 / H-030 / H-033 / H-034 / H-035 / H-036 / H-038
    / H-039 / H-041。

**数据可用性（本机实测 2026-10-10）**：`features.csv`（2513 行，至 2026-09-18）
与 `portfolio_features.csv`（2518 行，至 2026-09-25）齐备；`positions.csv` /
`accounts.csv` **仅 2026-09-22 一日快照** ⇒ 一切「多日快照 / 账户盈亏」类判据
无样本（H-006/008/009/011/016/017/018/022/023/028/033/038/039）；
`features.csv` **无 position_multiplier 列** ⇒ H-035/H-041 缺列；
TVL / 稳定币使用效率数据源**未接入** ⇒ H-030/H-034 等待数据。
⚠️ H-031（fed × CRCL）：**Mac 端 `features.csv` 已有 `fed` 列**，本机旧数据缺列。
实现为 ``custom``：有 `fed` 列 ⇒ 真算并做 t 检验给 `adopted`/`falsified`；
无 `fed` 列 ⇒ 返回 `pending`，原因写「数据缺失（路径）」+ 指出缺的是 fed 列。
⚠️ H-065（股债滚动相关 × 挤压期）：需 `prices.csv`（QQQ/TLT）+ `fred_DGS10.csv` +
`fred_BAA10Y.csv` + `raw/vix.csv` 四路序列。任一缺失 ⇒ 返回 `pending`，
原因写「数据缺失（路径）」；阈值全部**先验写死**为模块常量（OOS 禁调参）；
**只输出研究参考，不进权重**。

**口径声明（必须先读）**

A-3 原案（H-005 / H-007）的证据列在 fg_system 代码与 portfolio_features.csv 中
**均不存在**（`position_multiplier` 全仓零命中；「信号尾部第 5/6 列布尔位」无此列）。
按「数字必须指回文件」纪律，原案采用**可指回的真实列映射**，结论显式标注「口径映射」：

  - H-005 实质断言（fg 40-50 区间仓位放大为 2.0、55+ 放大为 3.0）
    ⇒ 映射为：按 fg_index 分箱（<40/40-50/50-55/55-70/>70），统计各箱
    `us_core`（大盘核心仓）与 `target_position` 的均值/中位数。
    判据：40-50 箱 us_core 均值 ≥ 2× 55-70 箱均值 → 成立；否则不成立。
  - H-007 实质断言（某布尔位 False 期间账户回撤 < True 期间）
    ⇒ 映射为：布尔位 = `trend_blocked_us`；账户净值 = TQQQ 策略净值（baseline
    同源）。按布尔位逐日分组，比较两组净值最大回撤幅度。
    判据：False 组回撤幅度 < True 组 → 成立。

WT-05 修订口径（2026-10-10，见 hypotheses.md 五行的 **2026-10-10 WT-01 口径修订**）：
虚构 threshold/position_multiplier → 真实 `core_position` / `zone`（features.csv）；
「第 4/5/6/7 列」→ 真实 `fg_index` / `trend_blocked_us` / `trend_blocked_crypto`
（**在 portfolio_features.csv**）。字段限定 `zone` / `fg_index` /
`trend_blocked_us` / `trend_blocked_crypto`。

  - H-024：fg_index ≥ 70 的全部日期，trend_blocked 布尔位触发率 ≥50% → **不成立**。
  - H-025：zone=3.0 且 fg_index ≥70 的日期，布尔位触发率 ≥50% → **不成立**。
  - H-027：AXTX 浮亏 ≤ -20% 的日期，布尔位触发率 ≥50% → **不成立**。
    ⚠️ 数据源（features.csv / portfolio_features.csv）**无 AXTX 浮亏列** ⇒
    本机数据缺失，验证挂起（明确报「数据缺失（路径）」）。
  - H-029：fg_index ≥ 70 的日期，布尔位触发率 ≥50% → **成立**。
  - H-032：zone=3.0 的日期，布尔位触发率 ≥50% → **不成立**。

用法：
    py -3.10 scripts/verify_hypotheses.py              # 全部假说
    py -3.10 scripts/verify_hypotheses.py --help       # 列出支持的假说
    py -3.10 scripts/verify_hypotheses.py --dry-run    # 只检查数据，不写文件
    py -3.10 scripts/verify_hypotheses.py -H H-024     # 只跑指定假说（可重复）

输出：**默认只打印到 stdout**；只有显式传 `--out` 时才追加写结果文件
（**不覆盖**已有内容）。
退出码：0 正常 / 2 数据缺失 / 1 运行错误。
"""
import argparse
import math
import os
import re
import sys

import numpy as np
import pandas as pd

# 输出统一 UTF-8（AGENTS.md §6.2 第 4 条）。Windows 默认 GBK 会让
# `✅` / `⇒` 等字符 `UnicodeEncodeError` 打挂进程。先设编码，再运行脚本。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fg_system import config  # noqa: E402

# 触发率判据阈值：子集内 trend_blocked 布尔位为 True 的占比（修订口径统一 50%）。
TRIGGER_RATE_THRESHOLD = 0.50
# fg_index「贪婪」判据线（H-024 / H-025 / H-029 修订口径均为 70）。
FG_GREED_LINE = 70.0
# zone=3.0 判据（修订口径字面值；features.csv 的 zone 列是整数 0-4 ⇒ 3.0 == 3）。
WATCH_ZONE = 3.0

# WT-07 新增阈值（先验，禁止优化）。
EXTREME_BAND_LOW, EXTREME_BAND_HIGH = 35.0, 80.0   # H-012 极值区间
OVERLAP_TOLERANCE = 0.20                            # H-010/H-014 重叠率阈值（20%）
AMPLITUDE_WINDOW = 10                               # H-013 滚动振幅窗口（交易日）
CORE_DOUBLE = 0.225                                 # H-020 core_position 翻倍档
SWITCH_ZONE = 2.0                                   # H-015/H-021 zone 降档目标
MIN_SNAPSHOT_DAYS = 2                               # 多日快照类判据最小观察点

# H-031（fed 方向变化 × CRCL 后续收益）阈值（先验，禁止优化）。
H031_HORIZONS = (4, 8, 16)      # 检验方法指定的前瞻窗口（交易日）
H031_ALPHA = 0.05               # 显著性水平：p ≤0.05 才认为有显著影响
H031_MIN_EVENTS = 5             # 方向变化事件日的最小样本
H031_MIN_BASE = 20              # 基线（全样本前瞻收益）的最小样本

# H-065（避险资产失效 —— 股债相关性转正）阈值（先验写死，OOS 禁调参）。
# 照 evolution/hypotheses.md 的 H-065 行与 docs/notes/2026-10-16-假说登记草案 §1。
# 不成立判据（满足任一即不成立）：
#   ① 全样本 corr>0 占比 < 20%；
#   ② 「低利率波动桶」corr>0 占比不高于全样本占比（正相关完全由利率解释）；
#   ③ 挤压期内 corr>0 且 QQQ 下跌的日子里，股债同跌天数 ≤ 5。
H065_ROLL_WINDOW = 60           # 60 日滚动 Pearson 相关窗口（交易日）
H065_POS_RATIO_FLOOR = 0.20     # 全样本 corr>0 占比下限（<20% ⇒ 不成立）
H065_SPREAD_WINDOW = 5          # 信用利差走阔观察窗（交易日）
H065_SPREAD_WIDEN_BP = 25.0     # BAA10Y 5 日走阔阈值（bp；%量纲 ×100）
H065_VIX_QUANTILE = 0.80        # VIX 高分位阈值（全样本 80 分位）
H065_VIX_JUMP_PCT = 0.20        # VIX 单日跳升阈值（>20%）
H065_COFALL_DAYS_MIN = 5        # 挤压期内股债同跌天数下限（≤5 ⇒ 不成立）
H065_DIVISOR_BP = 100.0         # 利差 % → bp 换算

# H-068（避险失效 —— **短窗**口径）阈值（先验写死，OOS 禁调参）。
# 照 `evolution/hypotheses.md` H-068 行。🔴 设计自检（`docs/dual-end-workflow.md`
# §C.3「预登记自检清单」5 条，逐条对照 H-065 的翻车点）：
#   ① 挤压期定义**不含** QQQ/TLT 方向（纯外生压力指标）⇒ 无循环定义
#      （H-065 主口径含「TLT 也跌」⇒ 把结论写进自变量）；
#   ② 判据为「挤压期 vs 非挤压期」**对比** ⇒ 与挤压期定义不重叠
#      （H-065 判据③ 数 `co_down`，而挤压期已含 `co_down` ⇒ 恒真）；
#   ③ 主口径按**统计效力**选（预登记时结果未知）：n<200 ⇒ `insufficient` 不硬凑；
#      稀有口径（BAA10Y，实测 n≈4）**仅列明细、不参与判定**
#      （H-065 规定「以主口径为准」而主口径仅 4 天 ⇒ 以无样本口径定结论）；
#   ④ 判据措辞与假说意图**逐字对齐**（「显著更高」）；
#   ⑤ 指标尺度（5 日）与机制尺度（数日挤压）**匹配**
#      （H-065 用 60 日滚动 ⇒ 被过去两个月的正常避险行为主导 ⇒ 结构性测不出）。
H068_ROLL_WINDOW = 5            # **短窗** 5 日滚动 Pearson 相关
H068_VIX_QUANTILE = 0.80        # 主口径：VIX 收盘 > 全样本 80 分位
H068_VIX_JUMP_PCT = 0.20        # 主口径：VIX 单日跳升 > 20%
H068_MIN_SQUEEZE_DAYS = 200     # 挤压期最小样本（不足 ⇒ insufficient，不硬凑）
H068_ALPHA = 0.05               # 单侧两比例 z 检验显著性（p < α ⇒ 显著更高）
H068_SPREAD_WINDOW = 5          # 辅助口径（仅明细）：BAA10Y 5 日观察窗
H068_SPREAD_WIDEN_BP = 25.0     # 辅助口径（仅明细）：走阔 > 25bp（沿用 H-065，不改）
H068_DIVISOR_BP = 100.0         # 利差 % → bp 换算

# H-069（避险失效 —— 当日同跌）阈值（先验写死，OOS 禁调参）。
# 照 `evolution/hypotheses.md` H-069 行（非盲登记 ⇒ 判定以「分段稳健」为准）。
# 不成立判据（满足任一即不成立）：
#   ① 全样本挤压期同跌率不显著高于非挤压期（单侧两比例 z 检验 p ≥ α）；
#   ② 分段：前 / 后任一半段 p ≥ α（只在半段成立 ⇒ 不稳健）；
#   ③ 挤压期样本 < 200 或任一半段 < 50 ⇒ insufficient（不硬凑结论）。
H069_VIX_QUANTILE = 0.80        # 挤压期主口径：VIX 收盘 > 全样本 80 分位
H069_VIX_JUMP_PCT = 0.20        # 挤压期主口径：VIX 单日跳升 > 20%
H069_MIN_SQUEEZE_DAYS = 200     # 挤压期最小样本（不足 ⇒ insufficient）
H069_MIN_HALF_SQUEEZE_DAYS = 50 # 半段最小挤压样本（不足 ⇒ insufficient）
H069_ALPHA = 0.05               # 单侧两比例 z 检验显著性（p < α ⇒ 显著更高）


class DataMissingError(Exception):
    """数据文件缺失。消息必须含**路径**，供 dry-run / main 报「数据缺失（路径）」。"""

    def __init__(self, path):
        self.path = path
        super().__init__("数据缺失（路径）：%s" % path)


# ------------------------------------------------------------------ 数据加载
def _read_csv(path):
    if not os.path.exists(path):
        raise DataMissingError(path)
    return pd.read_csv(path, parse_dates=["date"]).set_index("date")


def load_features():
    """features.csv × portfolio_features.csv 内连接。

    走 `fg_system.config` 路径常量。缺文件时抛 DataMissingError（含路径）。
    pf 与 feats 重叠列（target_position/extreme/core_position）以 feats 为准；
    pf 的 core_position **另存为 `core_position_pf`**（H-020 的 0.225 档只存在
    于 portfolio_features.csv，与 feats 的档位饱和度核心仓口径不同）。
    """
    feats = _read_csv(config.FEATURES_PATH)
    pf = _read_csv(config.PORTFOLIO_FEATURES_PATH)
    extra = ["us_core", "trend_blocked_us", "trend_blocked_crypto"]
    missing = [c for c in extra if c not in pf.columns]
    if missing:
        raise DataMissingError("%s（缺列 %s）" % (config.PORTFOLIO_FEATURES_PATH,
                                                 ",".join(missing)))
    for col in ("fg_index", "zone"):
        if col not in feats.columns:
            raise DataMissingError("%s（缺列 %s）" % (config.FEATURES_PATH, col))
    df = feats.join(pf[extra], how="inner")
    # pf 的 core_position（若存在）另存别名，避免被 feats 同名列覆盖。
    if "core_position" in pf.columns:
        df["core_position_pf"] = pf["core_position"]
    return df.dropna(subset=["fg_index", "us_core"])


def DATA_DEPENDENCIES():
    """dry-run 检查的**必需**数据文件（绝对路径，走 fg_system.config）。

    只列**验证确实会读**的文件。缺任一 ⇒ dry-run 退出码 2。
    ⚠️ 「数据源未接入」的假说（TVL / 稳定币使用效率）不在本清单里——
    它们走 `pending` 分支在输出中标注「等待数据」，不使整个 dry-run 失败。
    """
    return [config.FEATURES_PATH, config.PORTFOLIO_FEATURES_PATH]


def missing_dependencies(paths=None):
    """返回缺失的数据文件路径清单（按给定顺序，去重）。"""
    result = []
    for path in (paths if paths is not None else DATA_DEPENDENCIES()):
        if path not in result and not os.path.exists(path):
            result.append(path)
    return result


# ------------------------------------------------------------------ A-3 原案
def verify_h005(df):
    """H-005：fg_index 分箱 vs 核心仓（口径映射见模块 docstring）。"""
    bins = [-np.inf, 40, 50, 55, 70, np.inf]
    labels = ["<40", "40-50", "50-55", "55-70", ">70"]
    df = df.copy()
    df["bin"] = pd.cut(df["fg_index"], bins=bins, labels=labels,
                       right=False)
    rows = []
    for lab in labels:
        g = df[df["bin"] == lab]
        rows.append({
            "bin": lab,
            "n": int(len(g)),
            "us_core_mean": float(g["us_core"].mean()),
            "us_core_median": float(g["us_core"].median()),
            "target_mean": float(g["target_position"].mean()),
        })
    res = pd.DataFrame(rows)
    g40 = res.loc[res["bin"] == "40-50", "us_core_mean"].iloc[0]
    g55 = res.loc[res["bin"] == "55-70", "us_core_mean"].iloc[0]
    ratio = g40 / g55 if g55 != 0 else float("nan")
    passed = g40 >= 2.0 * g55 if g55 != 0 else False
    note = ("口径映射：position_multiplier 列不存在 ⇒ 用 us_core（五档核心仓）"
            "检验「40-50 箱为 55+ 箱的 2 倍」的实质断言。"
            "若按登记措辞 2.0/3.0 字面（55+ 应更大）⇒ 与五档设计（zone 越贪婪"
            "仓位越低）矛盾，字面口径不成立。")
    return res, {"ratio_40_55": float(ratio) if ratio == ratio else None,
                 "passed": bool(passed), "note": note}


def verify_h007(df):
    """H-007：trend_blocked_us 布尔位分组回撤比较（口径映射见 docstring）。"""
    prices_path = os.path.join(config.RAW_DIR, "prices.csv")
    if not os.path.exists(prices_path):
        raise DataMissingError(prices_path)
    prices = pd.read_csv(prices_path, parse_dates=["date"])
    p = prices[prices["symbol"] == "TQQQ"].set_index("date").sort_index()
    f = df.copy()
    f = f.join(p[["close"]], how="inner")
    if f.empty:
        return None, {"passed": False, "note": "无 TQQQ 价格数据，无法构造净值"}
    f["target"] = f["target_position"].shift(1).fillna(0.0)
    f["daily_ret"] = f["close"].pct_change().fillna(0.0)
    f["nav"] = (1.0 + f["target"] * f["daily_ret"]).cumprod()

    def _group_mdd(sub):
        if len(sub) < 2:
            return float("nan")
        cum = sub["nav"]
        return float((cum / cum.cummax() - 1.0).min())

    # 逐日布尔位分组（False 组 = 当日未阻断，True 组 = 当日阻断）
    false_days = f[~f["trend_blocked_us"].fillna(False).astype(bool)]
    true_days = f[f["trend_blocked_us"].fillna(False).astype(bool)]
    mdd_false = _group_mdd(false_days)
    mdd_true = _group_mdd(true_days)
    # H-007 判据：False 组最大回撤**幅度**小于 True 组 ⇒ 成立。
    passed_strict = (mdd_false == mdd_false and mdd_true == mdd_true
                     and abs(mdd_false) < abs(mdd_true))
    note = ("口径映射：信号尾部第 5/6 列布尔位不存在 ⇒ 取 trend_blocked_us "
            "（趋势过滤阻断，最贴近语义的布尔位）。账户净值 = TQQQ 策略净值"
            "（baseline 同源）。True 组（阻断日）应回撤更小才算「趋势过滤有效」。")
    return {"mdd_false": mdd_false, "mdd_true": mdd_true,
            "n_false": int(len(false_days)), "n_true": int(len(true_days)),
            "passed_abs_smaller": bool(passed_strict), "note": note}


# ------------------------------------------------------------------ WT-05 通用触发率验证
def trigger_rate_for_mask(df, mask):
    """通用触发率：子集内 trend_blocked_us / trend_blocked_crypto 的 True 占比。

    返回 dict：n（子集样本数）/ 两列各自触发数与触发率 / 合并触发率
    （任一布尔位为 True 即计入）。
    布尔位缺失（NaN）按 False 处理，与 H-007 口径一致。
    """
    sub = df[mask]
    n = int(len(sub))
    us = sub["trend_blocked_us"].fillna(False).astype(bool)
    cr = sub["trend_blocked_crypto"].fillna(False).astype(bool)
    any_hit = us | cr
    return {
        "n": n,
        "n_us": int(us.sum()),
        "rate_us": float(us.mean()) if n else float("nan"),
        "n_crypto": int(cr.sum()),
        "rate_crypto": float(cr.mean()) if n else float("nan"),
        "n_any": int(any_hit.sum()),
        "rate_any": float(any_hit.mean()) if n else float("nan"),
    }


def judge_trigger_rate(stats, pass_when="high"):
    """按修订口径判据给出成立与否。

    pass_when="high"：触发率 ≥50% 则假定成立（H-029）。
    pass_when="low" ：触发率 ≥50% 则假定**不成立**（H-024/025/027/032）。
    样本为空时返回 None（无法判定 ⇒ 挂起）。
    """
    rate = stats["rate_any"]
    if not stats.get("n") or rate != rate:
        return None
    high = rate >= TRIGGER_RATE_THRESHOLD
    return high if pass_when == "high" else (not high)


# 每条修订假说的「子集构造器」。字段限定 zone / fg_index。
def _mask_fg_ge_70(df):
    return df["fg_index"] >= FG_GREED_LINE


def _mask_zone3(df):
    return df["zone"].astype(float) == WATCH_ZONE


def _mask_zone3_and_fg70(df):
    return _mask_zone3(df) & _mask_fg_ge_70(df)


# ------------------------------------------------------------------ WT-07 单独实现
def _interval_overlap(lo_a, hi_a, lo_b, hi_b):
    """两区间重叠宽度占较窄区间宽度的比例（0 = 不重叠）。"""
    width = min(hi_a - lo_a, hi_b - lo_b)
    if width <= 0 or width != width:
        return 0.0
    overlap = min(hi_a, hi_b) - max(lo_a, lo_b)
    return float(max(0.0, overlap) / width)


def verify_h010(df):
    """H-010：zone 由 fg_index 固定边界驱动，且边界稳定（区间重叠率 ≤20%）。

    检验方法（hypotheses.md）：以 fg_index 为自变量、zone 为因变量分组统计，
    找档位切换点对应 fg_index 区间；统计相邻档位区间的重叠率。
    不成立判据：重叠率 >20%（同一数值区间出现两种 zone）。
    """
    d = df.dropna(subset=["fg_index", "zone"])
    groups = {}
    for z, sub in d.groupby(d["zone"].astype(float)):
        groups[z] = (float(sub["fg_index"].min()), float(sub["fg_index"].max()))
    zones = sorted(groups)
    worst = 0.0
    worst_pair = None
    rows = []
    for a, b in zip(zones, zones[1:]):
        rate = _interval_overlap(groups[a][0], groups[a][1],
                                 groups[b][0], groups[b][1])
        rows.append((a, b, rate))
        if rate > worst:
            worst, worst_pair = rate, (a, b)
    passed = worst <= OVERLAP_TOLERANCE
    note = ("口径修订：原虚构列 position_multiplier/threshold → 真实 zone 列"
            "（features.csv）。重叠率 = 相邻档位 fg_index 区间重叠宽度 / 较窄区间"
            "宽度；≤20% ⇒ 固定边界驱动成立。")
    return {"intervals": {k: groups[k] for k in zones}, "pair_overlaps": rows,
            "overlap": worst, "worst_pair": worst_pair, "passed": passed,
            "note": note}


def verify_h012(df):
    """H-012：布尔位触发依赖 fg_index 极值（>=80 或 <=35）。

    检验方法：取 trend_blocked_us/crypto 任一为 True 的行，关联同日 fg_index，
    计算落在 [35,80] 区间内的比例。
    不成立判据：>20% 的 True 行落在 [35,80] ⇒ 极值依赖被证伪。
    """
    d = df.dropna(subset=["fg_index"])
    us = d["trend_blocked_us"].fillna(False).astype(bool)
    cr = d["trend_blocked_crypto"].fillna(False).astype(bool)
    hits = d[us | cr]
    n = int(len(hits))
    if n:
        in_band = (hits["fg_index"] >= EXTREME_BAND_LOW) & \
                  (hits["fg_index"] <= EXTREME_BAND_HIGH)
        frac = float(in_band.mean())
    else:
        frac = float("nan")
    passed = None if not n else (frac <= OVERLAP_TOLERANCE)
    note = ("口径修订：原「信号尾部第 5、6 列布尔位」→ 真实 trend_blocked_us/"
            "trend_blocked_crypto（portfolio_features.csv）。极值区间 "
            "[%.0f, %.0f]；True 行落区间比例 ≤20%% ⇒ 极值依赖成立。"
            % (EXTREME_BAND_LOW, EXTREME_BAND_HIGH))
    return {"n_true": n, "frac_in_band": frac, "passed": passed, "note": note}


def verify_h013(df, switch_idx=None, window=AMPLITUDE_WINDOW):
    """H-013：档位切换后恐惧贪婪数值滚动 10 日振幅收窄。

    检验方法：以切换点为界，分前后两段计算 fg_index 滚动 10 日高低差均值。
    不成立判据：切换后均值 ≥ 切换前。
    """
    d = df.dropna(subset=["fg_index"]).copy()
    d["amplitude"] = d["fg_index"].rolling(window).apply(
        lambda s: s.max() - s.min(), raw=True)
    if switch_idx is None:
        z = d["zone"].astype(float)
        changes = z.ne(z.shift())
        idxs = [i for i, ch in enumerate(changes) if ch and i > 0]
        switch_idx = idxs[-1] if idxs else len(d) // 2
    before = d["amplitude"].iloc[:switch_idx].mean()
    after = d["amplitude"].iloc[switch_idx:].mean()
    both = before == before and after == after
    passed = bool(both and after < before)
    note = ("口径修订：原「09-28 切换点」以真实 zone 切换点为准；振幅 = fg_index "
            "滚动 %d 日高低差。切换后均值 < 切换前 ⇒ 收窄成立。" % window)
    return {"amplitude_before": float(before) if before == before else None,
            "amplitude_after": float(after) if after == after else None,
            "switch_idx": int(switch_idx), "passed": passed, "note": note}


def verify_h014(df):
    """H-014：zone 越高 fg_index 区间越高（单调映射）。

    不成立判据：相邻 zone 的 fg_index 区间存在重叠。
    """
    out = verify_h010(df)          # 同一区间统计口径
    passed = out["overlap"] == 0.0 if out["intervals"] else None
    note = ("口径修订：虚构 position_multiplier → 真实 zone 列（features.csv）。"
            "不成立判据：zone 区间存在重叠（重叠率 >0）⇒ 单调映射不成立。")
    return {"intervals": out["intervals"], "overlap": out["overlap"],
            "passed": passed, "note": note}


def verify_h015(df):
    """H-015：core_position 与 zone 反向绑定（zone 降档时 core_position 升高）。

    不成立判据：出现 zone 下降而 core_position 不变或下降的行。
    """
    d = df.dropna(subset=["zone", "core_position"]).copy()
    z = d["zone"].astype(float).to_numpy()
    c = d["core_position"].astype(float).to_numpy()
    n_sw = 0
    violations = 0
    for i in range(1, len(z)):
        if z[i] < z[i - 1]:                       # zone 降档
            n_sw += 1
            if c[i] <= c[i - 1]:                  # 核心仓未升高
                violations += 1
    passed = None if n_sw == 0 else (violations == 0)
    note = ("口径修订：虚构 threshold/position_multiplier → 真实 core_position/"
            "zone（features.csv）。zone 降档次数 %d；违例 %d ⇒ 反向绑定%s。"
            % (n_sw, violations, "成立" if violations == 0 else "被证伪"))
    return {"n_switches": n_sw, "n_violations": violations, "passed": passed,
            "note": note}


def verify_h019(df):
    """H-019：zone 与 fg_index 同向联动（秩相关为正且区间单调）。

    不成立判据：秩相关绝对值 <0.5。检验方法要求以 09-23~10-06 区间为准，
    本实现取全样本并显式标注口径。
    """
    d = df.dropna(subset=["zone", "fg_index"])
    rho = d["zone"].astype(float).corr(d["fg_index"].astype(float), method="spearman")
    rho = float(rho) if rho == rho else None
    passed = None if rho is None else (abs(rho) >= 0.5)
    note = ("口径修订：虚构 signal 列 → 真实 zone 列（features.csv）。"
            "以全样本计算 Spearman 秩相关；|ρ| ≥0.5 ⇒ 同向联动成立。")
    return {"spearman": rho, "n": int(len(d)), "passed": passed, "note": note}


def verify_h020(df):
    """H-020：core_position 翻倍（→0.225）后布尔位进入零触发。

    不成立判据：core_position=0.225 区间内出现任一 trend_blocked True 行。
    列取值以 portfolio_features.csv 为准（0.225 档只存在于该文件）；
    缺失时回退 features.csv 的 core_position。
    """
    col = "core_position_pf" if "core_position_pf" in df.columns else "core_position"
    d = df[df[col].astype(float).round(4) == CORE_DOUBLE]
    n = int(len(d))
    us = d["trend_blocked_us"].fillna(False).astype(bool)
    cr = d["trend_blocked_crypto"].fillna(False).astype(bool)
    n_any = int((us | cr).sum())
    passed = None if n == 0 else (n_any == 0)
    note = ("口径修订：虚构 threshold → 真实 core_position 列（0.225 档取自 "
            "portfolio_features.csv，另存别名 core_position_pf）；"
            "虚构「第 5、6 列」→ 真实 trend_blocked_us/trend_blocked_crypto。"
            "区间内 True 计数为 0 ⇒ 假设成立。")
    return {"n": n, "n_any": n_any, "passed": passed, "note": note}


def verify_h021(df):
    """H-021：zone=2.0 区间与 fg_index 回落区间时间上重合。

    不成立判据：zone=2.0 的任一行其 fg_index ≥ 相邻 zone=3.0 行的 fg_index。
    """
    d = df.dropna(subset=["zone", "fg_index"]).copy()
    z = d["zone"].astype(float).to_numpy()
    fg = d["fg_index"].astype(float).to_numpy()
    n_low = int((z == SWITCH_ZONE).sum())
    violations = 0
    for i in range(len(z)):
        if z[i] != SWITCH_ZONE:
            continue
        # 与前一处 zone=3.0 行比较（时间上最近的更早档位）
        prev = [j for j in range(i - 1, -1, -1) if z[j] > z[i]]
        if prev and fg[i] >= fg[prev[0]]:
            violations += 1
    passed = None if n_low == 0 else (violations == 0)
    note = ("口径修订：虚构 position_multiplier/列号 → 真实 zone/fg_index。"
            "zone=2.0 天数 %d；违例 %d ⇒ 时间重合%s。"
            % (n_low, violations, "成立" if violations == 0 else "被证伪"))
    return {"n_zone2": n_low, "n_violations": violations, "passed": passed,
            "note": note}


def verify_h031(df):
    """H-031：fed 方向变化前后 CRCL 后续 4/8/16 日收益差异（t 检验）。

    检验方法（hypotheses.md）：关联 fed 因子（features.fed）与 CRCL 价格/收益
    序列，比较 fed 方向变化前后 4/8/16 日 CRCL 收益差异。

    口径（照 hypotheses.md，不发明）：
      - 「方向」= sign(fed 日差分)：涨(+1) / 跌(-1) / 平(0)。
      - 「方向变化事件日」= 当日方向与上一日方向不同（含 0↔±1 切换）。
      - 「后续 H 日收益」= close.shift(-H)/close - 1（事件日起 H 个交易日后）。
      - 基线 = CRCL 全样本各 H 日前瞻收益。
      - t 检验：对每个 horizon 做**独立双样本 Welch t 检验**
        （事件组 vs 基线），α=0.05。

    判定：
      - 无 `fed` 列 ⇒ status=pending，原因「数据缺失（路径）」+ 缺 fed 列。
      - 任一 horizon p ≤0.05 ⇒ adopted（方向变化对后续收益有显著影响）。
      - 全部 horizon p >0.05 ⇒ falsified（判据「无显著影响 ⇒ 不成立」）。
      - 事件 / 基线样本不足 ⇒ insufficient。
    数据一律走 `fg_system.config` 路径。
    """
    # 1) fed 列缺失 ⇒ 明确报「数据缺失（路径）」+ 缺列原因（保持可解释）。
    if "fed" not in df.columns:
        return {
            "status": "pending",
            "passed": None,
            "reason": "数据缺失（路径）：%s（缺列 fed）" % config.FEATURES_PATH,
            "note": ("数据缺失（路径）：%s 无 fed 列（因子未落库）。"
                     "H-031 需 features.fed 与 CRCL 收益序列关联；"
                     "本机旧数据缺列，Mac 端已有 fed 列。" % config.FEATURES_PATH),
        }

    # 2) CRCL 价格序列（走 config 路径）。
    prices_path = os.path.join(config.RAW_DIR, "prices.csv")
    if not os.path.exists(prices_path):
        raise DataMissingError(prices_path)
    prices = pd.read_csv(prices_path, parse_dates=["date"])
    crcl = prices[prices["symbol"] == "CRCL"].set_index("date").sort_index()
    if crcl.empty:
        return {
            "status": "insufficient",
            "passed": None,
            "n_events": 0, "n_base": 0,
            "note": "prices.csv 无 CRCL 价格序列 ⇒ 样本不足，无法判定。",
        }

    fed = df["fed"].dropna()
    if fed.empty:
        return {
            "status": "insufficient",
            "passed": None,
            "n_events": 0, "n_base": 0,
            "note": "features.fed 全为空值 ⇒ 样本不足，无法判定。",
        }

    # 3) 方向变化事件日（sign 差分切换）。first_day 不构成「变化」⇒ 排除。
    direction = np.sign(fed.diff()).fillna(0.0)
    changed = direction.ne(direction.shift())
    if len(changed):
        changed.iloc[0] = False
    event_dates = fed.index[changed]
    event_dates = event_dates[event_dates.isin(crcl.index)]

    # 4) 各 horizon 的前瞻收益；事件组 vs 基线 Welch t 检验。
    close = crcl["close"].astype(float)
    results = {}
    p_values = []
    for h in H031_HORIZONS:
        fwd = close.shift(-h) / close - 1.0            # H 日前瞻收益
        fwd = fwd.dropna()
        base = fwd                                    # 基线 = 全样本
        ev = fwd.reindex(event_dates).dropna()
        n_ev, n_base = int(len(ev)), int(len(base))
        if n_ev >= H031_MIN_EVENTS and n_base >= H031_MIN_BASE:
            from scipy import stats as _st
            t_stat, p_val = _st.ttest_ind(ev.to_numpy(), base.to_numpy(),
                                          equal_var=False)
            t_stat = float(t_stat) if t_stat == t_stat else None
            p_val = float(p_val) if p_val == p_val else None
        else:
            t_stat, p_val = None, None
        if p_val is not None:
            p_values.append(p_val)
        results["h%d" % h] = {
            "n_events": n_ev, "n_base": n_base,
            "mean_event": float(ev.mean()) if n_ev else None,
            "mean_base": float(base.mean()) if n_base else None,
            "t": t_stat, "p": p_val,
        }

    n_ev_total = int(sum(r["n_events"] for r in results.values()))
    n_base_max = int(max(r["n_base"] for r in results.values()))
    if not p_values:
        return {
            "status": "insufficient", "passed": None,
            "n_events": n_ev_total, "n_base": n_base_max,
            "horizons": results,
            "note": ("样本不足：方向变化事件日 %d（需 ≥%d）/ 基线 %d（需 ≥%d），"
                     "无法做 t 检验。" % (n_ev_total, H031_MIN_EVENTS,
                                        n_base_max, H031_MIN_BASE)),
        }

    adopted = any(p <= H031_ALPHA for p in p_values)
    note = ("检验方法：fed 方向 = sign(日差分)；方向变化事件日 → CRCL 后续 "
            "4/8/16 日收益（close.shift(-H)/close-1）vs 全样本基线，各 horizon "
            "独立双样本 Welch t 检验，α=%.2f。任一 p ≤%.2f ⇒ 有显著影响 ⇒ 成立；"
            "全部 p >%.2f ⇒ 无显著影响 ⇒ 不成立（不成立判据）。"
            % (H031_ALPHA, H031_ALPHA, H031_ALPHA))
    return {
        "status": "ok",
        "passed": bool(adopted),
        "verdict": "adopted" if adopted else "falsified",
        "n_events": n_ev_total, "n_base": n_base_max,
        "horizons": results,
        "note": note,
    }


def _read_fred_series(path, sid):
    """读 FRED 版式 CSV（observation_date,<SID>）为按日期升序的 Series。

    ⚠️ FRED 列名是 observation_date 而非 date，不能用 `_read_csv`。
    缺文件 / 缺列 ⇒ 抛 DataMissingError（带**路径**与缺列名，供 reason 指回）。
    """
    if not os.path.exists(path):
        raise DataMissingError(path)
    df = pd.read_csv(path, parse_dates=["observation_date"])
    if "observation_date" not in df.columns or sid not in df.columns:
        raise DataMissingError("%s（缺列 %s）" % (path, sid))
    s = df.set_index("observation_date")[sid].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def verify_h065(df):
    """H-065：流动性挤压期中股债 60 日滚动相关性转正（避险失效）且非利率单独解释。

    口径（照 `evolution/hypotheses.md` H-065 行，**不发明**）：
      - 股端 QQQ 日收益、债端 TLT 日收益、控制量 DGS10 日变动；
      - `corr(t)` = QQQ 与 TLT 日收益的 **60 日滚动 Pearson 相关**；
      - 「挤压期」**双口径（先验写死）**：
          · 主口径（跨资产）= QQQ 与 TLT **同日下跌** 且 BAA10Y **5 日走阔 >25bp**；
          · 辅助口径（VIX）= VIX 收盘 > 全样本 80 分位 **或** VIX 单日跳升 >20%。
        🔴 两口径**都算**，**结论以主口径为准**。
      - 不成立判据（任一）：① 全样本 corr>0 占比 <20%；
        ②「低利率波动桶」corr>0 占比不高于全样本占比；③ 挤压期内 corr>0 且
        QQQ 下跌的日子里，股债同跌天数 ≤5。

    判定口径：`passed = 主口径下三条不成立判据**都未触发**`。
    （辅助口径仅作口径敏感性对照，不参与最终判定。）

    数据缺失（任一源文件/列缺失）⇒ `status="pending"` + `reason="数据缺失（路径）：…"`，
    **不抛异常、不硬凑结论**。样本窗口取 TLT ∩ BAA10Y ∩ DGS10 ∩ QQQ 的实际对齐区间，
    写入 `note`（不硬写登记草案的 2016-09-26）。

    🔴 只输出研究参考 —— **不写任何权重/仓位/规则**。
    """
    raw = config.RAW_DIR
    prices_path = os.path.join(raw, "prices.csv")
    dgs10_path = os.path.join(raw, "fred_DGS10.csv")
    baa10y_path = os.path.join(raw, "fred_BAA10Y.csv")
    vix_path = os.path.join(raw, "vix.csv")

    def _pending(reason):
        return {
            "status": "pending",
            "passed": None,
            "reason": reason,
            "note": ("数据缺失：H-065 需 QQQ/TLT（prices.csv）+ DGS10 + BAA10Y + "
                     "VIX 四路序列，缺失时挂起不硬凑结论（数据依赖见 MT-26/MT-28）。"),
        }

    # 1) QQQ / TLT 收盘（长表 ↔ 宽表）。
    if not os.path.exists(prices_path):
        return _pending("数据缺失（路径）：%s" % prices_path)
    prices = pd.read_csv(prices_path, parse_dates=["date"])
    need = ("QQQ", "TLT")
    miss = [s for s in need if s not in set(prices["symbol"])]
    if miss:
        return _pending("数据缺失（路径）：%s（无 symbol：%s）"
                        % (prices_path, ",".join(miss)))
    wide = (prices[prices["symbol"].isin(need)]
            .pivot_table(index="date", columns="symbol", values="close")
            .sort_index())

    # 2) FRED 序列（DGS10 / BAA10Y）与 VIX；缺文件/缺列 ⇒ pending。
    try:
        dgs10 = _read_fred_series(dgs10_path, "DGS10")
        baa10y = _read_fred_series(baa10y_path, "BAA10Y")
    except DataMissingError as exc:
        return _pending("数据缺失（路径）：%s" % exc.path)
    if not os.path.exists(vix_path):
        return _pending("数据缺失（路径）：%s" % vix_path)
    vix = pd.read_csv(vix_path, parse_dates=["date"])
    if "close" not in vix.columns:
        return _pending("数据缺失（路径）：%s（缺列 close）" % vix_path)
    vix = vix.set_index("date")["close"].astype(float).sort_index()

    # 3) 对齐样本：QQQ ∩ TLT ∩ DGS10 ∩ BAA10Y（VIX 用于辅助口径，单独对齐）。
    frame = pd.DataFrame({
        "qqq": wide.get("QQQ"),
        "tlt": wide.get("TLT"),
        "dgs10": dgs10,
        "baa10y": baa10y,
    }).dropna()
    if len(frame) < H065_ROLL_WINDOW + 1:
        return {
            "status": "insufficient", "passed": None,
            "n_days": int(len(frame)),
            "note": ("样本不足：对齐后仅 %d 日（需 >%d 日算 60 日滚动相关）⇒ 无法判定。"
                     % (len(frame), H065_ROLL_WINDOW)),
        }

    qqq_ret = frame["qqq"].pct_change()
    tlt_ret = frame["tlt"].pct_change()
    corr = qqq_ret.rolling(H065_ROLL_WINDOW).corr(tlt_ret)
    valid = corr.dropna()

    # 4) 全样本 corr>0 占比 + 逐年。
    pos = valid > 0
    corr_pos_ratio = float(pos.mean()) if len(valid) else float("nan")
    by_year = {int(y): float(v.mean())
               for y, v in (valid > 0).groupby(valid.index.year)}

    # 5) 利率波动分桶（|DGS10 日变动|）：按中位数把**全部 corr 有效日**分高/低两桶，
    #    再算「低利率波动桶」内的 corr>0 占比（与全样本占比同口径比较）。
    dgs_change = frame["dgs10"].diff().abs().reindex(valid.index)
    low_rate_ratio = float("nan")
    rate_split = None
    bucket_valid = dgs_change.dropna()
    if len(bucket_valid) and bucket_valid.max() > bucket_valid.min():
        rate_split = float(bucket_valid.median())
        low_days = bucket_valid.index[bucket_valid <= rate_split]
        low_rate_ratio = float((valid.reindex(low_days) > 0).mean())

    # 6) 主口径「挤压期」：QQQ 与 TLT 同日下跌 且 BAA10Y 5 日走阔 >25bp。
    co_down = (qqq_ret < 0) & (tlt_ret < 0)
    widen_bp = (frame["baa10y"] - frame["baa10y"].shift(H065_SPREAD_WINDOW)) \
        * H065_DIVISOR_BP
    primary_mask = (co_down & (widen_bp > H065_SPREAD_WIDEN_BP)).fillna(False)
    primary_squeeze_days = int(primary_mask.sum())

    # 7) 辅助口径「挤压期」：VIX 收盘 > 全样本 80 分位 或 VIX 单日跳升 >20%。
    vix_q = float(vix.quantile(H065_VIX_QUANTILE)) if len(vix) else float("nan")
    vix_jump = vix.pct_change()
    aux_raw = ((vix > vix_q) | (vix_jump > H065_VIX_JUMP_PCT)).fillna(False)
    aux_mask = aux_raw.reindex(frame.index).fillna(False).astype(bool)
    aux_squeeze_days = int(aux_mask.sum())

    # 8) 挤压期内：corr>0 占比 + corr>0 且 QQQ 下跌日里的股债同跌天数。
    qqq_down = (qqq_ret < 0)

    def _squeeze_stats(mask):
        sq = valid.index.intersection(frame.index[mask])
        n = int(len(sq))
        if not n:
            return None, n, 0
        p = float((valid.reindex(sq) > 0).mean())
        sel = sq[(valid.reindex(sq) > 0) & qqq_down.reindex(sq).fillna(False)]
        cofall = int(co_down.reindex(sel).sum())
        return p, n, cofall

    prim_ratio, prim_days, prim_cofall = _squeeze_stats(primary_mask)
    aux_ratio, aux_days, aux_cofall = _squeeze_stats(aux_mask)

    # 9) 三条不成立判据（以主口径为准）。
    c1 = not (corr_pos_ratio == corr_pos_ratio) or corr_pos_ratio < H065_POS_RATIO_FLOOR
    c2 = (low_rate_ratio == low_rate_ratio
          and low_rate_ratio <= corr_pos_ratio)
    c3 = prim_cofall <= H065_COFALL_DAYS_MIN
    primary_passed = not (c1 or c2 or c3)

    window_start = str(frame.index[0].date())
    window_end = str(frame.index[-1].date())
    note = ("口径（H-065 登记稿，先验写死）：corr(t) = QQQ 与 TLT 日收益 %d 日滚动 "
            "Pearson 相关；主口径挤压期 = QQQ 与 TLT 同日下跌 且 BAA10Y %d 日走阔 "
            ">%.0fbp；辅助口径 = VIX > 全样本 %.0f 分位 或 VIX 单日跳升 >%.0f%%。"
            "两口径都算，**结论以主口径为准**。实际样本窗口（TLT∩BAA10Y∩DGS10∩QQQ）"
            "= %s → %s（%d 交易日）。只输出研究参考，不进权重。"
            % (H065_ROLL_WINDOW, H065_SPREAD_WINDOW, H065_SPREAD_WIDEN_BP,
               100.0 * H065_VIX_QUANTILE, 100.0 * H065_VIX_JUMP_PCT,
               window_start, window_end, int(len(frame))))
    return {
        "status": "ok",
        "passed": bool(primary_passed),
        "note": note,
        "window_start": window_start,
        "window_end": window_end,
        "n_days": int(len(frame)),
        "corr": corr,
        "corr_pos_ratio": corr_pos_ratio,
        "corr_pos_ratio_by_year": by_year,
        "rate_bucket_split": rate_split,
        "low_rate_bucket_pos_ratio": low_rate_ratio,
        "primary_squeeze_mask": primary_mask,
        "primary_squeeze_days": primary_squeeze_days,
        "primary_corr_pos_ratio": prim_ratio,
        "primary_cofall_days": prim_cofall,
        "primary_passed": bool(primary_passed),
        "aux_vix_mask": aux_mask,
        "aux_vix_days": aux_squeeze_days,
        "aux_corr_pos_ratio": aux_ratio,
        "aux_cofall_days": aux_cofall,
        "falsified_by": [label for label, hit in
                         (("①全样本corr>0占比<20%", c1),
                          ("②低利率波动桶未更高", c2),
                          ("③挤压期股债同跌≤5", c3)) if hit],
    }


def _one_sided_two_prop_z(x1, n1, x2, n2):
    """单侧两比例 z 检验（H1: p1 > p2）。返回 (z, p)；不可算 ⇒ (None, None)。

    手写实现（`math.erfc` 给正态上尾），避免为一条判据引入新依赖。
    """
    if n1 <= 0 or n2 <= 0:
        return None, None
    pooled = float(x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n1 + 1.0 / n2))
    if se <= 0:
        return None, None
    z = (float(x1) / n1 - float(x2) / n2) / se
    return z, 0.5 * math.erfc(z / math.sqrt(2.0))


def verify_h068(df):
    """H-068：流动性挤压期中股债**短窗**（5 日）滚动相关显著转正（避险属性瞬时失效）。

    口径（照 `evolution/hypotheses.md` H-068 行，**不发明**）：
      - 股端 QQQ 日收益、债端 TLT 日收益；
      - `corr(t)` = QQQ 与 TLT 日收益的 **5 日滚动 Pearson 相关**（短窗 ——
        H-065 用 60 日，实测被过去两个月的正常避险行为主导 ⇒ 结构性测不出数日挤压）；
      - 「挤压期」**双口径**（两者定义都**不含** QQQ/TLT 方向 ⇒ 不循环定义）：
          · 主口径（VIX，**样本充分 ⇒ 参与判定**）= VIX 收盘 > 全样本 80 分位
            **或** VIX 单日跳升 > 20%；
          · 辅助口径（BAA10Y）= 信用利差 5 日走阔 > 25bp —— 🔴 实测样本极稀
            ⇒ **仅列明细、不参与判定**（反面教训：不得以无样本的口径定结论）。
      - 不成立判据：挤压期 `corr>0` 占比 **不显著高于**非挤压期
        （单侧两比例 z 检验 p ≥ `H068_ALPHA`）⇒ 不成立；
        挤压期样本 < `H068_MIN_SQUEEZE_DAYS` ⇒ `insufficient`（**不硬凑结论**）。

    数据缺失（QQQ/TLT 或 VIX 缺失 / 缺列）⇒ `status="pending"` +
    `reason="数据缺失（路径）：…"`，**不抛异常**。BAA10Y **可选**（缺 ⇒ 辅助明细为
    `None`，**不影响**主判定）。

    🔴 只输出研究参考 —— **不写任何权重/仓位/规则**。
    """
    raw = config.RAW_DIR
    prices_path = os.path.join(raw, "prices.csv")
    vix_path = os.path.join(raw, "vix.csv")
    baa10y_path = os.path.join(raw, "fred_BAA10Y.csv")

    def _pending(reason):
        return {
            "status": "pending",
            "passed": None,
            "reason": reason,
            "note": ("数据缺失：H-068 需 QQQ/TLT（prices.csv）+ VIX（raw/vix.csv）；"
                     "BAA10Y（fred_BAA10Y.csv）**可选**，仅作辅助明细、不参与判定。"),
        }

    # 1) QQQ / TLT 收盘（长表 ↔ 宽表）。
    if not os.path.exists(prices_path):
        return _pending("数据缺失（路径）：%s" % prices_path)
    prices = pd.read_csv(prices_path, parse_dates=["date"])
    need = ("QQQ", "TLT")
    miss = [s for s in need if s not in set(prices["symbol"])]
    if miss:
        return _pending("数据缺失（路径）：%s（无 symbol：%s）"
                        % (prices_path, ",".join(miss)))
    wide = (prices[prices["symbol"].isin(need)]
            .pivot_table(index="date", columns="symbol", values="close")
            .sort_index())

    # 2) VIX（主口径必需）。
    if not os.path.exists(vix_path):
        return _pending("数据缺失（路径）：%s" % vix_path)
    vix_df = pd.read_csv(vix_path, parse_dates=["date"])
    if "close" not in vix_df.columns:
        return _pending("数据缺失（路径）：%s（缺列 close）" % vix_path)
    vix = vix_df.set_index("date")["close"].astype(float).sort_index()

    # 3) 对齐样本：QQQ ∩ TLT ∩ VIX。
    frame = pd.DataFrame({
        "qqq": wide.get("QQQ"),
        "tlt": wide.get("TLT"),
        "vix": vix,
    }).dropna()
    if len(frame) < H068_ROLL_WINDOW + 1:
        return {
            "status": "insufficient", "passed": None,
            "n_days": int(len(frame)),
            "note": ("样本不足：对齐后仅 %d 日（需 >%d 日算 %d 日滚动相关）"
                     "⇒ 无法判定。" % (len(frame), H068_ROLL_WINDOW,
                                    H068_ROLL_WINDOW)),
        }

    qqq_ret = frame["qqq"].pct_change()
    tlt_ret = frame["tlt"].pct_change()
    corr = qqq_ret.rolling(H068_ROLL_WINDOW).corr(tlt_ret)
    valid = corr.dropna()

    # 4) 主口径挤压期（VIX 高分位 或 单日跳升）—— **不含** QQQ/TLT 方向。
    vix_q = float(frame["vix"].quantile(H068_VIX_QUANTILE))
    vix_jump = frame["vix"].pct_change()
    squeeze = (((frame["vix"] > vix_q) | (vix_jump > H068_VIX_JUMP_PCT))
               .fillna(False).astype(bool))

    sq_idx = valid.index.intersection(frame.index[squeeze])
    non_idx = valid.index.difference(sq_idx)
    n_sq, n_non = int(len(sq_idx)), int(len(non_idx))
    x_sq = int((valid.reindex(sq_idx) > 0).sum())
    x_non = int((valid.reindex(non_idx) > 0).sum())
    r_sq = (float(x_sq) / n_sq) if n_sq else float("nan")
    r_non = (float(x_non) / n_non) if n_non else float("nan")

    # 5) 报数（**不参与判定**）：当日股债同跌率（挤压 vs 非挤压）。
    co_down = (qqq_ret < 0) & (tlt_ret < 0)

    def _cofall_rate(idx):
        if not len(idx):
            return float("nan")
        return float(co_down.reindex(idx).fillna(False).mean())

    # 6) 判据：单侧两比例 z 检验（挤压期 corr>0 占比 **显著高于** 非挤压期）。
    z, p = _one_sided_two_prop_z(x_sq, n_sq, x_non, n_non)

    # 7) 辅助口径（BAA10Y，**仅明细**）：信用利差 5 日走阔 > 25bp。
    aux_days, aux_detail = None, None
    if os.path.exists(baa10y_path):
        try:
            baa = _read_fred_series(baa10y_path, "BAA10Y")
        except DataMissingError:
            baa = None
        if baa is not None:
            baa_al = baa.reindex(frame.index)
            widen = (baa_al - baa_al.shift(H068_SPREAD_WINDOW)) * H068_DIVISOR_BP
            aux_mask = (widen > H068_SPREAD_WIDEN_BP).fillna(False).astype(bool)
            aux_days = int(aux_mask.sum())
            aux_detail = [
                {"date": str(d.date()),
                 "widen_bp": round(float(widen.loc[d]), 1),
                 "qqq_ret": round(float(qqq_ret.loc[d]), 4),
                 "tlt_ret": round(float(tlt_ret.loc[d]), 4),
                 "corr": (round(float(corr.loc[d]), 3)
                          if d in valid.index else None)}
                for d in frame.index[aux_mask]
            ]

    # 8) 判定（主口径；样本不足 ⇒ insufficient，不硬凑）。
    if n_sq < H068_MIN_SQUEEZE_DAYS or n_non <= 0 or p is None:
        status, passed = "insufficient", None
    else:
        status, passed = "ok", bool(p < H068_ALPHA)

    window_start = str(frame.index[0].date())
    window_end = str(frame.index[-1].date())
    note = ("口径（H-068 登记稿，先验写死）：corr(t) = QQQ 与 TLT 日收益 %d 日滚动 "
            "Pearson 相关（**短窗**）；主口径挤压期 = VIX > 全样本 %.0f 分位 或 "
            "VIX 单日跳升 > %.0f%%（**不含** QQQ/TLT 方向 ⇒ 不循环定义）；"
            "辅助口径 = BAA10Y %d 日走阔 > %.0fbp（**仅列明细、不参与判定**，"
            "实测样本极稀）。判据：挤压期 corr>0 占比 **显著高于** 非挤压期"
            "（单侧两比例 z 检验 p < %.2f）⇒ 成立；挤压期样本 < %d ⇒ 样本不足。"
            "实际样本窗口（QQQ∩TLT∩VIX）= %s → %s（%d 交易日）。"
            "只输出研究参考，不进权重。"
            % (H068_ROLL_WINDOW, 100.0 * H068_VIX_QUANTILE,
               100.0 * H068_VIX_JUMP_PCT, H068_SPREAD_WINDOW,
               H068_SPREAD_WIDEN_BP, H068_ALPHA, H068_MIN_SQUEEZE_DAYS,
               window_start, window_end, int(len(frame))))
    return {
        "status": status,
        "passed": passed,
        "note": note,
        "window_start": window_start,
        "window_end": window_end,
        "n_days": int(len(frame)),
        "corr": corr,
        "squeeze_mask": squeeze,
        "squeeze_days": n_sq,
        "squeeze_pos_days": x_sq,
        "squeeze_pos_ratio": r_sq,
        "nonsqueeze_days": n_non,
        "nonsqueeze_pos_days": x_non,
        "nonsqueeze_pos_ratio": r_non,
        "z": z,
        "p_value": p,
        "cofall_rate_squeeze": _cofall_rate(sq_idx),
        "cofall_rate_nonsqueeze": _cofall_rate(non_idx),
        "aux_baa10y_days": aux_days,
        "aux_baa10y_detail": aux_detail,
    }


def verify_h069(df):
    """H-069：流动性挤压期中股债**同日下跌**（`co_down`）条件概率显著高于非挤压期。

    口径（照 `evolution/hypotheses.md` H-069 行，**不发明**）：
      - 股端 QQQ 日收益、债端 TLT 日收益；`co_down(t)` = (QQQ 跌 ∧ TLT 跌)（二元）；
      - 「挤压期」（沿用 H-068 主口径，**不含** QQQ/TLT 方向 ⇒ 不循环定义）=
        VIX 收盘 > 全样本 80 分位 **或** VIX 单日跳升 > 20%；
      - 🔴 **非盲登记**：判据在已知 H-068 报数（挤压 25.71% vs 非挤压 20.02%）之后确定
        ⇒ **全样本结果不构成独立验证** ⇒ 判定**以「分段稳健」为准**、结论强度降级为研究参考；
      - 判据：**全样本**挤压期同跌率**显著高于**非挤压期（单侧两比例 z 检验 p < α）
        **且** 按中位日期切前后两半段**都**显著（p < α）⇒ 成立；
        挤压期样本 < `H069_MIN_SQUEEZE_DAYS` 或任一半段 < `H069_MIN_HALF_SQUEEZE_DAYS`
        ⇒ `insufficient`（**不硬凑结论**）。

    数据缺失（QQQ/TLT 或 VIX 缺失 / 缺列）⇒ `status="pending"` +
    `reason="数据缺失（路径）：…"`，**不抛异常**。

    🔴 只输出研究参考 —— **不写任何权重/仓位/规则**。
    """
    raw = config.RAW_DIR
    prices_path = os.path.join(raw, "prices.csv")
    vix_path = os.path.join(raw, "vix.csv")

    def _pending(reason):
        return {
            "status": "pending",
            "passed": None,
            "reason": reason,
            "note": ("数据缺失：H-069 需 QQQ/TLT（prices.csv）+ VIX（raw/vix.csv）。"
                     "🔴 非盲登记 ⇒ 判定以「分段稳健」为准。"),
        }

    # 1) QQQ / TLT 收盘（长表 ↔ 宽表）。
    if not os.path.exists(prices_path):
        return _pending("数据缺失（路径）：%s" % prices_path)
    prices = pd.read_csv(prices_path, parse_dates=["date"])
    need = ("QQQ", "TLT")
    miss = [s for s in need if s not in set(prices["symbol"])]
    if miss:
        return _pending("数据缺失（路径）：%s（无 symbol：%s）"
                        % (prices_path, ",".join(miss)))
    wide = (prices[prices["symbol"].isin(need)]
            .pivot_table(index="date", columns="symbol", values="close")
            .sort_index())

    # 2) VIX（挤压期主口径必需）。
    if not os.path.exists(vix_path):
        return _pending("数据缺失（路径）：%s" % vix_path)
    vix_df = pd.read_csv(vix_path, parse_dates=["date"])
    if "close" not in vix_df.columns:
        return _pending("数据缺失（路径）：%s（缺列 close）" % vix_path)
    vix = vix_df.set_index("date")["close"].astype(float).sort_index()

    # 3) 对齐样本：QQQ ∩ TLT ∩ VIX。
    frame = pd.DataFrame({
        "qqq": wide.get("QQQ"),
        "tlt": wide.get("TLT"),
        "vix": vix,
    }).dropna()
    if len(frame) < 2:
        return {
            "status": "insufficient", "passed": None,
            "n_days": int(len(frame)),
            "note": "样本不足：对齐后仅 %d 日 ⇒ 无法判定。" % len(frame),
        }

    qqq_ret = frame["qqq"].pct_change()
    tlt_ret = frame["tlt"].pct_change()
    co_down = (qqq_ret < 0) & (tlt_ret < 0)

    # 4) 挤压期主口径（VIX 高分位 或 单日跳升）—— **不含** QQQ/TLT 方向。
    vix_q = float(frame["vix"].quantile(H069_VIX_QUANTILE))
    vix_jump = frame["vix"].pct_change()
    squeeze = (((frame["vix"] > vix_q) | (vix_jump > H069_VIX_JUMP_PCT))
               .fillna(False).astype(bool))

    # 5) 全样本：挤压 / 非挤压同跌率 + 单侧两比例 z 检验（H1：挤压期更高）。
    sq_idx = frame.index[squeeze]
    non_idx = frame.index.difference(sq_idx)
    n_sq, n_non = int(len(sq_idx)), int(len(non_idx))
    x_sq = int(co_down.reindex(sq_idx).fillna(False).sum())
    x_non = int(co_down.reindex(non_idx).fillna(False).sum())
    r_sq = (float(x_sq) / n_sq) if n_sq else float("nan")
    r_non = (float(x_non) / n_non) if n_non else float("nan")
    full_z, full_p = _one_sided_two_prop_z(x_sq, n_sq, x_non, n_non)

    # 6) 分段稳健：按样本中位日期切前后两半，两半各自做同样的 z 检验。
    half = int(len(frame) // 2)
    idx_first = frame.index[:half]
    idx_second = frame.index[half:]
    seg = []
    for lbl, idx in (("first", idx_first), ("second", idx_second)):
        s_i = idx.intersection(sq_idx)
        n_i = idx.intersection(non_idx)
        ns, nn = int(len(s_i)), int(len(n_i))
        xs = int(co_down.reindex(s_i).fillna(False).sum())
        xn = int(co_down.reindex(n_i).fillna(False).sum())
        z_i, p_i = _one_sided_two_prop_z(xs, ns, xn, nn)
        seg.append((lbl, ns, nn, xs, xn, z_i, p_i))
    first_lbl, first_n_sq, _, _, _, first_z, first_p = seg[0]
    second_lbl, second_n_sq, _, _, _, second_z, second_p = seg[1]

    # 7) 判定：全样本 + 两半段都显著 ⇒ 成立；样本不足 ⇒ insufficient。
    if (n_sq < H069_MIN_SQUEEZE_DAYS
            or first_n_sq < H069_MIN_HALF_SQUEEZE_DAYS
            or second_n_sq < H069_MIN_HALF_SQUEEZE_DAYS
            or n_non <= 0 or full_p is None):
        status, passed = "insufficient", None
    else:
        passed = bool(full_p < H069_ALPHA and first_p < H069_ALPHA
                      and second_p < H069_ALPHA)
        status = "ok"

    window_start = str(frame.index[0].date())
    window_end = str(frame.index[-1].date())
    note = ("口径（H-069 登记稿，**非盲登记**，先验写死）：co_down(t) = (QQQ 跌 ∧ TLT 跌)"
            "（二元）；挤压期沿用 H-068 主口径 = VIX > 全样本 %.0f 分位 或 VIX 单日跳升 > %.0f%%"
            "（**不含** QQQ/TLT 方向 ⇒ 不循环定义）。判据：全样本挤压期同跌率**显著高于**"
            "非挤压期（单侧两比例 z 检验 p < %.2f）**且分段稳健**（按中位日期切前后两半、"
            "两半都 p < %.2f）⇒ 成立；挤压期样本 < %d 或任一半段 < %d ⇒ 样本不足。"
            "实际样本窗口（QQQ∩TLT∩VIX）= %s → %s（%d 交易日）。🔴 非盲登记 ⇒ 全样本"
            "结果不构成独立验证，结论强度降级为**研究参考**；只输出研究参考，不进权重。"
            % (100.0 * H069_VIX_QUANTILE, 100.0 * H069_VIX_JUMP_PCT,
               H069_ALPHA, H069_ALPHA, H069_MIN_SQUEEZE_DAYS,
               H069_MIN_HALF_SQUEEZE_DAYS, window_start, window_end,
               int(len(frame))))
    return {
        "status": status,
        "passed": passed,
        "note": note,
        "window_start": window_start,
        "window_end": window_end,
        "n_days": int(len(frame)),
        "squeeze_mask": squeeze,
        "full_n_sq": n_sq,
        "full_rate_sq": r_sq,
        "full_rate_non": r_non,
        "full_z": full_z,
        "full_p": full_p,
        "first_half_n_sq": first_n_sq,
        "first_half_z": first_z,
        "first_half_p": first_p,
        "second_half_n_sq": second_n_sq,
        "second_half_z": second_z,
        "second_half_p": second_p,
        "nonblind_registration": True,
    }


# 单独实现（custom）的假说：id -> (runner, desc, fields)
CUSTOM = {
    "H-010": (verify_h010, "zone 由 fg_index 固定边界驱动且边界稳定（区间重叠率 ≤20%）",
              "fg_index + zone"),
    "H-012": (verify_h012, "布尔位触发依赖 fg_index 极值（>=80 或 <=35）",
              "fg_index + trend_blocked_us/trend_blocked_crypto"),
    "H-013": (verify_h013, "档位切换后 fg_index 滚动 10 日振幅收窄",
              "fg_index + zone"),
    "H-014": (verify_h014, "zone 越高 fg_index 区间越高（单调映射，无重叠）",
              "fg_index + zone"),
    "H-015": (verify_h015, "core_position 与 zone 反向绑定", "zone + core_position"),
    "H-019": (verify_h019, "zone 与 fg_index 同向联动（秩相关 ≥0.5）",
              "zone + fg_index"),
    "H-020": (verify_h020, "core_position=0.225 区间布尔位零触发",
              "core_position + trend_blocked_us/trend_blocked_crypto"),
    "H-021": (verify_h021, "zone=2.0 区间与 fg_index 回落区间时间重合",
              "zone + fg_index"),
    "H-031": (verify_h031, "fed 方向变化前后 CRCL 后续 4/8/16 日收益差异（t 检验）",
              "features.fed + CRCL 价格（prices.csv）"),
    "H-065": (verify_h065, "挤压期中股债 60 日滚动相关性转正（避险失效）且非利率单独解释",
              "QQQ/TLT（prices.csv）+ DGS10 + BAA10Y + VIX（raw/）"),
    "H-068": (verify_h068, "挤压期中股债 5 日滚动相关性**显著高于**非挤压期（避险瞬时失效）",
              "QQQ/TLT（prices.csv）+ VIX（raw/vix.csv）［BAA10Y 可选，仅明细］"),
    "H-069": (verify_h069, "挤压期中股债**同日下跌**（co_down）概率**显著高于**非挤压期（分段稳健）",
              "QQQ/TLT（prices.csv）+ VIX（raw/vix.csv）"),
}


# 假说注册表：id -> 元数据。
#   kind="trigger"：复用 WT-05 通用触发率框架（selector + pass_when）。
#   kind="custom" ：形态不同，单独实现（runner 指向 CUSTOM 里的验证函数）。
#   kind="pending"：数据源未接入或样本不足 ⇒ 等待数据，不硬凑结论。
HYPOTHESES = {
    # ---------------------------------------------------------- 触发率类
    "H-024": {
        "kind": "trigger",
        "desc": "fg_index≥70 的日期中 trend_blocked 触发率 ≥50% → 不成立",
        "selector": _mask_fg_ge_70,
        "pass_when": "low",
        "fields": "fg_index + trend_blocked_us/trend_blocked_crypto",
    },
    "H-025": {
        "kind": "trigger",
        "desc": "zone=3.0 且 fg_index≥70 的日期中布尔位触发率 ≥50% → 不成立",
        "selector": _mask_zone3_and_fg70,
        "pass_when": "low",
        "fields": "zone + fg_index + trend_blocked_us/trend_blocked_crypto",
    },
    "H-037": {
        "kind": "trigger",
        "desc": "fg_index≥70 的日期中布尔位触发率 <50% → 成立（H-024 的反向表述）",
        "selector": _mask_fg_ge_70,
        "pass_when": "low",
        "fields": "fg_index + trend_blocked_us/trend_blocked_crypto",
    },
    "H-029": {
        "kind": "trigger",
        "desc": "fg_index≥70 的日期中 trend_blocked 触发率 ≥50% → 成立",
        "selector": _mask_fg_ge_70,
        "pass_when": "high",
        "fields": "fg_index + trend_blocked_us/trend_blocked_crypto",
    },
    "H-032": {
        "kind": "trigger",
        "desc": "zone=3.0 的日期中 trend_blocked 触发率 ≥50% → 不成立",
        "selector": _mask_zone3,
        "pass_when": "low",
        "fields": "zone + trend_blocked_us/trend_blocked_crypto",
    },
    # ---------------------------------------------------------- 单独实现（custom）
    "H-010": {"kind": "custom", "desc": CUSTOM["H-010"][1],
              "fields": CUSTOM["H-010"][2]},
    "H-012": {"kind": "custom", "desc": CUSTOM["H-012"][1],
              "fields": CUSTOM["H-012"][2]},
    "H-013": {"kind": "custom", "desc": CUSTOM["H-013"][1],
              "fields": CUSTOM["H-013"][2]},
    "H-014": {"kind": "custom", "desc": CUSTOM["H-014"][1],
              "fields": CUSTOM["H-014"][2]},
    "H-015": {"kind": "custom", "desc": CUSTOM["H-015"][1],
              "fields": CUSTOM["H-015"][2]},
    "H-019": {"kind": "custom", "desc": CUSTOM["H-019"][1],
              "fields": CUSTOM["H-019"][2]},
    "H-020": {"kind": "custom", "desc": CUSTOM["H-020"][1],
              "fields": CUSTOM["H-020"][2]},
    "H-021": {"kind": "custom", "desc": CUSTOM["H-021"][1],
              "fields": CUSTOM["H-021"][2]},
    "H-031": {"kind": "custom", "desc": CUSTOM["H-031"][1],
              "fields": CUSTOM["H-031"][2]},
    "H-065": {"kind": "custom", "desc": CUSTOM["H-065"][1],
              "fields": CUSTOM["H-065"][2]},
    "H-068": {"kind": "custom", "desc": CUSTOM["H-068"][1],
              "fields": CUSTOM["H-068"][2]},
    "H-069": {"kind": "custom", "desc": CUSTOM["H-069"][1],
              "fields": CUSTOM["H-069"][2]},
    # ---------------------------------------------------------- 挂起（数据缺失）
    "H-027": {
        "kind": "pending",
        "desc": "AXTX 浮亏 ≤-20% 的日期中布尔位触发率 ≥50% → 不成立",
        "selector": None,
        "pass_when": "low",
        "fields": "AXTX 浮亏（数据源缺失）+ trend_blocked_us/trend_blocked_crypto",
        "missing_dep": "features.csv / portfolio_features.csv 无 AXTX 浮亏列",
    },
    "H-040": {
        "kind": "pending",
        "desc": "AXTX 浮亏 >20% 的日期中布尔位触发率 >0.5 → 不成立",
        "selector": None,
        "pass_when": "low",
        "fields": "AXTX 浮亏（数据源缺失）+ trend_blocked_us/trend_blocked_crypto",
        "missing_dep": "features.csv / portfolio_features.csv 无 AXTX 浮亏列",
    },
}

# 挂起假说（数据源未接入 / 样本不足 / 缺列）。三要素照录 hypotheses.md。
#   id -> (desc, missing_dep)
PENDING = {
    "H-006": ('账户累计盈亏日差分 × fg_index 的 Spearman 相关（≥60 交易日）', 'Data/accounts.csv（本机仅 1 日快照，需 ≥60 交易日）'),
    "H-008": ('杠杆标的占比 vs 累计盈亏日变动回归（≥40 交易日）', 'Data/positions.csv（本机仅 1 日快照，需 ≥40 交易日）'),
    "H-009": ('占比>28% 标的 T+10 负收益比例 vs 占比<20% 对照组', 'Data/positions.csv（本机仅 1 日快照，需 T+10 前瞻）'),
    "H-011": ('信号升降期账户日均浮亏变化绝对值比较', 'Data/accounts.csv / Data/positions.csv（09-25/09-29 快照缺失）'),
    "H-017": ('杠杆 ETF 组 vs BTC 组市值变动率比较（10-03↔10-07）', 'Data/positions.csv（本机仅 2026-09-22 一日快照）'),
    "H-022": ('5 只杠杆 ETF vs BTC-USDT 浮亏率比较（10-07/10-08）', 'Data/positions.csv（本机仅 2026-09-22 一日快照）'),
    "H-023": ('半凯利仓位 vs 规则仓位 walk-forward 净值回测', '胜率/盈亏比估计（样本 <60 日，置信度不足）'),
    "H-040": ('AXTX 浮亏占组合浮亏的比重', 'AXTX 浮亏列不存在（MT-34 / MT-35 实测 ✗）'),
    "H-028": ('现金>0 且累计盈亏<0 的频率', 'Data/accounts.csv（本机仅 1 日快照）'),
    "H-030": ('量价-资金背离（价格/成交上涨而 TVL 未跟随）分组对比', 'DeFi TVL 数据源未接入（B 类待数据）'),
    "H-034": ('稳定币使用效率 = 链上月交易量/流通量 的领先性 IC', '稳定币链上交易量数据源未接入（B 类待数据）'),
    "H-038": ('zone 2.0 期间累计盈亏变化', 'Data/accounts.csv（本机仅 1 日快照）'),
    "H-041": ('position_multiplier 降档前后 fg_index 振幅', 'position_multiplier 列不存在（虚构列）'),
}
for _hid, (_desc, _dep) in PENDING.items():
    HYPOTHESES[_hid] = {"kind": "pending", "desc": _desc, "selector": None,
                        "pass_when": "low", "fields": _dep,
                        "missing_dep": _dep}

# 全部支持的假说（含 A-3 原案）——供 --help 与默认运行使用。
# 顺序：原案（H-005/H-007）→ 触发率类 → 单独实现 → 挂起，均按编号升序。
_TRIGGER_IDS = sorted(h for h, s in HYPOTHESES.items() if s["kind"] == "trigger")
_CUSTOM_IDS = sorted(h for h, s in HYPOTHESES.items() if s["kind"] == "custom")
_PENDING_IDS = sorted(h for h, s in HYPOTHESES.items() if s["kind"] == "pending")
SUPPORTED = ["H-005", "H-007"] + _TRIGGER_IDS + _CUSTOM_IDS + _PENDING_IDS


def _run_custom(df, hid):
    """跑一条单独实现的假说，返回 (meta, text_block)。

    runner 可在结果里带 ``status``（默认 "ok"）声明挂起 / 样本不足
    （如 H-031 缺 fed 列 ⇒ "pending"）；``reason`` 作为挂起原因。
    """
    runner, desc, fields = CUSTOM[hid]
    result = runner(df)
    passed = result.get("passed")
    status = result.get("status", "ok")
    meta = {"id": hid, "status": status, "passed": passed, "result": result}
    if result.get("reason"):
        meta["reason"] = result["reason"]
    verdict = ("无法判定" if passed is None
               else ("成立" if passed else "不成立"))
    text = ["### %s%s" % (hid, "（挂起）" if status == "pending" else ""),
            "- 判据：%s" % desc,
            "- 字段：%s" % fields]
    if result.get("reason"):
        text.append("- 状态：%s" % result["reason"])
    _skip = ("passed", "note", "status", "reason", "verdict")
    for key, val in result.items():
        if key in _skip:
            continue
        text.append("- %s：%s" % (key, val))
    text += ["- 判定：%s" % verdict, "- 口径声明：%s" % result["note"]]
    return meta, text


def verify_revised(df, hid):
    """跑一条非原案假说，返回 (meta, text_block)。

    kind="trigger" ⇒ 通用触发率框架；kind="custom" ⇒ 单独实现；
    kind="pending" ⇒ 挂起（数据缺失/样本不足）。
    """
    spec = HYPOTHESES[hid]
    if spec["kind"] == "custom":
        return _run_custom(df, hid)
    if spec["selector"] is None:
        meta = {"id": hid, "status": "pending",
                "reason": "数据缺失：%s" % spec.get("missing_dep", "未知"),
                "passed": None}
        text = ["### %s（挂起）" % hid,
                "- 判据：%s" % spec["desc"],
                "- 状态：挂起 —— 数据缺失：%s" % spec.get("missing_dep", "未知")]
        return meta, text
    stats = trigger_rate_for_mask(df, spec["selector"](df))
    passed = judge_trigger_rate(stats, spec["pass_when"])
    meta = {"id": hid, "status": "ok", "passed": passed, "stats": stats}
    verdict = ("无法判定" if passed is None
               else ("成立" if passed else "不成立"))
    text = ["### %s" % hid,
            "- 判据：%s" % spec["desc"],
            "- 字段：%s" % spec["fields"],
            "- 子集样本数：%d" % stats["n"],
            "- trend_blocked_us 触发 %d / %.1f%%"
            % (stats["n_us"], 100.0 * stats["rate_us"]),
            "- trend_blocked_crypto 触发 %d / %.1f%%"
            % (stats["n_crypto"], 100.0 * stats["rate_crypto"]),
            "- 合并（任一为 True）触发 %d / %.1f%%"
            % (stats["n_any"], 100.0 * stats["rate_any"]),
            "- 判定：%s" % verdict]
    return meta, text


# ------------------------------------------------------------------ 输出
def _json(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def append_results(blocks, dry_run=False, out_path=None):
    """追加写 evolution/hypothesis_results.md（**不覆盖**已有内容）。"""
    out = out_path or os.path.join(config.ROOT, "evolution",
                                   "hypothesis_results.md")
    if dry_run:
        return out
    existing = ""
    if os.path.exists(out):
        with open(out, "r", encoding="utf-8") as fh:
            existing = fh.read()
    if existing and not existing.endswith("\n"):
        existing += "\n"
    payload = "\n".join(blocks) + "\n"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(existing + payload)
    return out


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HYP_TABLE_PATH = os.path.join(_REPO_ROOT, "evolution", "hypotheses.md")

#: 状态列**固定枚举**（体检 §五②：状态只用固定枚举、不加粗）。
#: 允许「枚举值 + 全角括号后缀」（如 `open（修订口径）`）⇒ 取前缀比对。
VALID_STATES = ("open", "verifying", "adopted", "falsified", "archived",
                "pending-revise")

#: 表格列数（`| id | 标题 | 假设 | 判据 | 数据 | 状态 | 备注 |`）。
HYP_TABLE_COLS = 7

#: 挂起假说在表内**允许**的状态（挂起 = 等数据/等样本 ⇒ 不该已归档/已采纳）。
_PENDING_ALLOWED_STATES = ("open", "verifying", "pending-revise")


def check_hypotheses_table(path=None):
    """对 `evolution/hypotheses.md` 做**结构自检**（体检报告 §五 ①②③）。

    动机：2026-10-16 体检发现 **4 行表格破损长期存在** ✗（裸 `|` 未转义 ⇒
    列数错位）+ 状态格式不统一（`**falsified**` ✗）+ 状态与备注脱钩
    （H-005 ✗）—— 这三类问题**都没有自动校验** ⇒ 会反复发生。

    三条断言：
      ① **列数 == 7**（裸 `|` 未转义 ⇒ 直接报错并给出修复提示）；
      ② **状态 ∈ 固定枚举**（`VALID_STATES`；允许 `open（…）` 这类后缀）；
      ③ **`PENDING` 与表内状态交叉一致**（挂起假说不得是 `adopted`/`archived`，
         且 `PENDING` 里的 id 必须真实存在于表中）。

    :param path: 表格路径；默认 `evolution/hypotheses.md`。
    :returns: ``(errors, warnings)`` —— 两个字符串列表；``errors`` 非空 ⇒ 应失败。
    """
    path = path or HYP_TABLE_PATH
    errors, warnings = [], []
    if not os.path.exists(path):
        return ["假说表缺失：%s" % path], warnings

    split = re.compile(r"(?<!\\)\|")  # 只按**未转义**的竖线切分
    rows, seen = {}, []
    with open(path, encoding="utf-8") as fh:
        for lineno, ln in enumerate(fh, 1):
            if not ln.lstrip().startswith("|"):
                continue
            cells = [c.strip() for c in split.split(ln.strip().strip("|"))]
            if len(cells) < 2 or not re.match(r"^H-\d+$", cells[0]):
                continue
            hid = cells[0]
            seen.append(hid)
            if hid in rows:
                errors.append("① %s 重复出现（行 %d）" % (hid, lineno))
            rows[hid] = cells
            if len(cells) != HYP_TABLE_COLS:
                errors.append(
                    "① %s 列数 = %d（应为 %d）⇒ 疑似**裸 `|` 未转义**"
                    "（行 %d）" % (hid, len(cells), HYP_TABLE_COLS, lineno))

    for hid in seen:
        cells = rows[hid]
        if len(cells) != HYP_TABLE_COLS:
            continue
        state = cells[5]
        base = re.split(r"[（(]", state, 1)[0].strip()
        if base not in VALID_STATES:
            errors.append("② %s 状态 = %r 不在固定枚举 %s"
                          % (hid, state, list(VALID_STATES)))
        elif state != base:
            warnings.append("② %s 状态带后缀 = %r（枚举值 %r）"
                            % (hid, state, base))

    for hid in sorted(PENDING):
        if hid not in rows:
            errors.append("③ PENDING 里的 %s 不在假说表中" % hid)
        elif len(rows[hid]) == HYP_TABLE_COLS:
            base = re.split(r"[（(]", rows[hid][5], 1)[0].strip()
            if base not in _PENDING_ALLOWED_STATES:
                errors.append("③ PENDING 的 %s 状态 = %r ⇒ 挂起假说不应是"
                              "已归档/已采纳" % (hid, rows[hid][5]))

    return errors, warnings


#: 任务表（`| WT-xx |` / `| MT-xx |`）—— 2026-10-19 起同样做结构自检。
TASK_TABLES = ("docs/mac-tasks.md", "docs/windows-tasks.md")


def check_task_tables(paths=None):
    """任务表结构自检：每条 `WT-` / `MT-` 行的**格数必须与表头一致** ✓。

    动机：MT-35 自己踩了 `|累计盈亏|` ✗（未转义的绝对值竖线 ⇒ 5 格变 6 格 ✗），
    而 `--check-table` 当时只管 `hypotheses.md` ✗。

    注意：**不能**用「朴素切分 vs 转义感知切分」的差值判定 ✗ —— 正确转义的 `\\|`
    也会让两者不等 ✓（试过，会全员误报 ✗）。真正的判据只能是「与表头格数比对」✓。

    :returns: 错误列表（空 ⇒ 通过）。
    """
    errors = []
    split = re.compile(r"(?<!\\)\|")
    for rel in (paths or TASK_TABLES):
        path = os.path.join(_REPO_ROOT, rel)
        if not os.path.exists(path):
            continue
        ncol = None
        with open(path, encoding="utf-8") as fh:
            for lineno, ln in enumerate(fh, 1):
                if not ln.lstrip().startswith("|"):
                    continue
                cells = split.split(ln.strip().strip("|"))
                if ncol is None:
                    ncol = len(cells)          # 首个表格行 = 表头
                    continue
                if set("".join(cells)) <= set("-: "):
                    continue                   # 分隔行
                if re.match(r"^\s*(W|M)T-\d+\s*$", cells[0]):
                    if len(cells) != ncol:
                        errors.append("%s %s 格数 = %d（表头 %d）✗ ⇒ 疑似**未转义的 `|`**（行 %d）"
                                      % (rel, cells[0].strip(), len(cells), ncol, lineno))
    return errors


def _run_check_table(path=None):
    """`--check-table` 入口：打印自检结果，返回退出码（0 通过 / 1 有错）。"""
    errors, warnings = check_hypotheses_table(path)
    print("假说表自检：%s" % (path or HYP_TABLE_PATH))
    for w in warnings:
        print("  ⚠️  %s" % w)
    if errors:
        for e in errors:
            print("  ❌ %s" % e)
        print("\n❌ 自检未通过：%d 个错误 / %d 个警告" % (len(errors), len(warnings)))
        return 1
    print("  ✅ ① 列数 == %d ② 状态 ∈ 固定枚举 ③ PENDING 交叉一致"
          % HYP_TABLE_COLS)

    task_errors = check_task_tables()
    print("任务表自检：%s" % ", ".join(TASK_TABLES))
    for e in task_errors:
        print("  ❌ %s" % e)
    if task_errors:
        print("\n❌ 自检未通过：任务表 %d 个错误" % len(task_errors))
        return 1
    print("  ✅ ④ 任务表无未转义的 `|`（列不串格）")
    print("\n✅ 自检通过（%d 个警告）" % len(warnings))
    return 0


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog="verify_hypotheses.py",
        description="假说验证：A-3 原案（H-005/H-007）+ WT-05/WT-07 覆盖全部 open 假说。\n"
                    "支持的假说（共 %d 条）：\n  - 原案：%s\n"
                    "  - 触发率类（复用通用框架）：%s\n"
                    "  - 单独实现（形态不同）：%s\n"
                    "  - 挂起（数据缺失/样本不足）：%s"
                    % (len(SUPPORTED), ", ".join(["H-005", "H-007"]),
                       ", ".join(_TRIGGER_IDS), ", ".join(_CUSTOM_IDS),
                       ", ".join(_PENDING_IDS)),
        epilog="支持哪些假说（全部 %d 条）：%s\n"
               "字段限定：zone / core_position / fg_index / "
               "trend_blocked_us / trend_blocked_crypto\n"
               "数据源：features.csv + portfolio_features.csv（走 fg_system.config 路径）\n"
               "输出：默认只打印到 stdout；传 --out 才写文件（不覆盖）"
               % (len(SUPPORTED), ", ".join(SUPPORTED)),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-H", "--hypothesis", action="append", default=None,
                   choices=SUPPORTED, metavar="ID",
                   help="只跑指定假说（可重复）。默认全部：%s"
                        % ", ".join(SUPPORTED))
    p.add_argument("--dry-run", action="store_true",
                   help="只检查数据是否存在并打印，不写结果文件。"
                        "数据缺失时打印「数据缺失（路径）」并以退出码 2 结束。")
    p.add_argument("--out", default=None,
                   help="结果文件路径。**默认不传 ⇒ 只打印 stdout，不写文件**；"
                        "显式传此参数才追加写（不覆盖已有内容）。")
    p.add_argument("--check-table", action="store_true",
                   help="只对 evolution/hypotheses.md 做**表格结构自检**"
                        "（列数 == %d / 状态 ∈ 固定枚举 / PENDING 交叉一致），"
                        "不跑任何假说。有错 ⇒ 退出码 1。" % HYP_TABLE_COLS)
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    wanted = args.hypothesis or SUPPORTED

    if args.check_table:
        return _run_check_table()

    if args.dry_run:
        return _dry_run(wanted)

    try:
        df = load_features()
    except DataMissingError as exc:
        print("❌ 数据缺失（路径）：%s" % exc.path, file=sys.stderr)
        return 2
    print("样本：%d 行（fg_index + us_core 均非空）" % len(df))

    blocks = []
    if "H-005" in wanted:
        h005, h005_meta = verify_h005(df)
        print("\n=== H-005 分箱统计 ===")
        print(h005.to_string(index=False))
        print("40-50 / 55-70 均值比: %.3f  判定: %s"
              % (h005_meta["ratio_40_55"],
                 "通过" if h005_meta["passed"] else "不通过"))
        blocks += ["## H-005：fg_index 分箱 vs 核心仓（WT-05 复跑）", "",
                   "| 箱 | 样本数 | us_core 均值 | us_core 中位数 | target 均值 |",
                   "|---|---|---|---|---|"]
        for _, r in h005.iterrows():
            blocks.append("| %s | %d | %.4f | %.4f | %.4f |"
                          % (r["bin"], r["n"], r["us_core_mean"],
                             r["us_core_median"], r["target_mean"]))
        blocks += ["",
                   "判定：%s（40-50/55-70 核心仓均值比 %.3f）"
                   % ("通过" if h005_meta["passed"] else "不通过",
                      h005_meta["ratio_40_55"] or float("nan")),
                   "口径声明：%s" % h005_meta["note"], ""]

    if "H-007" in wanted:
        try:
            h007 = verify_h007(df)
        except DataMissingError as exc:
            print("❌ 数据缺失（路径）：%s" % exc.path, file=sys.stderr)
            return 2
        print("\n=== H-007 布尔位分组 ===")
        print(_json(h007[1] if isinstance(h007, tuple) else h007))
        blocks += ["## H-007：trend_blocked_us 分组回撤（WT-05 复跑）", ""]
        if h007:
            blocks += ["- False 组（未阻断）%d 日 最大回撤 %.4f"
                       % (h007["n_false"], h007["mdd_false"]),
                       "- True 组（阻断）%d 日 最大回撤 %.4f"
                       % (h007["n_true"], h007["mdd_true"]),
                       "- 判定（False 组回撤幅度更小才成立）：%s"
                       % ("通过" if h007["passed_abs_smaller"] else "不通过"),
                       "- 口径声明：%s" % h007["note"], ""]

    revised = [h for h in wanted if h in HYPOTHESES]
    if revised:
        print("\n=== 修订口径假说（触发率/单独实现/挂起）===")
        blocks += ["## WT-05/WT-07 修订口径批量（2026-10-10）", ""]
        for hid in revised:
            meta, text = verify_revised(df, hid)
            print("[%s] %s" % (hid, meta.get("status")))
            for line in text:                        # 判定/数字也打到 stdout
                if line.startswith(("- 判定：", "- 状态：", "- 判据：", "- 口径")):
                    print("    %s" % line)
            blocks += text + [""]
            # A3c 尝试台账（规划 v2.0 A3c）：假说重验即登记（幂等，同 commit 不虚增）
            from fg_system import attempts
            attempts.append_attempt("hypothesis", hid, meta.get("status", "ok"))

    if args.out:
        out = append_results(blocks, dry_run=False, out_path=args.out)
        print("\n✅ 结果已追加写入 %s" % out)
    else:
        print("\n（默认不写文件；如需落盘请显式传 --out <路径>）")
    return 0


def _dry_run(wanted):
    """只检查数据是否存在，不写文件。

    数据缺失 ⇒ 打印「数据缺失（路径）」并返回退出码 2（不崩溃）。
    数据齐备 ⇒ 列出将验证的假说（含「等待数据」的挂起项）并返回 0。
    """
    missing = missing_dependencies()
    for path in missing:
        print("数据缺失（路径）：%s" % path)
    if missing:
        print("[dry-run] 数据缺失，共 %d 个文件；未写任何文件。" % len(missing))
        return 2
    print("[dry-run] 数据齐备：")
    for path in DATA_DEPENDENCIES():
        print("  - %s" % path)
    print("[dry-run] 将验证的假说（%d 条）：%s" % (len(wanted), ", ".join(wanted)))
    waiting = [h for h in wanted if HYPOTHESES.get(h, {}).get("kind") == "pending"]
    if waiting:
        print("[dry-run] 等待数据（数据源未接入/样本不足，将标注挂起）：%s"
              % ", ".join(waiting))
    print("[dry-run] 未写任何文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
