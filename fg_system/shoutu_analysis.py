# -*- coding: utf-8 -*-
"""守猪待兔「早清仓代价」分析（Step B · C 阶段）。

设计：docs/superpowers/specs/2026-09-24-shoutu-greed-exit-cost-design.md

**本模块只做纯计算**（可离线测试）：不读文件、不打印、不做 I/O。
编排（读 CSV、出表、交叉校验）在 `scripts/analyze_shoutu_greed.py`。
"""
import pandas as pd

from fg_system import config
from fg_system.signal import portfolio

# 交叉校验门槛（2026-09-24 用户裁决，见 spec 附 B）。
# ⚠️ **级差 `max_rel` 不作为判据** —— `shoutu_history.csv` 的 price 是**前复权**
# （含分红再投），`prices.csv` 的 close **未含分红调整** ⇒ 2.4 年累计级差约 2%，
# 差异全部落在**除息日**。分析只用 `pct_change` ⇒ 真正的 go 门是**日收益一致性**。
PRICE_CORR_MIN = 0.9999        # 日收益相关系数下限
PRICE_MAX_ABS_DRET = 0.005     # 单日收益差上限（0.5%）

# 除息日识别阈值（2026-09-28 用户裁决 **(a) 排除除息日**）。
# 依据：`hist/ref` 比值 = **累计分红因子**，两次除息之间**恒定**（实测 2026-09-17~09-23
# 恒为 `0.99807`），只在除息日当天**阶跃**（实测 `09-24` 跳到 `0.98111` = **−1.70%**）。
# 而 CSV 的价格精度约 0.01 元（≈0.02%）⇒ 取 **0.1%** 既有余量、又不会漏。
EX_DIV_STEP_MIN = 0.001


def greed_episodes(series, threshold=None):
    """找出 `series` 里**进入贪婪档**的 episode（连续区间）。

    `series`：index = 日期（**升序**），值 = 守猪待兔**原值**（−100 ~ 100）。
    `threshold`：贪婪线，默认 `config.SHOUTU_GREED_LINE`（+60）。

    返回 DataFrame（每 episode 一行）：

    | 列 | 含义 |
    |---|---|
    | `start` / `end` | 进入日 / 结束日 |
    | `days` | 区间内**交易日数**（含首尾） |
    | `peak` | 区间内最大值（原值） |
    | `closed` | 该段**之后仍有数据**为 `True`；**段尾即数据末尾**为 `False`（未完成） |

    ⚠️ 判定是 `>= threshold`（**等于算在内**），与 `ZONE_EDGES` 的
    `searchsorted(side="right")` 语义一致 —— 若这里用 `>`，边界日的档位
    会与分析外的地方对不上。
    """
    thr = config.SHOUTU_GREED_LINE if threshold is None else float(threshold)
    s = series.dropna().sort_index()
    cols = ["start", "end", "days", "peak", "closed"]
    if s.empty:
        return pd.DataFrame(columns=cols).astype({"closed": bool})

    in_zone = (s >= thr).to_numpy()
    idx = s.index
    rows = []
    i = 0
    n = len(in_zone)
    while i < n:
        if not in_zone[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and in_zone[j + 1]:
            j += 1
        rows.append({
            "start": idx[i],
            "end": idx[j],
            "days": j - i + 1,
            "peak": float(s.iloc[i:j + 1].max()),
            "closed": bool(j < n - 1),
        })
        i = j + 1
    return pd.DataFrame(rows, columns=cols)


def replay_exit_path(targets, p0):
    """逐日回放规则侧仓位路径。返回与 `targets` 同索引的实际仓位 Series。

    `targets`：每日的**目标仓位**（由 `P0 × ZONE_SATURATION[zone(值)]` 得到）。
    `p0`：起点仓位。

    ⚠️ **必须走 `portfolio.next_position`**（与 `FgStrategy` 同一个函数）——
    不得在此另写阈值/限幅逻辑，否则"分析里的规则 ≠ 回测里的规则"。

    ⚠️ 回放覆盖**整个窗口**：目标回到非零时会**重新买回**（`next_position` 天然
    支持），**不得"冻结"**在清仓后的 0 仓位 —— 冻结等于假设永不买回，
    会**系统性高估**卖飞。
    """
    out = []
    cur = float(p0)
    for t in targets:
        cur = portfolio.next_position(cur, float(t))
        out.append(cur)
    return pd.Series(out, index=targets.index, dtype=float)


def ex_dividend_dates(hist_price, ref_price, step_threshold=None):
    """识别**除息日**：`hist_price / ref_price` 比值发生**阶跃**的日期。

    **为什么这样识别**（2026-09-28 用户裁决 **(a) 排除除息日**）：
    `shoutu_history.csv` 的 `price` 是**前复权**（把分红从历史价里抹掉）、
    `prices.csv` 的 `close` **未含分红调整** ⇒ 两者**比值** = **累计分红因子**，
    在两次除息之间**恒定**（实测 2026-09-17~09-23 恒为 `0.99807`），只在**除息日
    当天**阶跃（实测 `09-24` 跳到 `0.98111` = **−1.70%**）。

    ⚠️ 因此「日收益差在除息日必然放大」是**口径的必然**、不是数据错误 —— 判据必须
    把它们剔除，否则**每次除息都会把旗标点亮**（2026-09-28 实测三个标的全未通过）。

    `step_threshold`：比值单日相对变动的阈值（默认 `EX_DIV_STEP_MIN` = 0.1%）。
    返回 `DatetimeIndex`（无除息日时为空）。
    """
    a, b = hist_price.align(ref_price, join="inner")
    ok = a.notna() & b.notna() & (a != 0) & (b != 0)
    ratio = (a[ok] / b[ok]).sort_index()
    if len(ratio) < 2:
        return pd.DatetimeIndex([])
    step = ratio.pct_change(fill_method=None).abs()
    thr = EX_DIV_STEP_MIN if step_threshold is None else float(step_threshold)
    return pd.DatetimeIndex(step[step > thr].index)


def price_divergence(hist_price, ref_price, exclude_dates=None):
    """两个价格序列的相对偏差（取交集日期）。

    返回：
    | 键 | 含义 |
    |---|---|
    | `n` | 交集天数 |
    | `max_rel` / `mean_rel` | **级差**（相对偏差），分母取 `max(|a|,|b|)` |
    | `corr_dret` | **日收益**（`pct_change`）的相关系数 |
    | `max_abs_dret` / `mean_abs_dret` | **单日收益差**的最大值 / 均值 |
    | `excluded` | 被 `exclude_dates` 剔除的**日收益点**数 |

    ⚠️ **级差与日收益是两件事**：`shoutu_history.csv` 的 price 是**前复权**（含分红
    再投），`prices.csv` 的 close **未含分红调整** ⇒ 级差可达 2%（差异全部落在
    **除息日**），但**日收益几乎相同**（corr ≥ 0.9999）。分析只用 `pct_change`
    ⇒ **判据必须用 `corr_dret` / `max_abs_dret`，不能用 `max_rel`**（见 spec 附 B）。

    `exclude_dates`：要**剔除的日期**（除息日，见 `ex_dividend_dates`）。默认 `None`
    ⇒ 行为**逐位不变**（既有调用方零影响）。

    ⚠️ **剔除方式**：只把**那一天的收益点**丢掉，**价格序列保持完整** —— 若改成
    「删价格行」，**次日**的收益会跨过除息缺口，把被剔除的那一天**又变相算回来**
    （`tests/test_shoutu_analysis.py::test_price_divergence_excludes_the_ex_div_day_return_only`
    专门区分这两种实现）。
    """
    a, b = hist_price.align(ref_price, join="inner")
    ok = a.notna() & b.notna() & (a != 0) & (b != 0)
    a, b = a[ok], b[ok]
    nan = float("nan")
    if a.empty:
        return {"n": 0, "max_rel": nan, "mean_rel": nan,
                "corr_dret": nan, "max_abs_dret": nan, "mean_abs_dret": nan,
                "excluded": 0}
    rel = (a - b).abs() / pd.concat([a.abs(), b.abs()], axis=1).max(axis=1)
    ra = a.pct_change().dropna()
    rb = b.pct_change().dropna()
    ra, rb = ra.align(rb, join="inner")
    excluded = 0
    if exclude_dates is not None and len(exclude_dates):
        ex = pd.DatetimeIndex(exclude_dates)
        keep = ~ra.index.isin(ex)
        excluded = int((~keep).sum())
        ra, rb = ra[keep], rb[keep]
        rel = rel[~rel.index.isin(ex)]
    dr = (ra - rb).abs()
    # ⚠️ 少于 2 个日收益点算不出相关 ⇒ 返回 NaN（由 price_consistency_ok 判失败，
    #    "没查过"不等于"查过通过"）
    corr = float(ra.corr(rb)) if len(dr) >= 2 else nan
    return {"n": int(len(a)),
            "max_rel": float(rel.max()) if len(rel) else nan,
            "mean_rel": float(rel.mean()) if len(rel) else nan,
            "corr_dret": corr,
            "max_abs_dret": float(dr.max()) if len(dr) else nan,
            "mean_abs_dret": float(dr.mean()) if len(dr) else nan,
            "excluded": excluded}


def extreme_trigger_counts(series, greed_trigger, fear_trigger):
    """极端规则的**触发天数**统计（A2-E Task 2 的「触发频率」表）。

    `series`：极端规则的**触发源**指数序列（0~100），index = 日期。
    `greed_trigger` / `fear_trigger`：熔断（`>= greed`）/ 极恐（`<= fear`）阈值。

    ⚠️ **判定必须与 `market_signal` 同语义**：贪婪用 `>=`、恐惧用 `<=`
    （`market_signal.py` 的 `index_value >= EXTREME_GREED_TRIGGER` /
    `trig <= EXTREME_FEAR_TRIGGER`）。用严格不等会在**恰好等于阈值**的日子
    少算一天，使「触发频率」与真实回测不一致。

    ⚠️ **NaN 不计入**（warmup / 无信号）—— 不得把「无信号」当「触发」。

    返回 `{"greed_days": int, "fear_days": int}`。**纯计算**，不读文件、不打印。
    """
    s = pd.Series(series).dropna()
    return {
        "greed_days": int((s >= float(greed_trigger)).sum()),
        "fear_days": int((s <= float(fear_trigger)).sum()),
    }


def trigger_date_distribution(series, greed_trigger, fear_trigger):
    """触发日的**逐日列表 + 月度分布**（A2-E 核对「少数几天主导」）。

    返回：
    | 键 | 含义 |
    |---|---|
    | `greed` / `fear` | 触发日的 `pd.Timestamp` 列表（升序） |
    | `greed_months` / `fear_months` | `{"YYYY-MM": 天数}`（供看是否集中在少数月份） |

    ⚠️ 判定与 NaN 处理同 `extreme_trigger_counts`（`>=` / `<=`；NaN 跳过）。
    **纯计算**，不读文件、不打印。
    """
    s = pd.Series(series).dropna().sort_index()
    greed = list(s.index[s >= float(greed_trigger)])
    fear = list(s.index[s <= float(fear_trigger)])
    greed_months = pd.Series(greed, dtype="datetime64[ns]").dt.strftime("%Y-%m") \
        if greed else pd.Series(dtype=str)
    fear_months = pd.Series(fear, dtype="datetime64[ns]").dt.strftime("%Y-%m") \
        if fear else pd.Series(dtype=str)
    return {
        "greed": greed, "fear": fear,
        "greed_months": dict(greed_months.value_counts().sort_index())
        if len(greed_months) else {},
        "fear_months": dict(fear_months.value_counts().sort_index())
        if len(fear_months) else {},
    }


def price_consistency_ok(d, corr_min=None, max_abs_dret=None):
    """把 `price_divergence` 的结果判成 go/no-go（**日收益一致性**）。

    ⚠️ 判据**不含** `max_rel` —— 复权口径差会让级差到 2% 而日收益几乎相同，
    级差不是有效判据（见 spec 附 B）。
    ⚠️ 样本不足（< 2 个日收益点）或含 NaN ⇒ **判失败**。
    """
    corr_min = PRICE_CORR_MIN if corr_min is None else float(corr_min)
    max_abs = PRICE_MAX_ABS_DRET if max_abs_dret is None else float(max_abs_dret)
    corr = d.get("corr_dret", float("nan"))
    dr = d.get("max_abs_dret", float("nan"))
    if corr != corr or dr != dr:                     # NaN
        return False
    return corr >= corr_min and dr <= max_abs


def fng_price_caliber(fng_price, hist_price, px_close):
    """判定 `shoutu_fng.csv` 的 `price` 属于**哪个复权口径**（§14.5 **D5**）。

    **为什么必须判**：fng 的 `price` 来自**页面/接口的实时报价**，而
    `shoutu_history.csv` 的 `price` 是**前复权**（含分红再投）、`prices.csv` 的
    `close` **未含分红调整** ⇒ 两者做**水平**比较（价格 × 情绪）前必须先知道 fng
    属于谁；做**收益**比较不受影响。

    判据（spec 附 B）：取 fng 有 `price` 的日期，**分别**与两个参照源算
    `price_divergence` ⇒ **谁的日收益一致性通过（且另一方不通过），fng 就属于谁**。

    ⚠️ **分辨力需要「跨除息日」的样本**：除息日之前两者的日收益**完全一致**
    ⇒ 若两边都通过（或都不通过），返回 `"无分辨力"` —— 那是「**样本还不够**」，
    **不是**失败，更**不得**据此断言任何一方。实测 2026-09-28：fng 的 `price` 从
    09-25 起才有值、与参照源重叠仅 1 天、日收益点 0 个 ⇒ 两边都不通过。

    返回 `{"hist": d1, "prices": d2, "ok_hist": bool, "ok_prices": bool,
    "verdict": str}`。**纯函数，不做 I/O**。
    """
    d_hist = price_divergence(fng_price, hist_price)
    d_px = price_divergence(fng_price, px_close)
    ok_hist = price_consistency_ok(d_hist)
    ok_px = price_consistency_ok(d_px)
    if ok_hist and not ok_px:
        verdict = "前复权（同 shoutu_history.csv）"
    elif ok_px and not ok_hist:
        verdict = "未复权（同 prices.csv）"
    elif ok_hist:
        verdict = "无分辨力（两边都通过 ⇒ 需跨除息日样本）"
    else:
        verdict = "无分辨力（两边都不通过 ⇒ 需跨除息日样本）"
    return {"hist": d_hist, "prices": d_px,
            "ok_hist": ok_hist, "ok_prices": ok_px, "verdict": verdict}
