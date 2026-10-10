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
    **H-010 / H-012**（极值依赖 / 切换点判据）+ H-013~H-015 / H-019~H-021。
  - ``pending``：**数据源未接入或样本不足** ⇒ 走「等待数据」分支，dry-run 报
    「数据缺失（路径）」，不硬凑结论。
    覆盖：H-006 / H-008 / H-009 / H-011 / H-016 / H-017 / H-018 / H-022 / H-023
    / H-026 / H-028 / H-030 / H-031 / H-033 / H-034 / H-035 / H-036 / H-038
    / H-039 / H-041。

**数据可用性（本机实测 2026-10-10）**：`features.csv`（2513 行，至 2026-09-18）
与 `portfolio_features.csv`（2518 行，至 2026-09-25）齐备；`positions.csv` /
`accounts.csv` **仅 2026-09-22 一日快照** ⇒ 一切「多日快照 / 账户盈亏」类判据
无样本（H-006/008/009/011/016/017/018/022/023/028/033/038/039）；
`features.csv` **无 fed 列**、**无 position_multiplier 列** ⇒ H-031/H-035/H-041 缺列；
TVL / 稳定币使用效率数据源**未接入** ⇒ H-030/H-034 等待数据。

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
import os
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
    "H-006": ("账户累计盈亏日差分 × fg_index 的 Spearman 相关（≥60 交易日）",
              "Data/accounts.csv（本机仅 1 日快照，需 ≥60 交易日）"),
    "H-008": ("杠杆标的占比 vs 累计盈亏日变动回归（≥40 交易日）",
              "Data/positions.csv（本机仅 1 日快照，需 ≥40 交易日）"),
    "H-009": ("占比>28% 标的 T+10 负收益比例 vs 占比<20% 对照组",
              "Data/positions.csv（本机仅 1 日快照，需 T+10 前瞻）"),
    "H-011": ("信号升降期账户日均浮亏变化绝对值比较",
              "Data/accounts.csv / Data/positions.csv（09-25/09-29 快照缺失）"),
    "H-016": ("零触发期股票账户累计盈亏扩大幅度 <20%",
              "Data/accounts.csv（本机仅 1 日快照，需区间首末对比）"),
    "H-017": ("杠杆 ETF 组 vs BTC 组市值变动率比较（10-03↔10-07）",
              "Data/positions.csv（本机仅 2026-09-22 一日快照）"),
    "H-018": ("fg_index 变化 × 1~3 日滞后累计盈亏变化相关",
              "Data/accounts.csv（本机仅 1 日快照）"),
    "H-022": ("5 只杠杆 ETF vs BTC-USDT 浮亏率比较（10-07/10-08）",
              "Data/positions.csv（本机仅 2026-09-22 一日快照）"),
    "H-023": ("半凯利仓位 vs 规则仓位 walk-forward 净值回测",
              "胜率/盈亏比估计（样本 <60 日，置信度不足）"),
    "H-026": ("GDXU 占比 >20% vs ≤20% 的组合日收益绝对值均值",
              "Data/positions.csv（本机仅 1 日快照，无 GDXU 占比时序）"),
    "H-028": ("现金>0 且累计盈亏<0 的频率",
              "Data/accounts.csv（本机仅 1 日快照）"),
    "H-030": ("量价-资金背离（价格/成交上涨而 TVL 未跟随）分组对比",
              "DeFi TVL 数据源未接入（B 类待数据）"),
    "H-031": ("fed 因子方向变化前后 CRCL 收益差异（样本 338/240）",
              "features.csv 无 fed 列（因子未落库；CRCL 价格样本已 330 行，"
              "缺的是 fed 输入）"),
    "H-033": ("币股经营现金流型 vs Crypto Beta 型分组后续收益差异",
              "币股上市不足一年，市场下跌期样本不足"),
    "H-034": ("稳定币使用效率 = 链上月交易量/流通量 的领先性 IC",
              "稳定币链上交易量数据源未接入（B 类待数据）"),
    "H-035": ("position_multiplier=3.0 vs 2.0 的布尔位触发率",
              "position_multiplier 列不存在（虚构列，同 H-005 口径问题）"),
    "H-036": ("GDXU 占比 >20% 日收益绝对值均值 vs 之前",
              "Data/positions.csv（本机仅 1 日快照，无 GDXU 占比时序）"),
    "H-038": ("zone 2.0 期间累计盈亏变化",
              "Data/accounts.csv（本机仅 1 日快照）"),
    "H-039": ("杠杆标的占比 >60% 期间组合日收益绝对值均值",
              "Data/positions.csv（本机仅 1 日快照，无占比时序）"),
    "H-041": ("position_multiplier 降档前后 fg_index 振幅",
              "position_multiplier 列不存在（虚构列）"),
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
    """跑一条单独实现的假说，返回 (meta, text_block)。"""
    runner, desc, fields = CUSTOM[hid]
    result = runner(df)
    passed = result.get("passed")
    meta = {"id": hid, "status": "ok", "passed": passed, "result": result}
    verdict = ("无法判定" if passed is None
               else ("成立" if passed else "不成立"))
    text = ["### %s" % hid,
            "- 判据：%s" % desc,
            "- 字段：%s" % fields]
    for key, val in result.items():
        if key in ("passed", "note"):
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
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    wanted = args.hypothesis or SUPPORTED

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
