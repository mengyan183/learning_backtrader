#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新假说验证骨架（H-030 / H-031 / H-033）。

自我进化闭环「⑤变体验证」的执行器。本文件是**一个统一骨架**，
覆盖三条由人工登记的新假说。**不是一个假说一个脚本**，也不复制三份逻辑。

三条假说（`evolution/hypotheses.md`）与各自**检验方法**要求的输入：

  - H-030 市场级「量价-资金背离」先验
      需要：DeFi 链上资金（TVL）数据源（如 DeFiLlama TVL），构造 TVL 20 日变化。
      现状：**数据源未接入**（B 类待数据）⇒ 可用观察点 0。
  - H-031 个股级「利率敏感度」先验
      需要：`features.fed`（Fed 因子）与 CRCL 价格序列配对，比较 fed 方向变化前后收益。
      现状：`features.csv` **无 `fed` 列** ⇒ 可用观察点 0。
  - H-033 币股「经营现金流 vs Crypto Beta」分层先验
      需要：币股与 BTC 收益配对、按市场下跌期（BTC 20 日回撤 >10%）分组。
      现状：BTC 与币股价格在库，但**分组所需的样本量远未达阈值**（币股上市不足一年）⇒ 可用观察点不足。

三条都标注为「🟡 研究参考 / 待样本积累 / 数据源待接入」，
**当前一律不能出结论** ⇒ 骨架只做两件事：

  1. 载入各假说**检验方法所需的输入**，数可用观察点，与各自阈值比较；
  2. 样本不足即输出「等待样本积累（n/阈值）」并 **exit 0**。

状态机（与 `hypotheses.md` 首行一致）：

    open ──样本足够──▶ verifying ──判据成立──▶ adopted
      ▲                   │
      └───────样本不足─────┴──判据不成立──▶ falsified

  - `open`      ：刚登记，尚无任何观察处理；
  - `verifying` ：每个新观察点都在累积，但累计 < 阈值 ⇒ 等样本；
  - `adopted`   ：样本达阈值且**未发现反证**（不成立判据不触发）；
  - `falsified` ：样本达阈值且**触发任一不成立判据**（证伪即成果）。

口径纪律（与 `evolution-plan.md` §6 一致）：
  证伪即成果；数据不足不硬凑结论（宁可 verifying 等数据）。

数据路径纪律：
  一律取 `fg_system.config` 的常量，**禁止**硬编码绝对路径，
  **禁止**用绝对路径直接 `read_csv`。

用法：
  py -3.10 scripts/evolve_verify_new.py            # 正常检（样本不足即 exit 0）
  py -3.10 scripts/evolve_verify_new.py --dry-run  # 只看样本状态，不写回 hypotheses.md
  py -3.10 scripts/evolve_verify_new.py --help
"""
import argparse
import csv
import os
import sys

# §6.2 第 4 条：脚本自带 stdout utf-8，避免 Windows GBK 控制台崩或重定向乱码。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fg_system import config  # noqa: E402


# ---------------------------------------------------------------- 阈值（先验，禁止优化）
# 每条假说的**最小观察点数**。低于此值一律 verifying（等样本），不出结论。
MIN_OBS = {
    "H-030": 240,   # 市场级：需约一年交易日样本
    "H-031": 240,   # 个股级：CRCL 2025-06 上市，需累计满一年交易日
    "H-033": 240,   # 分层：币股自上市以来累计满一年交易日
}


def _count_dates(path, symbols=None, need_column=None):
    """数 path 中符合条件记录的**按日期去重**数。

    - `symbols=None`：不按标的过滤；
    - `need_column`：要求该列非空（如 fed 因子列）。
    文件缺失 / 无匹配 → 返回 (0, "-")，不抛异常。
    """
    if not os.path.exists(path):
        return 0, "-"
    seen = set()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if symbols is not None and row.get("symbol") not in symbols:
                continue
            if need_column is not None and not str(row.get(need_column) or "").strip():
                continue
            d = row.get("date")
            if d:
                seen.add(d)
    if not seen:
        return 0, "-"
    dates = sorted(seen)
    return len(dates), "%s → %s" % (dates[0], dates[-1])


def _count_deffi_tvl():
    """H-030：DeFi 链上资金（TVL）数据源。未接入 ⇒ 0。"""
    # 数据源未入库（B 类待数据）。一旦接入，应改为读 config 下的 TVL 序列文件。
    return 0, "-"


def _count_fed_direction_samples():
    """H-031：需 `features.fed` 因子与 CRCL 价格配对。features.csv 无 fed 列 ⇒ 0。"""
    path = config.FEATURES_PATH
    if not os.path.exists(path):
        return 0, "-"
    with open(path, newline="", encoding="utf-8") as f:
        cols = next(csv.reader(f), [])
    if "fed" not in cols:
        return 0, "-"
    # fed 列存在才按价格配对计数（当前不可能走到）。
    return _count_dates(
        os.path.join(config.RAW_DIR, "prices.csv"), symbols={"CRCL"})


def _count_crypto_beta_samples():
    """H-033：币股与 BTC 收益配对、且落在市场下跌期（BTC 20 日回撤 >10%）的样本数。

    这不只是「币股有多少天价格」——检验方法要求**按市场下跌期分组**，
    故可用观察点 = 同时满足①币股有价、②BTC 有价、③BTC 20 日回撤 >10% 的日期。
    BTC 序列来自 `crypto_underlying.csv`（config.RAW_DIR 下）。
    """
    symbol_days = _symbol_date_set(
        os.path.join(config.RAW_DIR, "prices.csv"), {"CRCL", "HOOD", "COIN", "CRCG"})
    btc_path = os.path.join(config.RAW_DIR, "crypto_underlying.csv")
    if not os.path.exists(btc_path) or not symbol_days:
        return 0, "-"
    btc = []  # [(date, close), ...] 按日期升序
    with open(btc_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                btc.append((row["date"], float(row["close"])))
            except (KeyError, TypeError, ValueError):
                continue
    btc.sort()
    # 20 日滚动回撤：drawdown = close / max(前 20 日 close) - 1。
    qualify = []
    for i, (d, close) in enumerate(btc):
        window = [c for _, c in btc[max(0, i - 20):i + 1]]
        peak = max(window) if window else close
        if peak and (close / peak - 1.0) < -0.10 and d in symbol_days:
            qualify.append(d)
    if not qualify:
        return 0, "-"
    return len(qualify), "%s → %s" % (qualify[0], qualify[-1])


def _symbol_date_set(path, symbols):
    """path 中给定标的的日期集合。"""
    if not os.path.exists(path):
        return set()
    seen = set()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("symbol") in symbols and row.get("date"):
                seen.add(row["date"])
    return seen


# 假说登记（一个骨架，统一驱动）：
#   id → (检验方法所需输入的计数函数, 说明)
HYPOTHESES = {
    "H-030": (_count_deffi_tvl, "DeFi 链上资金（TVL）序列"),
    "H-031": (_count_fed_direction_samples, "features.fed 因子 × CRCL 价格配对"),
    "H-033": (_count_crypto_beta_samples, "币股价格 × BTC 收益配对样本"),
}


def evaluate(hid):
    """单条假说的骨架判定：只决定「能不能出结论」，不做统计检验。

    返回 dict：id / status / enough / evidence / note。
    status 取值来自状态机 {verifying, adopted, falsified}；
    骨架阶段样本一律不足 ⇒ 一律 verifying。
    """
    count_fn, source = HYPOTHESES[hid]
    n, span = count_fn()
    need = MIN_OBS[hid]
    enough = n >= need
    if not enough:
        return {
            "id": hid, "status": "verifying", "enough": False,
            "evidence": "等待样本积累（%d/%d）" % (n, need),
            "note": "所需输入：%s；日期范围 %s" % (source, span),
        }
    # 样本足够才走统计检验。骨架阶段先明确「已够、待接判据」，不硬凑结论。
    return {
        "id": hid, "status": "verifying", "enough": True,
        "evidence": "样本已达阈值（%d/%d），待按不成立判据做统计检验" % (n, need),
        "note": "所需输入：%s；日期范围 %s" % (source, span),
    }


def run_all():
    return [evaluate(hid) for hid in ("H-030", "H-031", "H-033")]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="新假说验证骨架（H-030/H-031/H-033）：样本不足即等待，不硬凑结论。")
    ap.add_argument("--dry-run", action="store_true",
                    help="只输出样本状态，不写回 hypotheses.md")
    args = ap.parse_args(argv)

    results = run_all()
    for r in results:
        print("[%s] %s：%s" % (r["id"], r["status"], r["evidence"]))
        if r.get("note"):
            print("        %s" % r["note"])

    pending = [r for r in results if not r["enough"]]
    if pending:
        print("等待样本积累（n/阈值）：%s" % "，".join(
            "%s %s" % (r["id"], r["evidence"].split("（", 1)[1].rstrip("）"))
            for r in pending))

    if args.dry_run:
        print("[dry-run] 未写回 hypotheses.md")
        return 0

    # 骨架阶段样本一律不足 ⇒ 不写回状态（保持 open/verifying），直接 exit 0。
    # 写回逻辑在样本足够、判据可用后接入（见模块 docstring 状态机）。
    print("[hypotheses.md] 样本未达阈值，状态不变（等待积累）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
