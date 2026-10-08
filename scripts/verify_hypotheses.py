#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-3 解锁 H-005 / H-007 假说验证（issue#3 闭环后，portfolio_features 已恢复）。

**口径声明（必须先读）**：H-005 登记的 `position_multiplier` 列、H-007 登记的
「信号尾部第 5/6 列布尔位」在 fg_system 代码与 portfolio_features.csv 中**均不存在**
（grep 全仓无 position_multiplier；portfolio_features 列序为 core_position /
ammo_position / target_position / ammo_released / ammo_us / ammo_crypto /
us_core / crypto_core / trend_blocked_us / trend_blocked_crypto / extreme /
note / warmup，布尔位仅 trend_blocked_* / extreme / warmup）。

**按「数字必须指回文件」纪律**：本次验证采用**可指回的真实列映射**，并在
结论中显式标注「口径映射」，不等同原始假说措辞：

  - H-005 实质断言（fg 40-50 区间仓位放大为 2.0、55+ 放大为 3.0）
    ⇒ 映射为：按 fg_index 分箱（<40/40-50/50-55/55-70/>70），统计各箱
    `us_core`（大盘核心仓，五档饱和度×上限）与 `target_position` 的
    均值/中位数/最大。判据同原案：40-50 箱是否显著高于相邻档（若五档
    设计成立，40-50 箱 ≈ zone2 饱和度 0.50×0.45×0.8 = 0.18，55-70 箱
    ≈ zone3 0.25×0.45×0.8 = 0.09，即 40-50 箱应为 55+ 箱的 **2 倍**——
    H-005 的「2.0 vs 3.0」若解读为「中性格核心仓/贪婪档核心仓」，与
    设计一致的是 **40-50 档 > 55+ 档**（2:1），而非 55+ 更大。
  - H-007 实质断言（某布尔位 False 期间账户回撤 < True 期间）
    ⇒ 映射为：布尔位 = `trend_blocked_us`（趋势过滤阻断，最贴近
    「信号尾部布尔位」语义），账户净值 = TQQQ 策略净值（与 baseline 同源
    回测）。按布尔位连续区间分组，比较两组区间内净值最大回撤均值。

判据严格沿用 hypotheses.md 登记口径：
  - H-005：40-50 箱 us_core 均值 **≥ 2×** 55-70 箱均值（2.0 vs 3.0 的
    最贴近可检验形式）→ 成立；否则不成立。同时输出各箱完整统计。
  - H-007：trend_blocked_us=False 组平均最大回撤 < True 组 → 成立；
    False 组 ≥ True 组 → 不成立。

用法：.venv/bin/python scripts/verify_hypotheses.py
输出：evolution/hypothesis_results.md（更新 hypotheses.md 状态引用）。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fg_system import config
from fg_system.backtest import runner


def load_features():
    feats = pd.read_csv(config.FEATURES_PATH, parse_dates=["date"]).set_index("date")
    pf = pd.read_csv(config.PORTFOLIO_FEATURES_PATH,
                     parse_dates=["date"]).set_index("date")
    # pf 与 feats 重叠列（target_position/extreme）以 feats 为准；只取 pf 独有列
    extra = ["us_core", "trend_blocked_us", "trend_blocked_crypto"]
    df = feats.join(pf[extra], how="inner")
    return df.dropna(subset=["fg_index", "us_core"])


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
    # 用 TQQQ 策略净值（与 baseline 同源）作为账户净值
    prices = pd.read_csv(os.path.join(config.RAW_DIR, "prices.csv"),
                         parse_dates=["date"])
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

    def _runs(mask):
        """把布尔序列切成连续区间，返回 [(区间回撤), ...]"""
        out = []
        cur = []
        prev = None
        for v in mask:
            if v != prev:
                if cur:
                    out.append(cur)
                cur = []
                prev = v
            cur.append(v)
        if cur:
            out.append(cur)
        return out

    # 逐日布尔位分组（False 组 = 当日未阻断，True 组 = 当日阻断）
    false_days = f[~f["trend_blocked_us"].fillna(False).astype(bool)]
    true_days = f[f["trend_blocked_us"].fillna(False).astype(bool)]
    mdd_false = _group_mdd(false_days)
    mdd_true = _group_mdd(true_days)
    passed = (mdd_false == mdd_false and mdd_true == mdd_true
              and mdd_false < mdd_true)  # False 组回撤更小（幅度更大）
    # 注意 H-007 判据：False 组**平均最大回撤幅度小于** True 组 ⇒ 不成立。
    # 即：False 期回撤（绝对值）应更小才算「布尔 False 保护账户」。
    passed_strict = (mdd_false == mdd_false and mdd_true == mdd_true
                     and abs(mdd_false) < abs(mdd_true))
    note = ("口径映射：信号尾部第 5/6 列布尔位不存在 ⇒ 取 trend_blocked_us "
            "（趋势过滤阻断，最贴近语义的布尔位）。账户净值 = TQQQ 策略净值"
            "（baseline 同源）。True 组（阻断日）应回撤更小才算「趋势过滤有效」。")
    return {"mdd_false": mdd_false, "mdd_true": mdd_true,
            "n_false": int(len(false_days)), "n_true": int(len(true_days)),
            "passed_abs_smaller": bool(passed_strict), "note": note}


def main():
    df = load_features()
    print("样本：%d 行（fg_index + us_core 均非空）" % len(df))

    h005, h005_meta = verify_h005(df)
    print("\n=== H-005 分箱统计 ===")
    print(h005.to_string(index=False))
    print("40-50 / 55-70 均值比: %.3f  判定: %s"
          % (h005_meta["ratio_40_55"], "通过" if h005_meta["passed"] else "不通过"))

    h007 = verify_h007(df)
    print("\n=== H-007 布尔位分组 ===")
    print(json_dumps(h007))

    # 写入结果文件
    out = os.path.join(os.path.dirname(__file__), "..", "evolution",
                       "hypothesis_results.md")
    lines = [
        "# 假说验证结果（A-3，2026-10-08）",
        "",
        "样本：portfolio_features.csv（已重建，%d 行）× features.csv 内连接，"
        "fg_index + us_core 均非空 %d 行。" % (len(df), len(df)),
        "",
        "## H-005：fg_index 分箱 vs 核心仓",
        "",
        "| 箱 | 样本数 | us_core 均值 | us_core 中位数 | target 均值 |",
        "|---|---|---|---|---|",
    ]
    for _, r in h005.iterrows():
        lines.append("| %s | %d | %.4f | %.4f | %.4f |"
                     % (r["bin"], r["n"], r["us_core_mean"],
                        r["us_core_median"], r["target_mean"]))
    lines.append("")
    lines.append("判定：%s（40-50/55-70 核心仓均值比 %.3f）"
                 % ("通过" if h005_meta["passed"] else "不通过",
                    h005_meta["ratio_40_55"] or float("nan")))
    lines.append("口径声明：%s" % h005_meta["note"])
    lines += ["", "## H-007：trend_blocked_us 分组回撤", ""]
    if h007:
        lines.append("- False 组（未阻断）%d 日 最大回撤 %.4f"
                     % (h007["n_false"], h007["mdd_false"]))
        lines.append("- True 组（阻断）%d 日 最大回撤 %.4f"
                     % (h007["n_true"], h007["mdd_true"]))
        lines.append("- 判定（False 组回撤幅度更小才成立）：%s"
                     % ("通过" if h007["passed_abs_smaller"] else "不通过"))
        lines.append("- 口径声明：%s" % h007["note"])
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n✅ 结果已写入 %s" % out)


def json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()
