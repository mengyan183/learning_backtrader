# -*- coding: utf-8 -*-
"""对比多套因子权重下的**信号 + 组合回测**（第 12.47 / 12.52 / 12.53 条）。

为什么不用 `portfolio_backtest.py` 的历史报告做对比：
  那个脚本读 `Data/features.csv`（当前生产口径）⇒ 想比两套权重就得来回改生产
  数据 ✗ 而且历史报告的数据窗口不同 ⇒ **不可比** ✗
  （实测：旧基线 37.66% 是短窗口下的数，同窗口下只有 17.22% ✗）

本脚本的做法：
  · `pipeline.run(write=False)` 现算两套/三套 `fg_index` ⇒ **不写任何文件** ✓
  · 组合回测直接把 DataFrame 喂给 `build_portfolio()` ⇒ **同一份 prices、
    同一个 OOS 起点，只换权重** ✓（B0 两段必然相同，可作「同窗口」的自检）

指标：
  · 信号：`fg_index` 分布 / 五档占比 / `target` 均值 / 换手 / 与 SPY 20 日 IC
  · 回测：OOS 与 IS 的年化 / 最大回撤 / Sharpe / Calmar（含 B0 对照）

用法：
    python scripts/weight_compare.py                      # 默认 old vs new
    python scripts/weight_compare.py --compare old,mid,new
    python scripts/weight_compare.py --compare old,mid,new --backtest
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system import config, pipeline  # noqa: E402
from fg_system.factors.eval import evaluate  # noqa: E402

#: 候选权重档 ✓ —— 键名后的百分比是**波动率族（vix+term）占比** ✓
PRESETS = {
    # 40.5%：第 12.47 条之前的口径，2026-11-20 回退后的生产值
    "old": {"vix": 0.270, "term": 0.135, "price": 0.225,
            "breadth": 0.135, "fed": 0.135, "putcall": 0.100},
    # 35.0%：第 12.53 条中间档 —— 降一半，看能否保住 OOS 收益
    "mid": {"vix": 0.235, "term": 0.115, "price": 0.225,
            "breadth": 0.170, "fed": 0.135, "putcall": 0.120},
    # 30.0%：第 12.47 条（A/B 未通过：−5.41pp / Sharpe −0.21，已回退）
    "new": {"vix": 0.200, "term": 0.100, "price": 0.225,
            "breadth": 0.210, "fed": 0.135, "putcall": 0.130},
}

ZONE_EDGES = [0, 20, 40, 60, 80, 100]
ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


def _run_with(weights):
    """临时换权重跑一遍 pipeline ✓ —— 不写文件、跑完恢复原值。"""
    backup = dict(config.WEIGHTS)
    config.WEIGHTS.clear()
    config.WEIGHTS.update(weights)
    try:
        return pipeline.run(write=False)
    finally:
        config.WEIGHTS.clear()
        config.WEIGHTS.update(backup)


def _stats(name, out, spy):
    fg = out["fg_index"].dropna()
    tgt = out["target_position"].dropna()
    z = pd.cut(fg, bins=ZONE_EDGES, labels=ZONE_NAMES, include_lowest=True)
    shares = (z.value_counts(normalize=True).reindex(ZONE_NAMES) * 100)
    st = {
        "name": name,
        "n": int(len(fg)),
        "mean": round(float(fg.mean()), 2),
        "std": round(float(fg.std()), 2),
        "p10": round(float(fg.quantile(0.10)), 1),
        "p90": round(float(fg.quantile(0.90)), 1),
        "min": round(float(fg.min()), 1),
        "max": round(float(fg.max()), 1),
        "target_mean": round(float(tgt.mean()) * 100, 2),
        # 换手 = 目标仓位逐日变动绝对值之和（pp）⇒ 衡量调仓频率 ✓
        "turnover_pp": round(float(tgt.diff().abs().sum()) * 100, 1),
        "zones": {k: round(float(v), 1) for k, v in shares.items()},
    }
    if spy is not None:
        ev = evaluate(fg, spy, horizons=(20,), window=60)
        s = ev[20]["stats"]
        if s:
            st["ic"] = round(s["ic_mean"], 3)
            st["icir_adj"] = round(s["icir"], 2)
            st["icir_raw"] = round(s["icir_raw"], 2)
    return st


def _portfolio(feats, prices, oos_start):
    """用**同一份 prices + 同一个 OOS 起点**跑组合回测 ✓（不写任何文件）。

    ⚠️ 需要 `backtrader`（仅 Mac 有）⇒ 失败时返回 {"error": ...}，不中断统计 ✓
    """
    try:
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import portfolio_backtest as pb
    except Exception as exc:               # noqa: BLE001
        return {"error": "无法加载回测引擎：%s" % exc}
    try:
        return pb.build_portfolio(feats, prices, oos_start=oos_start)
    except Exception as exc:               # noqa: BLE001
        return {"error": "回测失败：%s" % exc}


def _oos_start():
    """OOS 起点：**从回测脚本取**，不在本脚本里另写一份 ✗（口径唯一来源）。"""
    try:
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import portfolio_backtest as pb
        return pb.OOS_START
    except Exception:                      # noqa: BLE001
        return "2024-10-04"


def _show_bt(name, bt):
    if "error" in bt:
        print("\n=== [%s] 组合回测 —— %s ===" % (name, bt["error"]))
        return
    m = bt["metrics"]
    p, b = m["portfolio"], m["buyhold"]
    print("\n=== [%s] 组合回测（OOS 自 %s）===" % (name, bt["oos_start"]))
    for tag, key in (("OOS", "oos"), ("IS", "is")):
        pm, bm = p[key], b[key]
        print("  %-4s 年化 %7.2f%% | 回撤 %7.2f%% | Sharpe %5.2f | Calmar %5.2f"
              " || B0 年化 %7.2f%%"
              % (tag, pm["annual_return"] * 100, pm["max_drawdown"] * 100,
                 pm["sharpe"], pm["calmar"], bm["annual_return"] * 100))


def main():
    ap = argparse.ArgumentParser(description="多套权重的信号 / 回测对比")
    ap.add_argument("--compare", default="old,new",
                    help="要比的档位，逗号分隔（可选 %s）" % ",".join(PRESETS))
    ap.add_argument("--backtest", action="store_true",
                    help="同时跑组合回测（需 backtrader，仅 Mac 可用）")
    args = ap.parse_args()

    keys = [k.strip() for k in args.compare.split(",") if k.strip()]
    bad = [k for k in keys if k not in PRESETS]
    if bad or not keys:
        print("⛔ 未知档位：%s（可选 %s）" % (bad, ",".join(PRESETS)))
        return 2

    for k in keys:
        w = PRESETS[k]
        print("%-5s vol族 %4.1f%%  合计 %.3f  %s"
              % (k, (w["vix"] + w["term"]) * 100, sum(w.values()), w))
    print("生产当前 config.WEIGHTS:", config.WEIGHTS)

    wide = pipeline.load_wide()
    spy = (wide[("SPY", "close")].astype(float)
           if ("SPY", "close") in wide.columns else None)
    if spy is None:
        print("⚠️ 取不到 SPY 收盘价 ⇒ 跳过 IC 计算")

    rows, outs = [], {}
    for k in keys:
        out = _run_with(PRESETS[k])
        outs[k] = out
        st = _stats(k, out, spy)
        rows.append(st)
        print("\n=== [%s] 信号 ===" % k)
        for f in ("n", "mean", "std", "p10", "p90", "min", "max",
                  "target_mean", "turnover_pp", "ic", "icir_adj", "icir_raw"):
            if f in st:
                print("  %-12s %s" % (f, st[f]))
        print("  五档占比     %s" % st["zones"])

    # 差异：全部以**第一档**为基准 ✓
    base, bname = rows[0], keys[0]
    for cur, cname in zip(rows[1:], keys[1:]):
        print("\n=== 差异（%s − %s）===" % (cname, bname))
        print("  fg_index 均值   %+.2f" % (cur["mean"] - base["mean"]))
        print("  fg_index 标准差 %+.2f" % (cur["std"] - base["std"]))
        print("  target 均值     %+.2f pp"
              % (cur["target_mean"] - base["target_mean"]))
        print("  换手            %+.1f pp（%.1f → %.1f）"
              % (cur["turnover_pp"] - base["turnover_pp"],
                 base["turnover_pp"], cur["turnover_pp"]))
        for z in ZONE_NAMES:
            d = cur["zones"][z] - base["zones"][z]
            print("  %-6s 占比    %+.1f pp（%.1f%% → %.1f%%）"
                  % (z, d, base["zones"][z], cur["zones"][z]))
        if "ic" in base and "ic" in cur:
            print("  IC              %+.3f（%.3f → %.3f）"
                  % (cur["ic"] - base["ic"], base["ic"], cur["ic"]))

    if not args.backtest:
        return 0

    print("\n" + "=" * 62)
    print("组合回测（**同一份 prices、同一个 OOS 起点**，只换权重）")
    print("=" * 62)
    prices = pd.read_csv(os.path.join(REPO, "Data", "raw", "prices.csv"),
                         parse_dates=["date"])
    oos = _oos_start()
    bts = {}
    for k in keys:
        bts[k] = _portfolio(outs[k], prices, oos)
        _show_bt(k, bts[k])

    ok = [k for k in keys if "error" not in bts[k]]
    if len(ok) >= 2:
        b0 = bts[ok[0]]
        print("\n=== 回测差异（以 %s 为基准，同为 OOS）===" % ok[0])
        # 自检：B0 必须一致，否则说明不是同一窗口 ✗
        b0_ann = {k: bts[k]["metrics"]["buyhold"]["oos"]["annual_return"]
                  for k in ok}
        same = len(set(round(v, 6) for v in b0_ann.values())) == 1
        print("  同窗口自检：B0 年化 %s ⇒ %s"
              % (["%.2f%%" % (v * 100) for v in b0_ann.values()],
                 "一致 ✓" if same else "**不一致，结果不可比** ✗"))
        for k in ok[1:]:
            a = b0["metrics"]["portfolio"]["oos"]
            b = bts[k]["metrics"]["portfolio"]["oos"]
            print("  [%s] 年化 %+7.2f pp（%.2f%% → %.2f%%）"
                  % (k, (b["annual_return"] - a["annual_return"]) * 100,
                     a["annual_return"] * 100, b["annual_return"] * 100))
            print("  [%s] 回撤 %+7.2f pp | Sharpe %+6.2f（%.2f → %.2f）"
                  % (k, (b["max_drawdown"] - a["max_drawdown"]) * 100,
                     b["sharpe"] - a["sharpe"], a["sharpe"], b["sharpe"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
