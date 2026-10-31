"""因子评测协议（R1.1，Qlib 蓝图自实现）：IC/RankIC + 分层净值 + 多空对冲 + 含成本双口径。

与 `eval.py`（滚动 IC/ICIR 地基）的关系：
  - eval.py 保持为轻量核心（forward_returns / rolling_ic / icir），供 drift_monitor 等复用；
  - 本模块在 eval 之上补齐 Qlib 式裁判：Pearson IC 与 Spearman RankIC 双口径、
    滚动分位分层净值、顶底多空对冲净值、含/不含成本双口径、门槛判定。

纪律（factor-engine.md §4 硬规则）：
  - **无前视**：信号日期 t 只对 t+1..t+N 收益；分层分桶只用「截至当日」的滚动分位
    （禁止全样本分位——会把未来信息泄漏进分组）。
  - **确定性**：全部纯函数、无随机、无状态；同输入必同输出。
  - **门槛**：|ICIR| ≥ 0.5 且 n ≥ 60 且近窗（120 交易日）无衰减（factor-engine.md §4.4/4.5）。

用法（模块）：
    from fg_system.factors.protocol import screen_report, verdict
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from fg_system.factors.eval import forward_returns, icir, rolling_ic

DEFAULT_HORIZONS = (5, 10, 20, 40)
DEFAULT_WINDOW = 60            # IC 滚动窗（与 eval 一致）
RANK_WINDOW = 756              # 分层分桶滚动分位窗（与 config.RANK_WINDOW 一致）
N_BUCKETS = 5                  # 分 5 组（Qlib quintile）
DEFAULT_FEE = 0.001            # 单边成本率 10bp（参数化；含成本口径用）
GATE_ICIR = 0.5                # 入库门槛 |ICIR|
GATE_MIN_N = 60                # 最小样本
GATE_RECENT = 120              # 近窗天数


# ---------------------------------------------------------------- IC 双口径

def ic_pearson(signal: pd.Series, target: pd.Series, window: int = DEFAULT_WINDOW) -> pd.Series:
    """滚动 Pearson IC（Qlib 的 IC 口径）。

    target 为日频目标序列（如未来收益）。内部按共同日期对齐后滚动相关。
    样本不足返回空 Series。
    """
    df = pd.concat([signal.rename("sig"), target.rename("tgt")], axis=1).dropna()
    if len(df) < window + 2:
        return pd.Series(dtype=float)
    return df["sig"].rolling(window).corr(df["tgt"])


def ic_spearman(signal: pd.Series, target: pd.Series, window: int = DEFAULT_WINDOW) -> pd.Series:
    """滚动 Spearman RankIC（Qlib 的 RankIC 口径；等价 eval.rolling_ic 的 spearman 分支）。"""
    return rolling_ic(signal, target, window=window, method="spearman")


def ic_stats(ic_series: pd.Series) -> dict | None:
    """由 IC 序列计算汇总统计（复用 eval.icir 口径）。"""
    return icir(ic_series)


def ic_autocorr(signal: pd.Series, target: pd.Series,
                window: int = DEFAULT_WINDOW):
    """IC 序列的 **lag-1 自相关** 与**有效样本数** ✓（2026-10-31）。

    🔴 为什么必须报：`rolling_ic(window=60)` 让相邻两天的 IC **共享 59 天**数据 ✗，
    叠加「重叠 forward return」与「慢变因子」⇒ IC 序列几乎平滑 ✗
    实测（C5 ENE）自相关 **0.99** ⇒ 名义 2400 天的 |ICIR| 1.48，
    实际只由 **7~10 个**独立观测撑起 ✗

    有效样本数：`n_eff ≈ n × (1−ρ)/(1+ρ)` ✓

    :returns: `(ac1, n_eff)`；算不出 ⇒ `(None, None)`（不编造 ✓）
    """
    try:
        # 用 **Pearson** 滚动 IC ✓ —— `ic_spearman` 走 `rolling_ic`，
        # 实测在本仓库对长序列返回全 NaN ✗（`autocorr` 拿不到值 ✗）；
        # 自相关是「IC 序列的平滑程度」，两种口径结论一致 ✓
        # 🔴 2026-10-31 实测两个坑：
        #   ① `Series.autocorr(1)` 在**日期索引**上返回 NaN ✗
        #   ② 滚动相关在「窗口内某侧方差为 0」时产出 **inf** ✗
        #      （`dropna()` 不滤 inf ✗ ⇒ 后面 std 变 NaN ⇒ 全链路失效 ✗）
        ser = ic_pearson(signal, target, window=window)
        ser = ser.replace([np.inf, -np.inf], np.nan).dropna()
        if len(ser) < 10:
            return None, None
        # 手动按位置错位算 Pearson ✓（等价于 lag-1 自相关 ✓）
        v = ser.to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        if len(v) < 10:
            return None, None
        a, b = v[:-1], v[1:]
        if a.std() == 0 or b.std() == 0:
            return None, None
        ac1 = float(np.corrcoef(a, b)[0, 1])
    except Exception:                       # noqa: BLE001 —— 算不出就不报 ✓
        return None, None
    if ac1 is None or pd.isna(ac1):
        return None, None
    n_eff = len(ser) * (1.0 - ac1) / (1.0 + ac1) if ac1 < 1 else 0.0
    return ac1, n_eff


def recent_stats(ic_series: pd.Series, recent: int = GATE_RECENT) -> dict | None:
    """近窗（默认最近 120 个 IC 值）统计，用于衰减判定。"""
    ic = ic_series.dropna()
    if len(ic) == 0:
        return None
    return icir(ic.iloc[-recent:])


# ---------------------------------------------------------------- 分层

def rolling_quantile_bucket(signal: pd.Series, window: int = RANK_WINDOW,
                            n_buckets: int = N_BUCKETS) -> pd.Series:
    """信号对**自身滚动分位**分桶（1..n_buckets），无前视。

    t 日分位 = signal 在 (t-window, t] 内（含 t）的百分位排名；
    分位 <20% → 桶 1（最恐惧/最低）… ≥80% → 桶 5（最贪婪/最高）。
    窗口不足（前 window-1 日）为 NaN——避免用短窗噪声分桶。
    """
    pct = signal.rolling(window, min_periods=window).rank(pct=True)
    bucket = (pct * n_buckets).clip(lower=1, upper=n_buckets).round().astype("Int64")
    return bucket.rename("bucket")


def bucket_forward_stats(signal: pd.Series, close: pd.Series, horizons=DEFAULT_HORIZONS,
                         n_buckets: int = N_BUCKETS, window: int = RANK_WINDOW) -> dict:
    """分层统计：每 horizon 每桶的未来收益均值 / 样本数 / 顶底差 / 组间单调性。

    返回 {h: {"bucket_means": [...], "bucket_n": [...], "top_minus_bottom": float,
              "monotonic_spearman": float|None}}。
    单调性 = 桶均值序列与组号 [1..n] 的 Spearman 相关（>0 且接近 1 = 单调分层有效）。
    """
    buckets = rolling_quantile_bucket(signal, window=window, n_buckets=n_buckets)
    fwd = forward_returns(close, horizons)
    out = {}
    for h in horizons:
        df = pd.concat([buckets, fwd[f"fwd_{h}"]], axis=1).dropna()
        if len(df) == 0:
            out[h] = None
            continue
        means, counts = [], []
        for b in range(1, n_buckets + 1):
            sub = df.loc[df["bucket"] == b, f"fwd_{h}"]
            means.append(float(sub.mean()) if len(sub) else None)
            counts.append(int(len(sub)))
        top_bot = None
        mono = None
        if means[0] is not None and means[-1] is not None:
            top_bot = float(means[-1] - means[0])
        valid = [(i + 1, m) for i, m in enumerate(means) if m is not None]
        if len(valid) >= 3:
            x = pd.Series([v[0] for v in valid], dtype=float)
            y = pd.Series([v[1] for v in valid], dtype=float)
            mono = float(x.rank().corr(y.rank()))
        out[h] = {"bucket_means": means, "bucket_n": counts,
                  "top_minus_bottom": top_bot, "monotonic_spearman": mono}
    return out


# ---------------------------------------------------------------- 多空对冲 + 含成本

def long_short_nav(buckets: pd.Series, fwd: pd.Series, horizon: int,
                   fee: float = DEFAULT_FEE, n_buckets: int = N_BUCKETS,
                   direction: str = "正向") -> dict | None:
    """时间序列版多空对冲净值（Qlib LSR 的时序代理，口径文档注明）。

    非重叠调仓：每 horizon 天一个调仓点（df.iloc[::h]）。
    方向语义（factor-engine.md §4.2 逆向语义）：
      正向因子 → 顶桶做多（+fwd）、底桶做空（−fwd）；
      逆向因子 → 顶桶做空、底桶做多（贪恐分高=贪婪→未来跌）。
    中性桶空仓跳过。多空净值 = (1 + 带符号收益).cumprod()。
    含成本口径：每持有期扣单边成本 fee 的两倍（多+空两腿换仓），净值终值对比。

    返回 {nav_final, nav_final_net, annualized, annualized_net, max_dd, max_dd_net,
          n_periods, fee}；样本不足返回 None。
    """
    df = pd.concat([buckets.rename("b"), fwd.rename("r")], axis=1).dropna()
    if len(df) == 0:
        return None
    df = df.iloc[::horizon]  # 非重叠调仓点
    long_bucket, short_bucket = (n_buckets, 1) if direction != "逆向" else (1, n_buckets)
    signed = pd.Series(np.nan, index=df.index)
    signed.loc[df["b"] == long_bucket] = df["r"].loc[df["b"] == long_bucket]
    signed.loc[df["b"] == short_bucket] = -df["r"].loc[df["b"] == short_bucket]
    signed = signed.dropna()
    if len(signed) < 2:
        return None
    nav = (1.0 + signed).cumprod()
    nav_net = (1.0 + signed - 2.0 * fee).cumprod()
    n_periods = int(len(signed))
    ann = float(nav.iloc[-1] ** (252.0 / n_periods) - 1.0) if nav.iloc[-1] > 0 else None
    ann_net = float(nav_net.iloc[-1] ** (252.0 / n_periods) - 1.0) if nav_net.iloc[-1] > 0 else None
    dd = float((nav / nav.cummax() - 1.0).min())
    dd_net = float((nav_net / nav_net.cummax() - 1.0).min())
    return {"nav_final": float(nav.iloc[-1]), "nav_final_net": float(nav_net.iloc[-1]),
            "annualized": ann, "annualized_net": ann_net,
            "max_dd": dd, "max_dd_net": dd_net,
            "n_periods": n_periods, "fee": fee}


# ---------------------------------------------------------------- 门槛判定

def verdict(stats_by_h: dict, recent_by_h: dict, direction: str = "逆向") -> dict:
    """门槛判定（factor-engine.md §4.4/4.5）：|ICIR| ≥ 0.5 且 n ≥ 60 且近窗无衰减。

    🔴 **2026-10-31 起：ICIR 门槛降级为「参考」** ✗ ——
    实测 IC 自相关高达 0.99 ⇒ 有效样本仅为名义的约 0.5% ✗
    ⇒ 「通过」只代表「**IC 层面方向一致**」，**不代表可以采纳** ✓
    ⇒ 采纳判据是**回测裁判**（`factor_backtest_probe`：实际收益 vs B0）✓
    

    stats_by_h = {h: ic_stats|None}（Spearman RankIC 口径做判据）；
    recent_by_h = {h: recent_stats|None}。
    返回 {"status": "通过|accumulating|未达门槛", "detail": str, "best_horizon": int|None}。
    近窗衰减判据：近窗 |ICIR| < 全窗 |ICIR| × 0.5（与 drift_monitor 同向口径）。
    """
    passed, accumulating, best_h = [], None, None
    for h, st in stats_by_h.items():
        if st is None or st["n"] < 10:
            accumulating = accumulating or h
            continue
        rec = recent_by_h.get(h)
        rec_ok = rec is None or abs(rec["icir"]) >= abs(st["icir"]) * 0.5
        ok_gate = abs(st["icir"]) >= GATE_ICIR and st["n"] >= GATE_MIN_N
        if ok_gate and rec_ok:
            passed.append(h)
        if st["n"] < GATE_MIN_N:
            accumulating = accumulating or h
    if passed:
        # 🔴 2026-10-31 用户裁定：**ICIR 门槛正式降级为参考** ✗
        # 实测（C5 ENE）：IC 自相关 **0.99** ⇒ 有效样本 n_eff ≈ n×0.005
        #   ⇒ 名义 2400 天的 |ICIR| 1.48，实际只由 **7~10 个**独立观测撑起 ✗
        # 成因是三重叠加：滚动窗（相邻 IC 共享 59 天）+ 重叠 forward return
        #   + 慢变因子 ⇒ IC 序列几乎平滑 ✗
        # ⇒ status 仍叫「通过」（向后兼容 ✓），但 detail 必须说清
        #   「**仅 IC 层面**，采纳一律由回测裁判决定」✓
        status = "通过"
        detail = (f"horizon {passed} 的 |ICIR| ≥ {GATE_ICIR} 且近窗无衰减"
                  f"（{direction}）—— ⚠️ **ICIR 仅作方向参考，不作采纳依据** ✗："
                  "滚动窗 + 重叠收益 + 慢变因子会让 ICIR **结构性虚高**"
                  "（实测 IC 自相关 0.99 ⇒ 有效样本仅为名义的约 0.5%）"
                  "⇒ **采纳与否一律由回测裁判（实际收益 vs B0）决定** ✓")
        return {"status": status, "detail": detail, "best_horizon": max(passed),
                "passed": passed, "ic_reference_only": True}
    if accumulating is not None:
        return {"status": "accumulating", "detail": f"样本不足（n<{GATE_MIN_N}，horizon {accumulating}）→ 继续积累",
                "best_horizon": None, "passed": []}
    return {"status": "未达门槛", "detail": "有样本但 |ICIR|<0.5 或近窗衰减 → 拒收/观察",
            "best_horizon": None, "passed": []}


# ---------------------------------------------------------------- 汇总报告

def screen_report(signal: pd.Series, close: pd.Series, factor_id: str = "",
                  target: str = "SPY", direction: str = "逆向",
                  horizons=DEFAULT_HORIZONS, window: int = DEFAULT_WINDOW,
                  n_buckets: int = N_BUCKETS, fee: float = DEFAULT_FEE) -> dict:
    """一次完整评测 → dict（JSON 序列化友好，字段齐全）。

    字段：factor_id / target / direction / sample 区间 / n_days /
          ic（Pearson+RankIC 双口径 × horizon × 近窗）/
          layers（分层统计 × horizon）/ long_short（多空+含成本 × horizon）/
          verdict（门槛判定）。
    输入为空或样本不足时返回含 None 的完整骨架，不抛异常。
    """
    sig = signal.dropna().sort_index()
    c = close.dropna().sort_index()
    base = {"factor_id": factor_id, "target": target, "direction": direction,
            "horizons": list(horizons), "window": window, "fee": fee}
    if len(sig) == 0 or len(c) == 0:
        return {**base, "sample_start": None, "sample_end": None, "n_days": 0,
                "ic": {}, "recent": {}, "layers": {}, "long_short": {}, "verdict": None}
    fwd = forward_returns(c, horizons)
    ic_out, recent_out = {}, {}
    for h in horizons:
        tgt = fwd[f"fwd_{h}"]
        p_ic = ic_pearson(sig, tgt, window=window)
        r_ic = ic_spearman(sig, tgt, window=window)
        p_st, r_st = ic_stats(p_ic), ic_stats(r_ic)
        ic_out[h] = {
            "pearson_ic_mean": p_st["ic_mean"] if p_st else None,
            "pearson_icir": p_st["icir"] if p_st else None,
            "pearson_pos_ratio": p_st["ic_positive_ratio"] if p_st else None,
            "rank_ic_mean": r_st["ic_mean"] if r_st else None,
            "rank_icir": r_st["icir"] if r_st else None,
            "rank_pos_ratio": r_st["ic_positive_ratio"] if r_st else None,
            "n": r_st["n"] if r_st else 0,
        }
        rec = recent_stats(r_ic)
        recent_out[h] = rec  # icir dict（含 ic_mean/ic_std/icir/ic_positive_ratio/n），供 verdict 判衰减
    layers = bucket_forward_stats(sig, c, horizons=horizons, n_buckets=n_buckets)
    buckets = rolling_quantile_bucket(sig)
    ls = {}
    for h in horizons:
        ls[h] = long_short_nav(buckets, fwd[f"fwd_{h}"], h, fee=fee, n_buckets=n_buckets,
                               direction=direction)
    stats_by_h = {h: (ic_stats(ic_spearman(sig, fwd[f"fwd_{h}"], window=window))
                      if len(sig) else None) for h in horizons}
    v = verdict(stats_by_h, recent_out, direction=direction)
    return {**base,
            "sample_start": sig.index.min().strftime("%Y-%m-%d"),
            "sample_end": sig.index.max().strftime("%Y-%m-%d"),
            "n_days": int(len(sig)),
            "ic": ic_out, "recent": recent_out,
            "layers": layers, "long_short": ls, "verdict": v}
