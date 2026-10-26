#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并三个成交流水源，输出**只读**的统一视图（**永不覆盖原始表** ✗）。

【三个源与优先级】（用户 2026-10-26 拍板 ✓）

| 优先级 | 文件 | 角色 |
|---|---|---|
| **1（权威 ✓）** | `Data/trade_log_futu.csv` | **券商流水** ✓（`history_deal_list_query` ✓）|
| **2（补充 ✓）** | `Data/trade_log.csv` | **手工** ✓（富途拿不到的账户 ✓）|
| **3（校验 ✗）** | `Data/trade_log_derived.csv` | **快照反推** ✗ —— **只用于对账**，不参与合并 ✗ |

⇒ 输出 `Data/trade_log_merged.csv` ✓，每行带 `source`（`futu` / `manual` ✓）。
⇒ 🔴 **三个原始文件一律只读** ✗ —— 本脚本**不写**它们 ✓。

【为什么 derived 不参与合并】
反推有已知盲区 ✗（同日买卖相抵 ✗、缺日累积 ✗、退市标的查不到时间 ✗）
⇒ 若让它参与合并 ✓，会把**推断**当成**事实** ✗ ⇒ 与 `MT-55`「假成功」同类 ✗。

【用法】
    py -3.10 scripts/merge_trades.py                 # 打印合并结果
    py -3.10 scripts/merge_trades.py --write         # 写 trade_log_merged.csv
    py -3.10 scripts/merge_trades.py --audit         # 与 derived 对账 ✗
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd                                        # noqa: E402

from fg_system import config                               # noqa: E402

#: 源文件与优先级（**数字小 = 权威** ✓）
SOURCES = (
    ("futu", "trade_log_futu.csv", 1),
    ("manual", "trade_log.csv", 2),
)
#: 仅用于对账 ✗，**不参与合并** ✗
DERIVED = "trade_log_derived.csv"

COLUMNS = ["date", "symbol", "action", "quantity", "price", "source"]


def _load(name):
    p = os.path.join(config.DATA_DIR, name)
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, dtype={"symbol": str})


def _norm(df, source):
    """统一列名与格式 ✓（缺列补 `None` ✗）。"""
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    d["symbol"] = d["symbol"].astype(str).str.upper()
    d["action"] = d["action"].astype(str).str.lower()
    if "quantity" not in d.columns:
        d["quantity"] = None
    if "price" not in d.columns:
        d["price"] = None
    d["source"] = source
    return d[COLUMNS]


def merge(futu=None, manual=None):
    """合并 `futu` + `manual` ✓（**同 key 取 futu** ✗）。

    :returns: `DataFrame[date, symbol, action, quantity, price, source]` ✓
    """
    frames = []
    if futu is not None and not futu.empty:
        frames.append(_norm(futu, "futu"))
    if manual is not None and not manual.empty:
        frames.append(_norm(manual, "manual"))
    if not frames:
        return pd.DataFrame(columns=COLUMNS)

    allrows = pd.concat(frames, ignore_index=True)
    allrows["_pri"] = allrows["source"].map({"futu": 1, "manual": 2}).fillna(9)
    allrows["_key"] = (allrows["date"] + "|" + allrows["symbol"] + "|"
                       + allrows["action"])
    # 🔴 **先按「源 + key」求和** ✗（2026-10-26 实测：`manual` 26 笔被去重成 22 笔 ✗
    # ⇒ **同一天同标的的分批买入数量丢了** ✗）
    # ⇒ 同源同 key 的 `quantity` **相加** ✓；价格取**加权均价** ✓
    def _agg(g):
        q = pd.to_numeric(g["quantity"], errors="coerce")
        pr = pd.to_numeric(g["price"], errors="coerce")
        tot = float(q.sum()) if q.notna().any() else None
        wavg = None
        if q.notna().any() and pr.notna().any():
            m = q.notna() & pr.notna()
            if m.any() and float(q[m].sum()) != 0:
                wavg = float((q[m] * pr[m]).sum() / q[m].sum())
        return pd.Series({"quantity": tot, "price": wavg,
                          "source": g["source"].iloc[0]})

    allrows = (allrows.groupby(["_key", "_pri"], as_index=False)
               .apply(_agg, include_groups=False)
               .reset_index())
    # 🔴 跨源同 key ⇒ 取**优先级最高**（数字最小 ✓）的那条 ✗（futu 覆盖 manual ✓）
    out = (allrows.sort_values("_pri").drop_duplicates("_key", keep="first")
           .drop(columns=["_pri"]))
    # 🔴 **把 `_key` 拆回三列** ✗（groupby 后 date/symbol/action 已不在 ✓）
    parts = out["_key"].str.split("|", n=2, expand=True)
    out["date"] = parts[0]
    out["symbol"] = parts[1]
    out["action"] = parts[2]
    out = out.drop(columns=["_key"])
    return out[COLUMNS].sort_values(["date", "symbol"]).reset_index(drop=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="合并成交流水（原始表只读 ✓）")
    ap.add_argument("--write", action="store_true",
                    help="写 Data/trade_log_merged.csv（**不覆盖**原始三表 ✓）")
    ap.add_argument("--audit", action="store_true", help="与反推结果对账 ✗")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args(argv)

    futu = _load("trade_log_futu.csv")
    manual = _load("trade_log.csv")
    if futu is None and manual is None:
        sys.exit("❌ 两个源都不存在 ✗（本机可能只有 manual ✓）")

    out = merge(futu, manual)
    if args.json:
        print(json.dumps(out.to_dict("records"), ensure_ascii=False, default=str))
        return 0

    print("合并 %d 笔（futu %d / manual %d）"
          % (len(out),
             0 if futu is None else len(futu),
             0 if manual is None else len(manual)))
    if not out.empty:
        print("  区间: %s → %s" % (out["date"].min(), out["date"].max()))
        print("  方向: buy %d / sell %d"
              % ((out["action"] == "buy").sum(),
                 (out["action"] == "sell").sum()))
        print("  来源: %s" % dict(out["source"].value_counts()))
    print("  🔴 futu 缺失 ⇒ 合并结果**不完整** ✗：%s"
          % ("是 ✗（券商流水没拉到 ✓）" if futu is None else "否 ✓"))

    if args.audit:
        der = _load(DERIVED)
        print("\n=== 与反推（%s）对账 ✗ ===" % DERIVED)
        if der is None:
            print("  ⚠️ 反推文件不存在 ✗ ⇒ 先跑 `derive_trades.py --write` ✓")
        else:
            d = _norm(der, "derived")
            k1 = set(out["date"] + "|" + out["symbol"] + "|" + out["action"])
            k2 = set(d["date"] + "|" + d["symbol"] + "|" + d["action"])
            print("  合并 %d 笔 ｜ 反推 %d 笔" % (len(out), len(d)))
            print("  🔴 合并有、反推无：%d 笔 ✓（正常 ✓ —— 同日买卖相抵 ✗）"
                  % len(k1 - k2))
            print("  🟡 反推有、合并无：%d 笔 ✗（**该查** ✗ —— 券商流水漏了 ✓）"
                  % len(k2 - k1))
            for k in sorted(k2 - k1)[:20]:
                print("     %s" % k)

    if args.write:
        p = os.path.join(config.DATA_DIR, "trade_log_merged.csv")
        out.to_csv(p, index=False, encoding="utf-8")
        print("\n✅ 已写 %s（**原始三表只读** ✓）" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
