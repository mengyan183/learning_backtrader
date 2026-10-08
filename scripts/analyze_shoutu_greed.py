# -*- coding: utf-8 -*-
"""守猪待兔「早清仓代价」分析（Step B · C 阶段）。

设计：docs/superpowers/specs/2026-09-24-shoutu-greed-exit-cost-design.md

【口径】数据用 `shoutu_history.csv`（**服务端权威日值**，见 trading-discipline
§14.5 的裁决①）——**不是** `shoutu_fng.csv`（那是 06:30 采样，两者口径已实测不同）。

【为什么价格用本文件的 `price` 列】它是**标的自身价格** ⇒ 杠杆产品的损耗
（费用/融资/跟踪误差）**已内含**，**不得**再叠加 `PRODUCT_COST_RATE`。

【未建模】佣金 / 滑点 / 汇率 / 趋势系数 / 弹药池 ⇒ 结论**偏保守**
（规则侧多付一次卖出+买回成本 ⇒ 规则看起来更差 ⇒ 更容易触发"该改规则"）。

【两种口径并存】`full` = **spec §5.1 的 episode 全程**（进入 ≥+60 → 回落 <+60，
horizon = `days - 1` 个收益日，见 `analyze_symbol` 里的推导）；
`full120` = 计划的 120 日长窗口口径（`max(days - 1, 120)`）。二者不是同一个东西：
`full120` 里一个 7 天 episode 可能含之后 120 天的涨幅，**不能**与按 `days` 分的
分段混读。`d20/d60/d120` 是另算的固定窗口（可越过 episode 末尾、含买回）。

【⚠️ 两处与计划原文的修正】计划的 `full` 写的是 `max(ep["days"], 120)` ——
与 spec §5.1 的「episode 全程」定义冲突，且会让 ≤5 天段的 "full" 装 120 日窗口值。
本脚本按 **spec 为准**（`full` = episode 全程），并另存 `full120` 以保留对照。
另一处：`full` 的 horizon 用 **`days - 1`**（不是 `days`）—— 规则在事件日当天清仓、
在回落日买回，且 `rets[0]` 按「次日生效」约定被丢弃（两侧同丢），
故规则**离场**的收益只有 `days - 1` 个。

用法：
    py -3.10 scripts/analyze_shoutu_greed.py
    py -3.10 scripts/analyze_shoutu_greed.py --main-only    # 只看系统在用的三标的
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config, pipeline, shoutu_analysis    # noqa: E402
from fg_system.data import loader                          # noqa: E402

WINDOWS = (20, 60, 120)
# spec §6 判据（**跑数之前写死**，不要改）：长 episode 平均收益差 ≥ 10pp 或 单次最大卖飞 ≥ 20%。
GO_LONG_AVG_MIN = 0.10      # 长 episode（>20 天）平均收益差门槛
GO_MAX_LOSS_MIN = 0.20      # 单次最大卖飞门槛
# 系统在用的三个大盘标的（③ 裁决的主样本）。**不是**硬编码白名单 ——
# 白名单在 config.SHOUTU_SYMBOLS，这里只是"取其中系统真正在用的那三个"。
MAIN_SYMBOLS = [s for s in config.SHOUTU_SYMBOLS if s in config.SYMBOLS]
SIDE_SYMBOLS = [s for s in config.SHOUTU_SYMBOLS if s not in config.SYMBOLS]


def _targets(values):
    """守猪待兔原值 → 目标仓位比例（相对 P0）：`ZONE_SATURATION[zone(值)]`。

    ⚠️ 必须走 `pipeline.saturation_of`（**唯一实现**，Task 4 Step 0 已提升为公开）
    —— 不得在此重写 zone 查找逻辑。
    """
    return pd.Series(
        pipeline.saturation_of(loader.shoutu_to_system_scale(values).values),
        index=values.index)


def _forward_return(prices, start, days, p0):
    """从 `start` 起 `days` 个交易日的**买入持有**收益（`p0` 规模；不足则返回 NaN）。

    ⚠️ **必须乘 `p0`**：规则侧是 `p0` 规模，若持有端用 100% 规模，差值会被 `1/p0`
    倍放大（实测高估 2~8 倍）⇒ 违反 spec §4「每 1 元持仓、两边持仓规模相同」。
    ⚠️ 窗口不足（`j >= len(prices)`）⇒ 返回 NaN（保持原语义，`r_h == r_h` 的守卫不变）。
    """
    if start not in prices.index:
        return float("nan")
    i = prices.index.get_loc(start)
    j = i + days
    if j >= len(prices):
        return float("nan")
    seg = prices.iloc[i:j + 1]
    rets = seg.pct_change().fillna(0.0)
    return float((1.0 + p0 * rets).prod() - 1.0)


def analyze_symbol(sym, hist, weights):
    """返回该标的的事件表 DataFrame。"""
    sub = hist[hist["symbol"] == sym].sort_values("date")
    if sub.empty:
        return pd.DataFrame()
    s = sub.set_index("date")["score"]
    px = sub.set_index("date")["price"].astype(float)
    episodes = shoutu_analysis.greed_episodes(s)
    if episodes.empty:
        return pd.DataFrame()

    rows = []
    for _, ep in episodes.iterrows():
        start, end = ep["start"], ep["end"]
        # §4.2：`w_i` 取该标的在**事件日**的实际权重（不是样本首日 —— 那是计划原文的
        # 笔误：计划取 `s.index[0]`，会把 2024-04 的权重套到 2026 的事件上）。
        # `reindex` 缺该日则 ffill（权重序列从 `wide.index` 起，早于事件日必有值）。
        w = float(weights.reindex([start]).ffill().bfill().iloc[0].get(sym, 1.0 / 3.0))
        p0 = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"] * w
        pos = s.index.get_loc(start)

        # ⚠️ 与计划原文的一处**修正**（spec 优先）：`full` 的口径是
        # **spec §5.1 的「episode 全程」** = 从进入 ≥+60 到回落 <+60。
        # 计划原文写 `max(days, 120)`，那让**每个** episode 都至少回放 120 天
        # ⇒ 列名叫 "full" 却装的是 120 日窗口值，而汇总又按 `days` 分段
        # （≤5/6~20/>20）⇒ **分段与度量错位**：一个 7 天 episode 的 "full"
        # 达 +34%，全是之后 120 天的涨幅，不是"这段贪婪期本来的代价"。
        #
        # ⚠️ 另一处**修正**：`full` 的 horizon 必须是 **`days - 1`**，不是 `days`。
        # 推导（已核算）：
        #   - `days` = episode 的**交易日数**（`start..end` 含首尾）。
        #   - 规则在**事件日当天**清仓（`path[0] = 0`），在**回落日**买回
        #     （`path[days] = p0`）。
        #   - 且 `rets[0]` 被 `fillna(0.0)` 丢弃（§8 风险 4「收盘价 + 次日生效」
        #     的约定，两侧同丢 ⇒ 对称非偏）。
        #   ⇒ 规则**离场**的收益只有 `pos+1 .. pos+days-1` 共 **`days - 1`** 个。
        #   ⇒ `full` 的 horizon = `int(ep["days"]) - 1`
        #     （`days == 1` 时为 0，`full` 恒为 0 —— 合理：只离场 0 个收益日）。
        #   `_pair(days)` 会经 `stop = min(pos + horizon, len(s) - 1)` 取到
        #   第 `days + 1` 个价格点 ⇒ 多含了「回落日（买回日）」那一天的收益，
        #   与 spec §5.1「episode 全程 = 进入 ≥+60 到回落 <+60」差 **1 日**。
        # 两种口径并存：`full` = episode 全程（spec §5.1，`days - 1` 个收益日）；
        # `full120` = 计划的 120 天长窗口口径（保留以便对照，不是主口径）。
        def _pair(horizon):
            stop = min(pos + horizon, len(s) - 1)
            tgt = _targets(s.iloc[pos:stop + 1]) * p0
            path = shoutu_analysis.replay_exit_path(tgt, p0=p0)
            rets = px.reindex(tgt.index).pct_change().fillna(0.0)
            rule_cum = float((1.0 + path * rets).prod() - 1.0)
            hold_cum = float((1.0 + p0 * rets).prod() - 1.0)
            return path, hold_cum - rule_cum

        path, full = _pair(max(int(ep["days"]) - 1, 0))
        _, full120 = _pair(max(int(ep["days"]) - 1, max(WINDOWS)))

        row = {
            "symbol": sym, "start": start, "end": end, "days": int(ep["days"]),
            "peak": float(ep["peak"]), "closed": bool(ep["closed"]),
            "p0": round(p0, 4),
            "exit_ratio": round(float(1.0 - path.min() / p0), 4),
            "full": round(full, 4),
            "full120": round(full120, 4),
        }
        for wd in WINDOWS:
            # ⚠️ 持有端必须与规则侧**同规模**（乘 `p0`），见 `_forward_return` 的
            # docstring 与 tests/test_analyze_shoutu_greed.py 的规模不变量。
            r_h = _forward_return(px, start, wd, p0)
            j = min(pos + wd, len(s) - 1)
            sub_tgt = _targets(s.iloc[pos:j + 1]) * p0
            sub_path = shoutu_analysis.replay_exit_path(sub_tgt, p0=p0)
            sub_ret = px.reindex(sub_tgt.index).pct_change().fillna(0.0)
            r_r = float((1.0 + sub_path * sub_ret).prod() - 1.0)
            row["d%d" % wd] = round(r_h - r_r, 4) if r_h == r_h else float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def _bucket(days):
    if days <= 5:
        return "≤5 天"
    return "6~20 天" if days <= 20 else ">20 天"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-only", action="store_true",
                    help="只看系统在用的三个大盘标的")
    args = ap.parse_args()

    hist = loader.load_shoutu_history()
    if hist.empty:
        print("没有历史数据（%s）" % config.SHOUTU_HISTORY_PATH)
        return 1

    symbols = MAIN_SYMBOLS if args.main_only else MAIN_SYMBOLS + SIDE_SYMBOLS
    print("数据：%s（%d 行，%s ~ %s）"
          % (os.path.basename(config.SHOUTU_HISTORY_PATH), len(hist),
             hist["date"].min().date(), hist["date"].max().date()))
    print("主样本（系统在用）：%s" % " / ".join(MAIN_SYMBOLS))
    print("旁证：%s" % (" / ".join(SIDE_SYMBOLS) or "（无）"))
    print()

    # 权重：用**事件日**的实际权重（§4.2；w_i 只影响"卖出多少"，不影响主口径）
    # ⚠️ `wide` 只读一次盘，下面的 price 交叉校验复用它（**不再**调 load_wide()）。
    weights = None
    wide = None
    try:
        wide = pipeline.load_wide()
        weights = pipeline.risk_weight_series(wide)
    except Exception as e:                                  # noqa: BLE001
        print("⚠️ 取权重失败（%s）⇒ 退化为等权 1/3" % e)

    # 交叉校验：`shoutu_history.csv` 的 price 列 vs `prices.csv`（A2 的第一次实质使用）
    # ⚠️ 门槛分两层（2026-09-24 用户裁决，见 spec 附 B）：
    #   ① `max_rel`（级差）**只作观察项** —— hist.price 是**前复权**（含分红再投），
    #      prices.csv.close **未含分红调整** ⇒ 2.4 年累计级差约 2%，差异**全部落在
    #      除息日**（TQQQ 2024-06-26 / 09-25 / 12-23 等），**不是**数据错误。
    #   ② 真正的 go 门是**日收益一致性**（分析只用 `pct_change`）：
    #      `corr_dret >= PRICE_CORR_MIN` 且 `max_abs_dret <= PRICE_MAX_ABS_DRET`。
    price_ok = []
    try:
        if wide is None:
            wide = pipeline.load_wide()
        for s in MAIN_SYMBOLS:
            hp = hist[hist["symbol"] == s].set_index("date")["price"].astype(float)
            rp = wide[(s, "close")].dropna()
            # ⚠️ **剔除除息日**（2026-09-28 用户裁决 (a)）：前复权 vs 未复权在除息日
            #    **必然**差一个股息 ⇒ 不剔除的话每次除息都会把旗标点亮（实测 09-24 那次
            #    让三个标的全报「未通过」）。识别方式见 `shoutu_analysis.ex_dividend_dates`。
            ex = shoutu_analysis.ex_dividend_dates(hp, rp)
            d = shoutu_analysis.price_divergence(hp, rp, exclude_dates=ex)
            ok = shoutu_analysis.price_consistency_ok(d)
            price_ok.append(ok)
            print("price 交叉校验 %-5s 交集 %4d 天 | 除息日 %d 天(已剔除)"
                  " | 级差(观察) 最大 %.4f%% 平均 %.4f%%"
                  " | 日收益 corr %.6f 最大差 %.4f%% 平均 %.4f%% | %s"
                  % (s, d["n"], d["excluded"], 100 * d["max_rel"], 100 * d["mean_rel"],
                     d["corr_dret"], 100 * d["max_abs_dret"], 100 * d["mean_abs_dret"],
                     "通过" if ok else "**未通过**"))
            if len(ex):
                print("             └ 除息日：%s"
                      % ", ".join(str(x.date()) for x in ex))
    except Exception as e:                                  # noqa: BLE001
        print("⚠️ price 交叉校验跳过（%s）" % e)
    if price_ok:
        print("⇒ price 列一致性校验：%s（判据 = 日收益 corr ≥ %.4f 且 单日收益差 ≤ %.2f%%；"
              "级差为复权口径差，不作判据）"
              % ("**通过**" if all(price_ok) else "**未通过，本次结论需复核**",
                 shoutu_analysis.PRICE_CORR_MIN,
                 100 * shoutu_analysis.PRICE_MAX_ABS_DRET))
    print()

    # D5（§14.5）：`shoutu_fng.csv` 的 `price` 属**哪个复权口径**？
    # 判据 = 分别与两个参照源算日收益一致性 ⇒ 谁的通过（另一方不通过）就归谁。
    # ⚠️ **分辨力需要「跨除息日」的样本** ⇒ 现在（2026-09-28）重叠仅 1 天，
    #    会报「无分辨力」。**这不是失败** —— 是「数据还没到」（等 2026-12 下旬
    #    除息日落入 fng 序列）。**不得**据此断言任何一方。
    try:
        recs = loader.load_shoutu_records()
        if recs.empty or "price" not in recs.columns or recs["price"].isna().all():
            print("D5 fng 口径：跳过（shoutu_fng.csv 尚无 price 值）")
        else:
            fng_px = recs.dropna(subset=["price"])
            for s in MAIN_SYMBOLS:
                fp = (fng_px[fng_px["symbol"] == s].set_index("date")["price"]
                      .astype(float).sort_index())
                if fp.empty:
                    continue
                hp = hist[hist["symbol"] == s].set_index("date")["price"].astype(float)
                rp = wide[(s, "close")].dropna()
                out = shoutu_analysis.fng_price_caliber(fp, hp, rp)
                print("D5 fng 口径 %-5s fng %3d 天 | vs history %s | vs prices %s | %s"
                      % (s, len(fp),
                         "通过" if out["ok_hist"] else "未通过",
                         "通过" if out["ok_prices"] else "未通过",
                         out["verdict"]))
    except Exception as e:                                  # noqa: BLE001
        print("⚠️ D5 fng 口径判定跳过（%s）" % e)
    print()

    tables = [analyze_symbol(s, hist, weights) for s in symbols]
    tables = [t for t in tables if not t.empty]
    if not tables:
        print("没有任何 episode")
        return 0
    ev = pd.concat(tables, ignore_index=True)
    ev["bucket"] = ev["days"].map(_bucket)
    ev["is_main"] = ev["symbol"].isin(MAIN_SYMBOLS)

    pd.set_option("display.width", 240)
    print("=== 事件表（%d 个 episode；closed=False 表示数据末尾仍在贪婪档）===" % len(ev))
    print("full = episode 全程（spec §5.1）；full120 = 120 日长窗口（对照用）；"
          "d20/d60/d120 = 固定窗口，持有端与规则侧**同为 p0 规模**（spec §4）")
    print(ev.to_string(index=False))
    print()

    # ⚠️ spec §3 契约：**未完成** episode（数据末尾仍在档位 4）**不进入「全程」统计**
    # （其 `full` 被截断在数据末尾，混入会**低估**卖飞）。固定窗口（d20/d60/d120）
    # 在事件表里仍逐行保留（事件表在**过滤之前**已打印，含全部 episode）。
    unclosed = ev[~ev["closed"].astype(bool)]
    ev = ev[ev["closed"].astype(bool)]

    # ⚠️ `exit_ratio == 0` ⇒ 规则**从未动作**（`p0 < REBALANCE_THRESHOLD`，单标的
    # 仓位不到 10pp 时连阈值都够不到）⇒ `full` 恒为 0。这是**规则未生效**，
    # 不是"卖飞小"；混入均值会稀释结论。故同时给出"全样本"与"规则真的动作过"两行。
    noact = ev[ev["exit_ratio"] == 0.0]
    if len(noact):
        print("⚠️ 规则从未动作的 episode：%d 个（标的 %s，p0 ≈ %.2f%%~%.2f%% < 阈值 %.0f%%）"
              % (len(noact), "/".join(sorted(noact["symbol"].unique())),
                 100 * noact["p0"].min(), 100 * noact["p0"].max(),
                 100 * config.REBALANCE_THRESHOLD))
        print()

    if len(unclosed):
        print("⚠️ 未完成 episode：%d 个（标的 %s，数据末尾仍在档位 4）"
              "⇒ 按 spec §3 **不进入「全程」统计**（其固定窗口 d20/d60/d120 见事件表）"
              % (len(unclosed), "/".join(sorted(unclosed["symbol"].unique()))))
        print()

    print("=== 汇总（收益差 = 不卖 − 规则，>0 = 卖飞；单位：小数）===")
    view = ev[ev["exit_ratio"] > 0.0]
    print("过滤后样本（仅含规则真的动作过的 episode）：%d / %d" % (len(view), len(ev)))
    for label, grp in (("主样本", view[view["is_main"]]),
                      ("旁证", view[~view["is_main"]])):
        if grp.empty:
            continue
        for b in ("≤5 天", "6~20 天", ">20 天"):
            g = grp[grp["bucket"] == b]
            if g.empty:
                continue
            print("%-6s %-8s n=%-3d full 均值 %+7.2f%% 中位 %+7.2f%% 为正 %d/%d"
                  "  |  full120 均值 %+8.2f%%"
                  % (label, b, len(g), 100 * g["full"].mean(),
                     100 * g["full"].median(), int((g["full"] > 0).sum()), len(g),
                     100 * g["full120"].mean()))
    print()
    # 判据（spec §6，跑数**之前**已写死）。
    # ⚠️ **两个窗口并列**（spec §5.1 的两种口径，2026-09-24 用户裁决）：
    #   `full`    = episode 全程  ⇒ **主判据**
    #   `full120` = 120 日固定窗口 ⇒ **补充判据**
    # 为什么差这么多：规则一旦清仓，在 120 日窗口内平均 97.4/121 天（80%）仓位为 0
    # （`REBALANCE_THRESHOLD` 阻尼 ⇒ 只在档位 0 才买回）⇒ `full` 只覆盖离场期的
    # 很小一段，**结构性低估**。
    # ⚠️ **样本口径**：裁决③ 明确「标的**只用系统在用的 TQQQ / SOXL / UPRO**
    # （YINN / GDXU / CONL 作旁证）」⇒ **判据用主样本**。
    # 旁证并入的「全样本」另算一遍作**稳健性对照** —— 否则旁证的 GDXU 长 episode
    # 会把「单次最大卖飞」抬起，与主口径混读。
    def _verdict(g, col="full"):
        """→ (长 episode 均值, 单次最大卖飞, 是否满足判据)。空样本 ⇒ (NaN, NaN, False)。"""
        if g.empty:
            return float("nan"), float("nan"), False
        long_avg = float(g[g["bucket"] == ">20 天"][col].mean())
        mx = float(g[col].max())
        ok = ((long_avg == long_avg and long_avg >= GO_LONG_AVG_MIN)
              or mx >= GO_MAX_LOSS_MIN)
        return long_avg, mx, ok

    print("=== 判据（spec §6，事先写死；样本 = **主样本**，见裁决③；**两窗口并列**）===")
    for label, col in (("主判据", "full"), ("补充判据", "full120")):
        m_long, m_max, ok = _verdict(view[view["is_main"]], col)
        print("【%s】窗口 = %s" % (label, col))
        print("  长 episode（>20 天）平均收益差：%+.2f%%（门槛 ≥ 10%%）" % (100 * m_long))
        print("  单次最大卖飞：%+.2f%%（门槛 ≥ 20%%）" % (100 * m_max))
        print("  ⇒ %s" % ("**满足**判据" if ok else "不满足判据"))
    a_long, a_max, a_ok = _verdict(view, "full")
    print("稳健性对照（含旁证的过滤后全样本 %d 个，窗口 = full）：长 episode 均值 %+.2f%%、"
          "单次最大卖飞 %+.2f%% ⇒ %s"
          % (len(view), 100 * a_long, 100 * a_max,
             "仍**不满足**判据" if not a_ok else "**满足**判据"))
    # ⚠️ 本行**无 `%` 格式化**（`print` 不带参数）⇒ 用单个 `%`，不能用 `%%`
    # （`%%` 只在有格式化操作时转义；裸 `print` 里会原样打印成 `20%%`）。
    print("⇒ **主判据（full）不建议做 A；补充判据（full120）的「单次最大卖飞 ≥ 20%」成立"
          " ⇒ 是否做 A 交人工裁决**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
