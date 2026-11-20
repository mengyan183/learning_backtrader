# -*- coding: utf-8 -*-
"""第 12.59 条 A/B：调仓冷却用「自然日」还是「交易日」。

为什么**不是**组合回测
    `throttle_ok()` 只被 `pipeline.instruction_card()`（指令卡）与
    `scripts/invest_research.py::_instruction_line()`（简报）调用 ⇒ 它
    **不影响** `target_position`，也不进回测 ✗
    影响面在「实际执行」：同一条信号，冷却口径不同 ⇒ 能不能动手不同 ✓

所以本脚本做**执行层模拟**：逐日拿 `target_position`，用**真实的**
`portfolio.throttle_ok` + `clip_adjustment` 决定是否动手，比较两种冷却口径下的
操作次数 / 被挡次数 / 换手 / 持仓偏离 / 近似净值。

近似口径（必须知道）
    · `target_position` 已是 shift(1) 的可执行目标 ✓
    · 净值用「持仓比例 × 标的篮子日收益」累乘，**不含**佣金/滑点/融资成本 ✗
    · 只用 `us_equity` 的 target（加密侧在 `portfolio_features` 另算）✗

用法
    python scripts/cooldown_compare.py
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from fg_system import pipeline  # noqa: E402
from fg_system.signal import portfolio as sig  # noqa: E402

#: 生产实现，**在打补丁之前**绑定 ⇒ 避免 `_gap_trading` 递归调用自己 ✗
_ORIG_GAP = sig.cooldown_gap


def _gap_calendar(last, date):
    """旧口径：自然日（第 12.59 条之前的实现）。"""
    return (pd.Timestamp(date) - pd.Timestamp(last)).days


def _gap_trading(last, date):
    """新口径：交易日（用生产实现，避免两处逻辑漂移）。"""
    return _ORIG_GAP(last, date)


def _simulate(target, gap_fn):
    """按真实 `throttle_ok` + `clip_adjustment` 跑一遍执行模拟。

    :param target: `Series[date -> target_position]`（可含 NaN，NaN 视为「无信号」）
    :param gap_fn: 冷却间隔函数 `(last, date) -> 天数`
    :returns: dict（pos / ops / blocked_cooldown / blocked_threshold / blocked_dates）
    """
    orig = sig.cooldown_gap
    sig.cooldown_gap = gap_fn
    try:
        state = sig.PortfolioState()
        pos = 0.0
        ops = blocked_cd = blocked_th = 0
        blocked_dates = []
        out = []
        for dt, tgt in target.items():
            if pd.isna(tgt):
                out.append(pos)
                continue
            d = dt.strftime("%Y-%m-%d")
            ok, reason = sig.throttle_ok(state, pos, float(tgt), d, extreme=False)
            if ok:
                pos = sig.clip_adjustment(pos, float(tgt))
                state.last_rebalance_date = d
                ops += 1
            else:
                if "冷却" in reason:
                    blocked_cd += 1
                    blocked_dates.append(d)
                elif "阈值" in reason:
                    blocked_th += 1
            out.append(pos)
        return {"pos": pd.Series(out, index=target.index), "ops": ops,
                "blocked_cooldown": blocked_cd, "blocked_threshold": blocked_th,
                "blocked_dates": blocked_dates}
    finally:
        sig.cooldown_gap = orig


def _equity(pos, ret):
    """近似净值：持仓比例 × 篮子日收益（不含成本）。"""
    nav = (1.0 + pos * ret).cumprod()
    n = max(1, len(nav))
    ann = float(nav.iloc[-1]) ** (252.0 / n) - 1.0
    dd = float((nav / nav.cummax() - 1.0).min())
    return ann, dd


def _summary(name, sim, target, ret):
    pos = sim["pos"]
    ann, dd = _equity(pos, ret)
    dev = (pos - target.ffill().fillna(0.0)).abs()
    return {
        "name": name,
        "ops": sim["ops"],
        "blocked_cooldown": sim["blocked_cooldown"],
        "blocked_threshold": sim["blocked_threshold"],
        "turnover_pp": round(float(pos.diff().abs().sum()) * 100, 1),
        "pos_mean": round(float(pos.mean()) * 100, 2),
        "dev_mean": round(float(dev.mean()) * 100, 2),
        "annual": round(ann * 100, 2),
        "max_dd": round(dd * 100, 2),
    }


def _show(st):
    print("\n=== [%s] 执行模拟 ===" % st["name"])
    print("  可操作次数        %d" % st["ops"])
    print("  被冷却挡住        %d" % st["blocked_cooldown"])
    print("  被阈值挡住        %d" % st["blocked_threshold"])
    print("  换手              %.1f pp" % st["turnover_pp"])
    print("  平均持仓          %.2f%%" % st["pos_mean"])
    print("  持仓与目标偏离    %.2f pp（均值）" % st["dev_mean"])
    print("  近似年化/回撤     %.2f%% / %.2f%%（不含成本）" % (st["annual"], st["max_dd"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="调仓冷却口径 A/B（第 12.59 条）")
    ap.parse_args(argv)

    out = pipeline.run(write=False)
    target = out["target_position"]
    if target.dropna().empty:
        print("⛔ target_position 全为空 ⇒ 先跑 pipeline")
        return 2

    wide = pipeline.load_wide()
    weights = pipeline.risk_weight_series(wide)
    ret = pipeline.weighted_basket_returns(wide, weights).reindex(target.index).fillna(0.0)

    old_sim = _simulate(target, _gap_calendar)
    new_sim = _simulate(target, _gap_trading)
    old = _summary("old（自然日）", old_sim, target, ret)
    new = _summary("new（交易日）", new_sim, target, ret)
    _show(old)
    _show(new)

    print("\n=== 差异（new − old）===")
    print("  可操作次数        %+d（%d → %d）"
          % (new["ops"] - old["ops"], old["ops"], new["ops"]))
    print("  被冷却挡住        %+d（%d → %d）"
          % (new["blocked_cooldown"] - old["blocked_cooldown"],
             old["blocked_cooldown"], new["blocked_cooldown"]))
    print("  换手              %+.1f pp（%.1f → %.1f）"
          % (new["turnover_pp"] - old["turnover_pp"],
             old["turnover_pp"], new["turnover_pp"]))
    print("  平均持仓          %+.2f pp（%.2f%% → %.2f%%）"
          % (new["pos_mean"] - old["pos_mean"], old["pos_mean"], new["pos_mean"]))
    print("  持仓与目标偏离    %+.2f pp（%.2f → %.2f）"
          % (new["dev_mean"] - old["dev_mean"], old["dev_mean"], new["dev_mean"]))
    print("  近似年化          %+.2f pp（%.2f%% → %.2f%%）"
          % (new["annual"] - old["annual"], old["annual"], new["annual"]))
    print("  近似回撤          %+.2f pp（%.2f%% → %.2f%%）"
          % (new["max_dd"] - old["max_dd"], old["max_dd"], new["max_dd"]))

    extra = sorted(set(new_sim["blocked_dates"]) - set(old_sim["blocked_dates"]))
    print("\n新规则**额外**挡住的日期：%d 个" % len(extra))
    if extra:
        print("  前 10 个：%s" % ", ".join(extra[:10]))

    print("\n⚠️ 本结果是**执行层近似**（不含成本、只用 us_equity 目标）"
          "⇒ 用于判断规则影响面，不作为收益预测 ✗")
    return 0


if __name__ == "__main__":
    sys.exit(main())
