# -*- coding: utf-8 -*-
"""C1 信用维度：BAA10Y 信用利差因子（MT-76 ②）。

【为什么用信用利差】
情绪类因子（put-call / VIX / FGI）测的是「**当下恐慌**」；
BAA10Y 测的是「**融资条件收紧**」—— 是股权下跌的**领先**变量，与情绪维度**正交**。

【🔴 核心纪律：发布滞后 ⇒ 只认 `available_date`】

BAA10Y 是**有发布延迟**的宏观序列（实测 T+1，跨周末 3~4 天）。
若按 `date`（观测日）对齐：

    2026-10-01 的观测值，实际 10-05 才发布
    ⇒ 在 10-01 就「看到」了 10-05 才有的数据
    ⇒ IC 会**虚高** ✗（典型 lookahead）

⇒ 本模块**只认 `available_date`**：

- 取数必须 `merge_asof(direction="backward", on="available_date")` ✓
- **禁止** `reindex().ffill()` ✗ —— 那会跨越 `available_date` 把未来值提前
- `available_date` 缺失 ⇒ **直接抛错** ✗，不猜

【方向】
信用利差**走阔** = 融资紧 = 风险大 = **恐惧** ⇒
`baa10y_score()` 用 `reverse=True` ⇒ 高分 = 贪婪 ✓（与系统 0~100 口径一致）。

【文件命名】
🔴 数据文件带 `_avail` 后缀（`fred_baa10y_avail.csv`）——
裸名 `fred_baa10y.csv` 会与 H-065 主口径的 `fred_BAA10Y.csv`
在 APFS（大小写不敏感）上撞名 ✗。
"""
import os

import pandas as pd

from fg_system import config
from fg_system.factors.base import pct_score, rolling_pct

#: 必需列（缺一即抛错 ✗）
REQUIRED = ("date", "value", "available_date")

#: 默认数据文件（🔴 `_avail` 后缀，勿改成裸名）
DEFAULT_FILE = "fred_baa10y_avail.csv"


def load(path=None):
    """读 `fred_baa10y_avail.csv` ⇒ `DataFrame[date, value, available_date]` ✓。

    **缺列直接抛 `ValueError`** ✗ —— 不猜、不用 `date` 兜底（那正是 lookahead 的来源 ✗）。
    """
    p = path or os.path.join(config.DATA_DIR, "raw", DEFAULT_FILE)
    if not os.path.exists(p):
        raise FileNotFoundError(
            "信用利差数据不存在：%s\n"
            "⇒ 真实 CSV 只在 Mac 本地（不入库 ✓）；Windows 侧请显式传入 `df` 或用合成样本 ✓"
            % p)
    df = pd.read_csv(p, encoding="utf-8")
    miss = [c for c in REQUIRED if c not in df.columns]
    if miss:
        raise ValueError("信用利差数据缺列：%s（需要 date/value/available_date）✗"
                         % miss)
    d = df.copy()
    for c in ("date", "available_date"):
        d[c] = pd.to_datetime(d[c], errors="coerce")
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d = d.dropna(subset=list(REQUIRED))
    return d.sort_values("available_date").reset_index(drop=True)


def align_to(df, target_index, lag_days=0):
    """把信用利差按 **`available_date`** 对齐到 `target_index`（通常是交易日 ✓）。

    🔴 **只用 `merge_asof(direction="backward")`** ✓：
    t 日只能看到 `available_date <= t` 的**最新**值 ✓。

    `lag_days`：额外保守滞后（默认 0 ✓）—— 给「发布日仍不确定」留余量。

    **禁止** `reindex().ffill()` ✗：它不看 `available_date`，
    会把「t+5 才发布」的值一路前填到 t ✗ ⇒ 就是 lookahead ✗。

    :returns: `Series`（index = `target_index` 升序 ✓，列名 `baa10y` ✓）
    """
    if df is None or len(df) == 0:
        return pd.Series(dtype=float, name="baa10y")
    right = df[["available_date", "value"]].copy()
    right["available_date"] = pd.to_datetime(right["available_date"])
    if lag_days:
        right["available_date"] = (right["available_date"]
                                   + pd.Timedelta(days=int(lag_days)))
    right = right.sort_values("available_date").reset_index(drop=True)

    left = pd.DataFrame({"t": pd.to_datetime(pd.Index(target_index))})
    left = left.sort_values("t").reset_index(drop=True)

    out = pd.merge_asof(left, right, left_on="t", right_on="available_date",
                        direction="backward", allow_exact_matches=True)
    return out.set_index("t")["value"].rename("baa10y")


def baa10y_level(df=None, target_index=None, lag_days=0):
    """BAA10Y **原值** ✓（按 `available_date` 对齐 ✓）。

    - `df=None` ⇒ 从 `Data/raw/fred_baa10y_avail.csv` 读 ✓
    - `target_index=None` ⇒ 直接以 `available_date` 为索引返回 ✓（原始序列）
    """
    d = load() if df is None else df
    if target_index is None:
        return (d.set_index("available_date")["value"]
                .sort_index().rename("baa10y"))
    return align_to(d, target_index, lag_days=lag_days)


def baa10y_zscore(df=None, target_index=None, window=None, lag_days=0):
    """BAA10Y **滚动分位** ✓（0~1，高分 = 利差宽 = 融资紧 = **恐惧** ✓）。

    窗口走 `base.rolling_pct` 的默认值（`config.RANK_WINDOW` ✓），
    **与现有因子一致** ✓ —— 不另设窗口 ✗。

    窗口不足处为 `NaN` ✓（禁止用不足窗口的数据凑值 ✗）。
    """
    lvl = baa10y_level(df, target_index, lag_days=lag_days)
    return rolling_pct(lvl, window).rename("baa10y_z")


def baa10y_score(df=None, target_index=None, window=None, lag_days=0):
    """0~100 情绪分 ✓（**高分 = 贪婪** ✓）。

    信用利差是**逆向**指标 ⇒ `reverse=True` ✓：
    利差越宽 ⇒ 分越低（恐惧）✓。
    """
    lvl = baa10y_level(df, target_index, lag_days=lag_days)
    return pct_score(lvl, window, reverse=True).rename("baa10y_score")
