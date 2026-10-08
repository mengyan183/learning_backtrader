# -*- coding: utf-8 -*-
"""守猪待兔「清仓线」全系统回放（A1）+ keyed extremes 维度（A2-E）。

设计：docs/superpowers/specs/2026-09-24-shoutu-variants-replay-design.md
      docs/superpowers/specs/2026-09-28-keyed-extremes-magnitude-design.md

【结论纪律】第 13.1 / 13.2 / 13.0 条 ⇒ 本脚本只出**机制性证据 + 量级判断**：
**不排名、不挑「最优清仓线」**；**回测不作为改规则的依据**。

【组合集（A2-E）】8 组合 = `VARIANT_KEYS` × `(keyed=False, keyed=True)`。
  - `keyed=False`：熔断 / 极恐加仓仍以**市场指数**为触发源（变体只换五档 core 的来源）。
  - `keyed=True`：熔断 / 极恐的**触发源**改用守猪待兔口径的市场级指数
    （`pipeline.shoutu_market_index`，即 A2 的 `shoutu_keyed_extremes`）。
  ⚠️ keyed 在守猪待兔覆盖区间**之前**逐位等价 `fg_index` ⇒ 历史区间 keyed 与
  非 keyed 曲线**逐位相同**（红线：`tests/test_shoutu_variants.py`）。

【两条口径（必须明示）】
  1. 只有 `keyed=True` 的组合才换极端规则的触发源；`keyed=False` 仍以市场指数为触发源。
  2. 「高情绪区间」= `fg_index >= 80` 的交易日（**与组合无关** ⇒ 八条曲线同一批日子）。

【未建模】汇率 / 税 / 申购赎回 / 借券成本；`RANK_WINDOW=756` 未满 ⇒ 实际走 `fixed` 口径。

用法：
    py -3.10 scripts/analyze_shoutu_variants.py
"""
import os
import sys

import pandas as pd

# 输出统一 UTF-8。**为什么必须**：定时任务 / CI / `>` 重定向会把 stdout 写进文件，
# 而 Windows 默认 cp936 ⇒ `⚠️` / `⇒` / `—` 全部变成 `??`，日志事后不可读
# （实测：本脚本重定向后 4 个变体的口径提醒行全部乱码）。
# 同 `scripts/fetch_market_data.py` 的做法；`hasattr` 守卫兼容被包装过的 stdout。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config, pipeline, shoutu_variants   # noqa: E402
from fg_system import shoutu_analysis                     # noqa: E402
from fg_system.backtest import runner                     # noqa: E402
from fg_system.data import loader                         # noqa: E402

EFFECT_START = "2024-04-23"      # 守猪待兔历史起点 ⇒ 「纯效应段」起点（spec §6）
HIGH_MOOD_INDEX = 80.0           # 「高情绪」= 系统口径的极度贪婪档（spec §4.1）
SHOUTU_GREED_LINE = config.SHOUTU_GREED_LINE   # 守猪待兔贪婪线（+60），用于对照列
# A2-E：极端规则的触发阈值（与 market_signal 判定同语义，供「触发频率」表用）。
GREED_TRIGGER = config.EXTREME_GREED_TRIGGER   # 熔断（>= 该值）
FEAR_TRIGGER = config.EXTREME_FEAR_TRIGGER     # 极恐（<= 该值）

# A2-E：keyed 维度（熔断 / 极恐的触发源是否改用守猪待兔口径）。
KEYED_FLAGS = (False, True)
# 组合集 = 4 变体 × 2 keyed（8 个），顺序固定：先 `keyed=False` 全变体，再 `keyed=True`。
COMBO_KEYS = tuple((v, k) for v in shoutu_variants.VARIANT_KEYS for k in KEYED_FLAGS)


def _combo_id(variant, keyed):
    """组合的稳定短 id（供结果字典键 / 表列）。`keyed=False` 时就是变体键本身。"""
    return variant if not keyed else "%s+keyed" % variant


def _label(variant, keyed):
    tag = "（守猪待兔触发源）" if keyed else "（市场指数触发源）"
    if variant == shoutu_variants.BASELINE:
        return "基准（市场指数 core）%s" % tag
    return shoutu_variants.VARIANTS[variant]["label"] + tag


def run_combo(variant, keyed, us_v2, crypto, weights, hist, shoutu_wide, basket):
    """跑一个 `(variant, keyed)` 组合，返回 `{"strat", "returns", "base", "pf", ...}`。

    - `us_core`：`None`（= 五档基准）或变体口径的 core 序列（A1 注入点）。
    - `us_trigger_index`：`None`（= 市场指数触发源）或守猪待兔口径的市场级指数
      （A2 注入点，`pipeline.shoutu_market_index`）。
    """
    core = (None if variant == shoutu_variants.BASELINE
            else shoutu_variants.variant_core_series(us_v2, weights, hist, variant))
    trig = (None if not keyed
            else pipeline.shoutu_market_index(us_v2, weights, shoutu_wide))
    pf = pipeline.run_portfolio(us_v2, crypto, write=False, us_core=core,
                                us_trigger_index=trig)
    # 与 `cli backtest-v2` 完全同口径（cli.py:395-396）
    base = (pf["us_core"].fillna(0.0) + pf["ammo_us"]).clip(upper=1.0).shift(1)
    f = us_v2.copy()
    f["target_position"] = base
    f["fg_index"] = us_v2["fg_index"]
    f["zone"] = us_v2["zone"]
    for col in ("open", "high", "low", "close"):
        f[col] = basket
    f["volume"] = 0.0
    strat, returns = runner.run_single(f, "BASKET")
    # 不含成本版：同一份 features 再跑一次，临时把佣金 / 滑点置零（`build_cerebro`
    # 在调用时读 `config.COMMISSION` / `config.SLIPPAGE` ⇒ 保存-置零-恢复即可，
    # **不重写** 任何回测逻辑）。用于隔离「换手上升带来的成本后果」（spec §7 风险 2）。
    cost_c, cost_s = config.COMMISSION, config.SLIPPAGE
    try:
        config.COMMISSION, config.SLIPPAGE = 0.0, 0.0
        _, returns_nocost = runner.run_single(f, "BASKET")
    finally:
        config.COMMISSION, config.SLIPPAGE = cost_c, cost_s
    return {"strat": strat, "returns": returns, "returns_nocost": returns_nocost,
            "base": base, "pf": pf,
            "variant": variant, "keyed": keyed,
            "combo": _combo_id(variant, keyed), "label": _label(variant, keyed)}


def metrics_frame(results, start=None):
    """组合级指标表（复用 `runner.performance_metrics`）。"""
    rows = []
    for r in results.values():
        rets = r["returns"] if start is None else r["returns"].loc[start:]
        m = runner.performance_metrics(rets)
        rows.append({
            "组合": r["combo"], "说明": r["label"],
            "keyed": r["keyed"], "有效天": int(rets.dropna().shape[0]),
            "总收益%": 100 * m["total_return"], "年化%": 100 * m["annual_return"],
            "最大回撤%": 100 * m["max_drawdown"], "年化波动%": 100 * m["annual_vol"],
            "Sharpe": m["sharpe"], "Calmar": m["calmar"],
        })
    return pd.DataFrame(rows)


def flat_stats(core):
    """连续「core == 0」的统计：天数占比 / 平均长度 / 最长长度。"""
    valid = core.notna()
    zero = (core == 0.0) & valid
    n_valid = int(valid.sum())
    runs, cur = [], 0
    for flag in zero.tolist():
        if flag:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return {
        "zero_days": int(zero.sum()),
        "zero_share": (float(zero.sum()) / n_valid) if n_valid else float("nan"),
        "avg_flat_run": (sum(runs) / len(runs)) if runs else 0.0,
        "max_flat_run": max(runs) if runs else 0,
    }


def high_mood_masks(us_v2, shoutu_wide):
    """`(H, Hs, overlap)`：高情绪（fg_index>=80）、守猪待兔高情绪（任一主标的 >=+60）。

    `shoutu_wide`：守猪待兔**宽表**（`shoutu_variants.shoutu_wide_from_long(hist)`），
    与 `run_combo` 的 `us_trigger_index` **共用同一份** ⇒ 只构造一次。
    """
    H = (us_v2["fg_index"] >= HIGH_MOOD_INDEX).reindex(us_v2.index).fillna(False)
    Hs = (shoutu_wide >= SHOUTU_GREED_LINE).any(axis=1).reindex(us_v2.index).fillna(False)
    return H, Hs, int((H & Hs).sum())


def reentry_lag(core, high_flag):
    """「高情绪段结束」到「core > 0」的**中位天数**（spec §7.3）。

    `high_flag`：布尔 Series（`守猪待兔 >= +60` 的任一主标的，即 `Hs`）。
    对每个 `high_flag == True` 的**连续段**，找段结束后**首个** `core > 0` 的日子，
    记 `lag = 该日 - 段末日`；返回 `(中位数, 用到的段数)`。找不到则跳过该段。
    V3（从不清仓）预期 `median = 0`。
    """
    flags = pd.Series(high_flag).fillna(False).astype(bool)
    pos = pd.Series(core).reindex(flags.index)
    lags = []
    run_end = None
    vals = flags.to_numpy()
    for i in range(len(vals)):
        if vals[i]:
            run_end = i
        elif run_end is not None:
            after = pos.iloc[run_end + 1:]
            nz = after[after > 0.0]
            if len(nz):
                lags.append(int(after.index.get_loc(nz.index[0])))
            run_end = None
    if not lags:
        return float("nan"), 0
    return float(pd.Series(lags).median()), len(lags)


def main_table(results, H, base_rets, windows=((None, "全历史"), (EFFECT_START, "纯效应段"))):
    """① 组合级主表：8 组合 × 双窗口：年化 / 最大回撤 / Calmar / 高情绪区间相对收益差。

    高情绪差沿用 A1 口径：`Σ_{t ∈ H} (r_combo,t − r_B0,t)`（pp，每 1 元组合）。
    """
    rows = []
    for start, wname in windows:
        # ⚠️ 高情绪差必须**与窗口对齐**：纯效应段行只在 `H ∩ [start, …)` 上求和，
        # 否则该列会在两个窗口显示同一个（全期）值，误导读者（与表 2 / 表 2c 对齐）。
        h_win = H if start is None else (H & (H.index >= pd.Timestamp(start)))
        for r in results.values():
            rets = r["returns"] if start is None else r["returns"].loc[start:]
            m = runner.performance_metrics(rets)
            r_all = r["returns"].reindex(base_rets.index)
            h = h_win.reindex(r_all.index).fillna(False)
            diff = (r_all[h] - base_rets[h]).sum()
            rows.append({
                "组合": r["combo"], "窗口": wname,
                "年化%": 100 * m["annual_return"],
                "最大回撤%": 100 * m["max_drawdown"],
                "Calmar": m["calmar"],
                "高情绪Σ差(pp)": 100 * diff,
            })
    return pd.DataFrame(rows)


def increment_table(results):
    """② 增量表：`keyed=True` 相对 `keyed=False` 的年化差 / Calmar 差（逐变体 × 逐窗口）。"""
    rows = []
    for v in shoutu_variants.VARIANT_KEYS:
        off = results[_combo_id(v, False)]
        on = results[_combo_id(v, True)]
        for start, wname in ((None, "全历史"), (EFFECT_START, "纯效应段")):
            ro = off["returns"] if start is None else off["returns"].loc[start:]
            rn = on["returns"] if start is None else on["returns"].loc[start:]
            mo, mn = runner.performance_metrics(ro), runner.performance_metrics(rn)
            rows.append({
                "变体": v, "窗口": wname,
                "年化(非keyed)%": 100 * mo["annual_return"],
                "年化(keyed)%": 100 * mn["annual_return"],
                "Δ年化(pp)": 100 * (mn["annual_return"] - mo["annual_return"]),
                "Calmar(非keyed)": mo["calmar"], "Calmar(keyed)": mn["calmar"],
                "ΔCalmar": mn["calmar"] - mo["calmar"],
            })
    return pd.DataFrame(rows)


def trigger_turnover_table(results, us_v2, keyed_trigger):
    """③ 触发频率 / 换手表。

    - 触发频率：keyed 口径（`keyed_trigger`）vs 市场指数口径（`us_v2["fg_index"]`）
      的熔断 / 极恐**天数**，**按窗口分别统计**。
    - 换手：各组合的 `strat.order_count`（`extreme` 豁免防抖动的后果），
      keyed vs 非 keyed 逐变体对照。
    - 含成本 / 不含成本**两版年化**（纯效应段）。
    """
    market = us_v2["fg_index"]
    rows = []
    for start, wname in ((None, "全历史"), (EFFECT_START, "纯效应段")):
        k = keyed_trigger if start is None else keyed_trigger.loc[start:]
        mk = market if start is None else market.loc[start:]
        kc = shoutu_analysis.extreme_trigger_counts(k, GREED_TRIGGER, FEAR_TRIGGER)
        mc = shoutu_analysis.extreme_trigger_counts(mk, GREED_TRIGGER, FEAR_TRIGGER)
        rows.append({
            "窗口": wname, "口径": "keyed（守猪待兔触发源）",
            "熔断天数": kc["greed_days"], "极恐天数": kc["fear_days"]})
        rows.append({
            "窗口": wname, "口径": "市场指数触发源",
            "熔断天数": mc["greed_days"], "极恐天数": mc["fear_days"]})
    freq = pd.DataFrame(rows)

    trows = []
    for v in shoutu_variants.VARIANT_KEYS:
        off = results[_combo_id(v, False)]
        on = results[_combo_id(v, True)]
        m_off = runner.performance_metrics(off["returns"].loc[EFFECT_START:])
        m_on = runner.performance_metrics(on["returns"].loc[EFFECT_START:])
        n_off = runner.performance_metrics(off["returns_nocost"].loc[EFFECT_START:])
        n_on = runner.performance_metrics(on["returns_nocost"].loc[EFFECT_START:])
        trows.append({
            "变体": v,
            "调仓次数(非keyed)": off["strat"].order_count,
            "调仓次数(keyed)": on["strat"].order_count,
            "Δ调仓次数": on["strat"].order_count - off["strat"].order_count,
            "年化(含成本,非keyed)%": 100 * m_off["annual_return"],
            "年化(含成本,keyed)%": 100 * m_on["annual_return"],
            "年化(不含成本,非keyed)%": 100 * n_off["annual_return"],
            "年化(不含成本,keyed)%": 100 * n_on["annual_return"],
        })
    return freq, pd.DataFrame(trows)


def _full_sample_symbols(hist):
    """守猪待兔历史里**服务端有数据**的标的（`config.SHOUTU_SYMBOLS` 的子集，按白名单序）。

    不硬编码标的：从 `config.SHOUTU_SYMBOLS` ∩ `hist["symbol"]` 推导（spec §3 全样本口径）。
    """
    have = set(hist["symbol"])
    return [s for s in config.SHOUTU_SYMBOLS if s in have]


def robustness_panel(us_v2, crypto, hist, sig_wide, basket_weights, symbols):
    """④ 稳健性对照的一个样本：**只变「守猪待兔信号所用的标的集合」**，返回增量行。

    ⚠️ **可对照性（关键）**：本面板固定两件事，只变一个因素：
      1. **可交易组合（篮子 / 执行约束）恒为主样本三标的**（`basket_weights` =
         生产口径 `risk_weight_series(wide)`）。全样本标的**不可交易**：CONL 只在
         `crypto_prices.csv`、GDXU 的底层是合成列 ⇒ `symbols` 只影响**信号聚合**。
      2. **信号聚合的权重口径对两个样本统一用 `config.WEIGHTING`（inv_vol）**，
         底层取 `config.SIGNAL_UNDERLYING_MAP`（**研究用**映射，不动生产
         `UNDERLYING_MAP`）⇒ 与主表同口径，差异**唯一**归因到「标的集合」。
    主表（表 1/表 A）仍用生产口径 `risk_weight_series(wide)`。

    `sig_wide`：研究用宽表（`pipeline.signal_wide` 构造）—— 在 `wide` 基础上补齐全样本标的的
    无杠杆底层列（合成列 + 币股）。⚠️ 早期版本此处**统一等权**，理由是「`wide` 里
    CONL/YINN/GDXU 没有 close」；该理由**不准确**（YINN/GDXU 本就在 `prices.csv`），
    真正的障碍是 GDXU 的底层缺 GDXJ、CONL 的底层在另一张表 —— 现均已补齐。
    """
    sig_weights = pipeline.risk_weight_series(
        sig_wide, symbols=symbols, underlying_map=config.SIGNAL_UNDERLYING_MAP)
    # 篮子恒为主样本三标的：`basket_weights` 的列就是 `config.SYMBOLS`，而
    # `weighted_basket_returns` 只取**权重的列** ⇒ 这里传 `sig_wide`（只多出研究用列）
    # 与传生产 `wide` 的结果**逐位相同**。
    basket = pipeline.basket_price_series(
        pipeline.weighted_basket_returns(sig_wide, basket_weights))
    swide = shoutu_variants.shoutu_wide_from_long(hist, symbols)
    res = {}
    for v in shoutu_variants.VARIANT_KEYS:
        for keyed in KEYED_FLAGS:
            core = (None if v == shoutu_variants.BASELINE
                    else shoutu_variants.variant_core_series(
                        us_v2, sig_weights, hist, v, symbols=symbols))
            trig = (None if not keyed
                    else pipeline.shoutu_market_index(us_v2, sig_weights, swide,
                                                      symbols=symbols))
            pf = pipeline.run_portfolio(us_v2, crypto, write=False, us_core=core,
                                        us_trigger_index=trig)
            base = (pf["us_core"].fillna(0.0) + pf["ammo_us"]).clip(upper=1.0).shift(1)
            f = us_v2.copy()
            f["target_position"] = base
            f["fg_index"] = us_v2["fg_index"]
            f["zone"] = us_v2["zone"]
            for col in ("open", "high", "low", "close"):
                f[col] = basket
            f["volume"] = 0.0
            _, returns = runner.run_single(f, "BASKET")
            res[(v, keyed)] = returns
    rows = []
    for v in shoutu_variants.VARIANT_KEYS:
        for start, wname in ((None, "全历史"), (EFFECT_START, "纯效应段")):
            ro = res[(v, False)]
            rn = res[(v, True)]
            ro = ro if start is None else ro.loc[start:]
            rn = rn if start is None else rn.loc[start:]
            mo, mn = runner.performance_metrics(ro), runner.performance_metrics(rn)
            rows.append({
                "样本": "%d 标的（%s）" % (len(symbols), "+".join(symbols)),
                "n_symbols": len(symbols), "变体": v, "窗口": wname,
                "Δ年化(pp)": 100 * (mn["annual_return"] - mo["annual_return"]),
                "ΔCalmar": mn["calmar"] - mo["calmar"],
            })
    return rows


def main():
    us_v2 = pipeline.run_equity_v2()
    crypto = pipeline.run_crypto(write=False)
    wide = pipeline.load_wide()
    weights = pipeline.risk_weight_series(wide)
    # 研究用宽表：补齐全样本标的的无杠杆底层（**只增列**，不动任何原列）
    sig_wide = pipeline.signal_wide(wide)
    hist = loader.load_shoutu_history()
    # 守猪待兔**宽表**（date × symbol，值 = score）：`us_trigger_index`（keyed）与
    # 高情绪掩码共用同一份 ⇒ 只构造一次。
    shoutu_wide = shoutu_variants.shoutu_wide_from_long(hist)
    basket_ret = pipeline.weighted_basket_returns(wide, weights)
    basket = pipeline.basket_price_series(basket_ret)

    # 8 组合 = 4 变体 × 2 keyed（A2-E）。`keyed=False` 与 A1 的 4 变体逐位同口径。
    results = {_combo_id(v, k): run_combo(v, k, us_v2, crypto, weights, hist,
                                          shoutu_wide, basket)
               for v, k in COMBO_KEYS}

    pd.set_option("display.width", 240)
    print("数据：shoutu_history.csv（%s ~ %s）；主样本 %s"
          % (hist["date"].min().date(), hist["date"].max().date(),
             " / ".join(config.SYMBOLS)))
    print("权重口径：%s；组合级 = 加权篮子 + FgStrategy 单组合口径" % config.WEIGHTING)
    print("组合集：%d 个 = %d 变体 × (keyed=False / True)；keyed=True ⇒ "
          "熔断 / 极恐触发源改用守猪待兔口径"
          % (len(COMBO_KEYS), len(shoutu_variants.VARIANT_KEYS)))
    print()

    print("=== 表 1：组合级指标（窗口 = 全历史）===")
    print(metrics_frame(results).round(4).to_string(index=False))
    print()
    print("=== 表 1b：组合级指标（窗口 = 纯效应段，%s 起）===" % EFFECT_START)
    print(metrics_frame(results, EFFECT_START).round(4).to_string(index=False))
    print()

    H, Hs, overlap = high_mood_masks(us_v2, shoutu_wide)
    print("=== 表 2：高情绪区间相对收益差（H = fg_index >= %.0f；共 %d 天）==="
          % (HIGH_MOOD_INDEX, int(H.sum())))
    base_rets = results[_combo_id(shoutu_variants.BASELINE, False)]["returns"]
    rows = []
    for r in results.values():
        rets = r["returns"].reindex(base_rets.index)
        diff = (rets[H.reindex(rets.index).fillna(False)]
                - base_rets[H.reindex(base_rets.index).fillna(False)])
        rows.append({"组合": r["combo"], "说明": r["label"], "n_H": int(len(diff)),
                     "Σ差(pp)": 100 * diff.sum(), "均值差(pp)": 100 * diff.mean()})
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print("对照：守猪待兔高情绪日（任一主标的 >= %+.0f）= %d 天；与 H 重叠 %d 天"
          % (SHOUTU_GREED_LINE, int(Hs.sum()), overlap))
    print()

    H2 = H & (H.index >= pd.Timestamp(EFFECT_START))
    print("=== 表 2c：高情绪区间相对收益差（纯效应段 %s 起，H 子集 %d 天）==="
          % (EFFECT_START, int(H2.sum())))
    rows = []
    for r in results.values():
        rets = r["returns"].reindex(base_rets.index)
        diff = (rets[H2.reindex(rets.index).fillna(False)]
                - base_rets[H2.reindex(base_rets.index).fillna(False)])
        rows.append({"组合": r["combo"], "说明": r["label"], "n_H2": int(len(diff)),
                     "Σ差(pp)": 100 * diff.sum(), "均值差(pp)": 100 * diff.mean()})
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print()

    print("=== 表 2b：归因（各标的加权贡献 Σ_t base_t × w_i,t × r_i,t；单位 pp）===")
    rows = []
    for r in results.values():
        c_h = shoutu_variants.attribution_contributions(wide, weights, r["base"], H)
        c_o = shoutu_variants.attribution_contributions(wide, weights, r["base"], ~H)
        row = {"组合": r["combo"], "说明": r["label"]}
        for s in config.SYMBOLS:
            row["H·" + s] = 100 * float(c_h[s])
        row["非H合计"] = 100 * float(c_o.sum())
        rows.append(row)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print()

    print("=== 表 3：机制性指标（core == 0 的暴露与换手）===")
    rows = []
    for r in results.values():
        st = flat_stats(r["pf"]["us_core"])
        lag_med, lag_n = reentry_lag(r["pf"]["us_core"], Hs)
        rows.append({"组合": r["combo"], "说明": r["label"],
                     "清仓天数": st["zero_days"], "清仓占比": st["zero_share"],
                     "平均连续清仓": st["avg_flat_run"], "最长连续清仓": st["max_flat_run"],
                     "操作次数": r["strat"].order_count,
                     "平均目标仓位": float(r["base"].dropna().mean()),
                     "买回延迟中位": lag_med, "延迟样本数": lag_n})
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print()

    print("=== 表 4：归因口径偏差（目标口径 vs 策略实际收益；供 §14.5 ④ 引用）===")
    rows = []
    for r in results.values():
        rets = r["returns"].reindex(base_rets.index).fillna(0.0)
        b = r["base"].reindex(rets.index).fillna(0.0)
        br = basket_ret.reindex(rets.index).fillna(0.0)
        attr_all = float((b * br).sum())
        attr_h = float((b * br)[H.reindex(rets.index).fillna(False)].sum())
        ret_all = float(rets.sum())
        ret_h = float(rets[H.reindex(rets.index).fillna(False)].sum())
        rows.append({"组合": r["combo"], "说明": r["label"],
                     "归因和%(全期)": 100 * attr_all, "策略和%(全期)": 100 * ret_all,
                     "偏差pp(全期)": 100 * (ret_all - attr_all),
                     "归因和%(H段)": 100 * attr_h, "策略和%(H段)": 100 * ret_h,
                     "偏差pp(H段)": 100 * (ret_h - attr_h)})
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print()

    # ---------------- A2-E Task 2：四张表（① 主表 ② 增量 ③ 触发频率/换手 ④ 稳健性）--------
    keyed_trigger = pipeline.shoutu_market_index(us_v2, weights, shoutu_wide)

    print("=== 表 A（① 组合级主表）：8 组合 × 双窗口：年化 / 最大回撤 / Calmar / 高情绪Σ差 ===")
    print(main_table(results, H, base_rets).round(4).to_string(index=False))
    print()

    print("=== 表 B（② 增量表）：keyed − 非 keyed（逐变体 × 逐窗口）===")
    print(increment_table(results).round(4).to_string(index=False))
    print()

    print("=== 表 C（③ 触发频率 / 换手）：keyed 口径 vs 市场指数口径；调仓次数；含/不含成本年化 ===")
    freq, turn = trigger_turnover_table(results, us_v2, keyed_trigger)
    print("[C1] 触发天数对照（按窗口）—— 熔断（>= %d）/ 极恐（<= %d）"
          % (GREED_TRIGGER, FEAR_TRIGGER))
    print(freq.to_string(index=False))
    print("[C2] 调仓次数 + 含成本 / 不含成本年化（纯效应段 %s 起）" % EFFECT_START)
    print(turn.round(4).to_string(index=False))
    print()

    # 核对点 #4：触发日分布（是否由少数几天主导）。
    dist = shoutu_analysis.trigger_date_distribution(
        keyed_trigger, GREED_TRIGGER, FEAR_TRIGGER)
    print("[C3] keyed 触发日分布（核对「少数几天主导」）")
    print("  熔断 %d 天；按月：%s" % (len(dist["greed"]), dist["greed_months"]))
    print("  极恐 %d 天；按月：%s" % (len(dist["fear"]), dist["fear_months"]))
    print("  熔断日全列：%s" % ", ".join(d.strftime("%Y-%m-%d") for d in dist["greed"]))
    print("  极恐日全列：%s" % ", ".join(d.strftime("%Y-%m-%d") for d in dist["fear"]))
    print()

    print("=== 表 D（④ 稳健性对照）：主样本 vs 全样本 —— 增量对照 ===")
    main_syms = list(config.SYMBOLS)
    full_syms = _full_sample_symbols(hist)
    print("  样本口径：主样本 = %s；全样本 = %s（守猪待兔历史有数据者）"
          % ("+".join(main_syms), "+".join(full_syms)))
    print("  ⚠️ 可对照性：**可交易篮子恒为主样本三标的**（全样本标的不可交易 ——")
    print("     CONL 只在 crypto_prices.csv、GDXU 的底层是合成列）；`symbols` 只影响")
    print("     **守猪待兔信号的聚合**；信号权重对两个样本**统一用 config.WEIGHTING = %s**，"
          % config.WEIGHTING)
    print("     底层取 config.SIGNAL_UNDERLYING_MAP（研究用；不动生产 UNDERLYING_MAP）")
    print("     ⇒ 与主表同口径，差异唯一归因到「标的集合」一个因素。")
    rob_rows = (robustness_panel(us_v2, crypto, hist, sig_wide, weights, main_syms)
                + robustness_panel(us_v2, crypto, hist, sig_wide, weights, full_syms))
    print(pd.DataFrame(rob_rows).round(4).to_string(index=False))
    print()

    # 核对点 #3：红线 —— 历史区间（EFFECT_START 之前）keyed 与非 keyed 逐位相同。
    print("[E] 红线核对：历史区间（%s 之前）keyed=True vs keyed=False 的最大绝对差"
          % EFFECT_START)
    worst = 0.0
    for v in shoutu_variants.VARIANT_KEYS:
        off = results[_combo_id(v, False)]["returns"].loc[:EFFECT_START]
        on = results[_combo_id(v, True)]["returns"].loc[:EFFECT_START]
        d = (off - on).abs().max()
        worst = max(worst, float(d) if d == d else 0.0)
        print("  %-3s max|Δ| = %.3e" % (v, float(d) if d == d else 0.0))
    print("  ⇒ 全域最大 %.3e（应为 ~0，证明 keyed 在效应窗之前逐位等价）" % worst)
    print("  ⚠️ 口径提醒：**全历史窗口**下 keyed=True 与 keyed=False **仍会有差**"
          "（效应窗内合法分叉）—— 红线只约束 %s（效应窗）**之前**。" % EFFECT_START)
    print()

    print("=== 结论（量级 + 机制 + 纪律声明）===")
    print("1) 量级：见上表；两个窗口必须并列读。⚠️ `2024-04-23` 之前**只有 V1 与基准重合**"
          "（V1 的表 = 全局表）；**V2/V3 不是** —— 该日之前守猪待兔回退到市场指数后"
          "仍会套用各自的变体表 ⇒ 对 V2/V3 是「变体表 + 市场指数回退」，**不是**效应稀释。")
    print("1b) keyed 维度：`keyed=True` 在守猪待兔覆盖区间**之前**逐位等价 `fg_index`"
          "⇒ 历史区间 keyed 与非 keyed 曲线**逐位相同**（红线）；只有纯效应段可能分叉。")
    print("2) 机制：见「表 3」—— 清仓占比与最长连续清仓说明规则的实际离场暴露。")
    print("3) 纪律：**不排名、不挑最优**；**回测不作为改规则的依据**；")
    print("   改不改、改哪个值由**先验推导 + 真实操作复盘**（第 13.6 条 O4 / 第 8.4 条）决定。")
    print("   明示：`keyed=False` 的熔断/极恐仍以市场指数为触发源；RANK_WINDOW=756 未满"
          " ⇒ 实际走 fixed 口径；")
    print("   守猪待兔历史仅约 2.4 年 ⇒ 年化/Calmar 为量级估计；不做显著性检验。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
