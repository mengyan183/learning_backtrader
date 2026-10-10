#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""假说验证脚本：A-3 原两案（H-005 / H-007）+ WT-05 修订口径批量（H-024/025/027/029/032）。

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

输出：追加写 evolution/hypothesis_results.md（**不覆盖**已有内容）。
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
    pf 与 feats 重叠列（target_position/extreme）以 feats 为准；只取 pf 独有列。
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
    return df.dropna(subset=["fg_index", "us_core"])


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


# 假说注册表：id -> 元数据。selector 为 None 表示数据源无对应列（本机缺失）。
HYPOTHESES = {
    "H-024": {
        "desc": "fg_index≥70 的日期中 trend_blocked 触发率 ≥50% → 不成立",
        "selector": _mask_fg_ge_70,
        "pass_when": "low",
        "fields": "fg_index + trend_blocked_us/trend_blocked_crypto",
    },
    "H-025": {
        "desc": "zone=3.0 且 fg_index≥70 的日期中布尔位触发率 ≥50% → 不成立",
        "selector": _mask_zone3_and_fg70,
        "pass_when": "low",
        "fields": "zone + fg_index + trend_blocked_us/trend_blocked_crypto",
    },
    "H-027": {
        "desc": "AXTX 浮亏 ≤-20% 的日期中布尔位触发率 ≥50% → 不成立",
        "selector": None,   # 数据源无 AXTX 浮亏列
        "pass_when": "low",
        "fields": "AXTX 浮亏（数据源缺失）+ trend_blocked_us/trend_blocked_crypto",
        "missing_dep": "features.csv / portfolio_features.csv 无 AXTX 浮亏列",
    },
    "H-029": {
        "desc": "fg_index≥70 的日期中 trend_blocked 触发率 ≥50% → 成立",
        "selector": _mask_fg_ge_70,
        "pass_when": "high",
        "fields": "fg_index + trend_blocked_us/trend_blocked_crypto",
    },
    "H-032": {
        "desc": "zone=3.0 的日期中 trend_blocked 触发率 ≥50% → 不成立",
        "selector": _mask_zone3,
        "pass_when": "low",
        "fields": "zone + trend_blocked_us/trend_blocked_crypto",
    },
}

# 全部支持的假说（含 A-3 原案）——供 --help 与默认运行使用。
SUPPORTED = ["H-005", "H-007"] + list(HYPOTHESES.keys())


def verify_revised(df, hid):
    """跑一条修订口径假说，返回 (meta, text_block)。selector 为 None ⇒ 挂起。"""
    spec = HYPOTHESES[hid]
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
        description="假说验证：A-3 原案（H-005/H-007）+ WT-05 修订口径批量。\n"
                    "支持的假说：%s" % ", ".join(SUPPORTED),
        epilog="支持哪些假说：%s\n"
               "字段限定：zone / fg_index / trend_blocked_us / trend_blocked_crypto\n"
               "数据源：features.csv + portfolio_features.csv（走 fg_system.config 路径）"
               % ", ".join(SUPPORTED),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-H", "--hypothesis", action="append", default=None,
                   choices=SUPPORTED,
                   help="只跑指定假说（可重复）。默认全部：%s"
                        % ", ".join(SUPPORTED))
    p.add_argument("--dry-run", action="store_true",
                   help="只检查数据是否存在并打印，不写结果文件。"
                        "数据缺失时打印「数据缺失（路径）」并以退出码 2 结束。")
    p.add_argument("--out", default=None,
                   help="结果文件路径（默认 evolution/hypothesis_results.md）。")
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
        print("\n=== WT-05 修订口径（触发率 ≥50%）===")
        blocks += ["## WT-05 修订口径批量（触发率 ≥50%，2026-10-10）", ""]
        for hid in revised:
            meta, text = verify_revised(df, hid)
            print("[%s] %s" % (hid, meta.get("status")))
            blocks += text + [""]

    out = append_results(blocks, dry_run=False, out_path=args.out)
    print("\n✅ 结果已追加写入 %s" % out)
    return 0


def _dry_run(wanted):
    """只检查数据是否存在，不写文件。数据缺失时打印「数据缺失（路径）」。"""
    missing = []
    for path in (config.FEATURES_PATH, config.PORTFOLIO_FEATURES_PATH):
        if not os.path.exists(path):
            missing.append(path)
    if missing:
        for path in missing:
            print("数据缺失（路径）：%s" % path)
        print("[dry-run] 数据缺失，共 %d 个文件；未写任何文件。" % len(missing))
        return 2
    print("[dry-run] 数据齐备：")
    for path in (config.FEATURES_PATH, config.PORTFOLIO_FEATURES_PATH):
        print("  - %s" % path)
    print("[dry-run] 将验证的假说：%s" % ", ".join(wanted))
    print("[dry-run] 未写任何文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
