# -*- coding: utf-8 -*-
"""因子筛选工具：**否证性取证**，不是参数搜索（第 13.4 条）。

用途：给定一条因子序列（`raw` ∈ [0,1]，**高 = 贪婪**）与一个目标标的的收盘价，
检验先验「**因子越贪婪 → 未来 N 日收益越低**」是否成立。

================================================================================
⚠️ 这不是交易信号，**禁止用于生成仓位**
================================================================================
`forward_return` 用到了**未来**收益（`shift(-horizon)`），属第 10 条红线定义的
前视偏差。它**只能**出现在研究/取证语境里，**不得**进入 `factors/` 的任何
`Factor.raw()` 或 `signal/` 的任何决策路径。生产因子必须只用 ≤ T 的数据。
"""
import numpy as np
import pandas as pd


def forward_return(close, horizon):
    """未来 `horizon` 日收益：`close[t+h] / close[t] - 1`。

    ⚠️ 含前视偏差，**仅供研究**（见模块 docstring）。
    """
    if horizon < 1:
        raise ValueError("horizon 必须 >= 1，实际 %r" % horizon)
    return close.shift(-horizon) / close - 1.0


def bucket_table(factor, fwd, n_buckets=5):
    """按**因子自身取值**分组。

    为什么直接按 `raw` 分组就是因果的：`raw` 本身已经是 `rolling_pct` 的产物
    （窗口 756 日，只用 ≤ T 的数据），所以「T 日的组号」在 T 日即可知，
    **不需要**用全样本分位（那会引入前视）。

    返回 DataFrame，index = 组号（**0 = 最恐惧 … n-1 = 最贪婪**），
    列 = n / mean / median / win_rate。
    """
    df = pd.concat([factor.rename("f"), fwd.rename("r")], axis=1).dropna()
    if df.empty:
        return pd.DataFrame(columns=["n", "mean", "median", "win_rate"])
    b = np.clip((df["f"] * n_buckets).astype(int), 0, n_buckets - 1)
    g = df.groupby(b)["r"]
    tbl = pd.DataFrame({
        "n": g.size(),
        "mean": g.mean(),
        "median": g.median(),
        "win_rate": g.apply(lambda s: float((s > 0).mean())),
    })
    return tbl.reindex(range(n_buckets))


def spearman_ic(factor, fwd, min_n=60):
    """因子与未来收益的 **Spearman 秩相关**。**期望为负**（贪婪 → 低未来收益）。

    用秩相关而非 Pearson：因子是分位归一化值、未来收益是重尾分布，
    秩相关对两者的单调非线性关系更稳健。

    样本不足 `min_n` 时返回 NaN（禁止用不足样本下结论）。
    """
    df = pd.concat([factor.rename("f"), fwd.rename("r")], axis=1).dropna()
    if len(df) < min_n:
        return np.nan
    return float(df["f"].corr(df["r"], method="spearman"))


def screen(factor, fwd, n_buckets=5):
    """一次筛选的完整结论。

    返回 dict：
    - `ic`       Spearman 秩相关（**期望 < 0**）
    - `mono`     组均值随组号**递减**的比例（1.0 = 完全单调递减）
    - `spread`   **最恐惧组均值 − 最贪婪组均值**（**期望 > 0**，单位 = 未来收益）
    - `hit`      `P(最恐惧日收益 > 最贪婪日收益)`，成对比较（类似 AUC）。
                 **0.5 = 无判别力**，> 0.5 才符合先验。**不是**「逐日胜率」——
                 每天只属于一个组，逐日口径不存在。
    - `n`        有效样本数
    - `degenerate` **退化标记**：有组为空 ⇒ `spread` / `hit` / `ic` **都不可信**
    - `occupancy` 各组样本数（定位退化用）
    - `table`    分组明细

    ⚠️ **退化必须优先处理**：`rolling_pct` 作用在**单调趋势**的序列上会退化为
    恒 0 或恒 1（`base.py` 已记录该数学必然），使因子塌缩到单一分组。
    此时 `ic` 看起来可能很显著，但那是**伪影不是信号**——必须先修因子
    （例如改用「比价的变动」而非「比价的水平」），再谈方向。

    ⚠️ **不要**把 `spread` / `hit` 当统计显著性：horizon > 1 时样本高度重叠
    （同一段未来收益被反复计入），有效样本数远小于 `n`。这里的用途是
    **方向性否证**——如果连方向都不对，就不必谈显著性。
    """
    tbl = bucket_table(factor, fwd, n_buckets)
    ic = spearman_ic(factor, fwd)
    occ = tbl["n"].fillna(0) if len(tbl) else pd.Series(dtype=float)
    degenerate = bool(len(occ) and (occ == 0).any())
    means = tbl["mean"].dropna()
    diffs = means.diff().dropna()
    mono = float((diffs < 0).mean()) if len(diffs) else np.nan
    spread = (float(means.iloc[0] - means.iloc[-1])
              if len(means) == n_buckets else np.nan)

    df = pd.concat([factor.rename("f"), fwd.rename("r")], axis=1).dropna()
    hit = np.nan
    if not df.empty:
        b = np.clip((df["f"] * n_buckets).astype(int), 0, n_buckets - 1)
        lo = df["r"][b == 0].to_numpy()
        hi = df["r"][b == n_buckets - 1].to_numpy()
        if len(lo) and len(hi):
            hit = float((lo[:, None] > hi[None, :]).mean())

    return {"ic": ic, "mono": mono, "spread": spread, "hit": hit,
            "n": int(len(df)), "degenerate": degenerate, "occupancy": occ,
            "table": tbl}
