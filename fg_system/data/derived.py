# -*- coding: utf-8 -*-
"""从 `positions.csv` **派生**未实现盈亏（逐标的 / 逐日 / 账户级）。

【为什么需要】
`accounts.csv` 的 `unrealized_pnl` 来自富途 `accinfo_query` 的 `unrealized_pl` ✗ ——
该字段在**部分 FutuOpenD 版本不存在** ✓ ⇒ `r.get(..., 0)` 会**静默写 0.0** ✗
（WT-43 已把**写入侧**改成自算 ✓，但**历史行未订正** ✗，且**逐标的**浮亏从来没算过 ✗）。

而 `positions.csv` 有 `qty` / `price` / `cost` ✓ ⇒ **未实现盈亏可完全自算** ✓：

    unrealized = qty × (price − cost)

⇒ 2026-10-21 实测：本机 09-22 快照自算合计 **−1033.40** ✓ —— 正是 **H-004** 引用的那个数 ✓
⇒ 说明这条派生口径**与项目历史口径一致** ✓。

【给谁用】
- **11 条假说**依赖浮亏 ✗（`H-011/016/017/018/022/038/040` + `verifying` 的
  `H-001/006/008/009`）⇒ 用本模块取数 ✓，**不要再读 `accounts.unrealized_pnl`** ✗。
- `scripts/derive_unrealized.py` 是它的命令行入口 ✓（含与 `accounts.csv` 的**审计** ✓）。
"""
import pandas as pd

#: 计算所需列 ✓（缺任一列 ⇒ 无法派生 ✗）
REQUIRED = ("date", "symbol", "qty", "price", "cost")


def available(positions):
    """`positions` 是否具备派生所需的列 ✓。"""
    return positions is not None and set(REQUIRED) <= set(positions.columns)


def unrealized(positions):
    """逐行加一列 `unrealized` ✓ = `qty × (price − cost)`（保留 2 位 ✓）。

    :returns: 新 DataFrame（**不修改入参** ✓）；缺列 ⇒ 抛 `ValueError` ✗
    """
    if not available(positions):
        raise ValueError("positions 缺少列：%s"
                         % (set(REQUIRED) - set(positions.columns or ())))
    out = positions.copy()
    qty = pd.to_numeric(out["qty"], errors="coerce")
    price = pd.to_numeric(out["price"], errors="coerce")
    cost = pd.to_numeric(out["cost"], errors="coerce")
    out["unrealized"] = (qty * (price - cost)).round(2)
    return out


def by_symbol(positions, date=None):
    """**逐标的**浮亏 ✓（`date` 为 `None` ⇒ 取最后一日 ✓）。

    :returns: `DataFrame[date, symbol, qty, price, cost, unrealized]` ✓
    """
    d = unrealized(positions)
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    if date is None:
        date = d["date"].max()
    keep = ["date", "symbol", "qty", "price", "cost", "unrealized"]
    return d[d["date"] == date][keep].reset_index(drop=True)


def daily(positions):
    """**按日**汇总 ✓（`date` + `unrealized` + `n_symbols` ✓）。"""
    d = unrealized(positions)
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    g = d.groupby("date", as_index=False).agg(
        unrealized=("unrealized", "sum"), n_symbols=("symbol", "nunique"))
    g["unrealized"] = g["unrealized"].round(2)
    return g.sort_values("date").reset_index(drop=True)


def audit_accounts(accounts, positions, tol=0.5):
    """**审计** `accounts.unrealized_pnl` 与自算值是否一致 ✓。

    :returns: `DataFrame[date, reported, derived, diff, ok]` ✓
              —— `ok=False` 的行就是**数据源可疑**的行 ✗（典型：`reported == 0.0` ✗）
    """
    if accounts is None or "unrealized_pnl" not in accounts.columns:
        return pd.DataFrame(columns=["date", "reported", "derived", "diff", "ok"])
    a = accounts.copy()
    a["date"] = pd.to_datetime(a["date"]).dt.strftime("%Y-%m-%d")
    rep = a.groupby("date", as_index=False)["unrealized_pnl"].sum()
    rep["reported"] = pd.to_numeric(rep["unrealized_pnl"], errors="coerce").round(2)
    out = rep[["date", "reported"]].merge(daily(positions), on="date", how="outer")
    out["derived"] = out["unrealized"].fillna(0.0).round(2)
    out["diff"] = (out["reported"].fillna(0.0) - out["derived"]).round(2)
    out["ok"] = out["diff"].abs() <= tol
    return out[["date", "reported", "derived", "diff", "ok"]].sort_values("date") \
        .reset_index(drop=True)
