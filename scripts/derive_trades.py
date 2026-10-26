#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 `positions.csv` **每日持仓快照**反推成交流水，并与 `trade_log.csv` 对账。

【为什么需要】
`Data/trade_log.csv` 是**手工维护**的 ✗ —— 实测 2026-10-23：
- 26 笔**全是 `buy`** ✓，`sell` 记录 **0** 笔 ✗
- 但 `DPST` / `RKLX` / `SOXL` / `TQQQ` **买过却不在持仓** ✗ ⇒ **卖过，但没记** ✗

⇒ 于是「当时为什么卖、卖了多少、`fg_index` 多少」**全部丢失** ✗
⇒ 卖出这件事**没有可复盘的素材** ✗ ⇒ 这正是「学不会卖」的**结构性原因** ✗。

【原理】
`positions.csv` 每天记录当时持仓 ✓ ⇒ 按 `symbol` 逐日比 `qty` ✗：

    今日 qty − 昨日 qty > 0  ⇒ buy（增量 ✓）
    今日 qty − 昨日 qty < 0  ⇒ sell（减量 ✓）
    昨日有、今日无            ⇒ sell（全量清仓 ✓，qty 记为昨日持仓 ✓）

⚠️ **盲区**（必须知道 ✗）：若某天**同时买 A 又卖 A** ✓，净变化为 0 ✗
⇒ **反推不出来** ✗ ⇒ 这类只能靠 `trade_log` 手工补 ✓。

【用法】
    py -3.10 scripts/derive_trades.py                 # 打印反推流水
    py -3.10 scripts/derive_trades.py --audit         # 与 trade_log 对账 ✗
    py -3.10 scripts/derive_trades.py --write         # 写 Data/trade_log_derived.csv
    py -3.10 scripts/derive_trades.py --json          # 机器可读
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

#: 反推所需列 ✓
REQUIRED = ("date", "symbol", "qty")

#: 数量容差 ✓（浮点与碎股 ✓）
QTY_TOL = 1e-9


def _load(name):
    p = os.path.join(config.DATA_DIR, name)
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, dtype={"symbol": str})


def derive(positions):
    """按 `symbol` 逐日比 `qty` 反推成交流水 ✓。

    :returns: `DataFrame[date, symbol, action, quantity, price]` ✓（按日期升序 ✓）
    """
    if positions is None or positions.empty:
        return pd.DataFrame(columns=["date", "symbol", "action",
                                     "quantity", "price"])
    missing = set(REQUIRED) - set(positions.columns)
    if missing:
        raise ValueError("positions 缺少列：%s" % missing)

    d = positions.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    d["qty"] = pd.to_numeric(d["qty"], errors="coerce").fillna(0.0)
    # 同一天同标的可能多行（多账户 ✓）⇒ 先按日汇总 ✓
    agg = d.groupby(["date", "symbol"], as_index=False).agg(
        qty=("qty", "sum"),
        price=("price", "last") if "price" in d.columns else ("qty", "size"))

    dates = sorted(agg["date"].unique())
    syms = sorted(agg["symbol"].unique())
    wide = (agg.pivot(index="date", columns="symbol", values="qty")
            .reindex(index=dates, columns=syms).fillna(0.0))   # 缺失 = 无持仓 ✓
    px = (agg.pivot(index="date", columns="symbol", values="price")
          .reindex(index=dates, columns=syms)) if "price" in agg.columns else None

    rows = []
    # 🔴 **首日只作基准** ✗（2026-10-23 实测：本地只有 1 天快照 ✓，
    # 若把首日持仓当成「首次买入」✗ ⇒ 会报出大量**假成交** ✗）
    prev = wide.loc[dates[0]].copy()
    for dt in dates[1:]:
        cur = wide.loc[dt]
        delta = cur - prev
        for sym in syms:
            dv = float(delta.get(sym, 0.0))
            if abs(dv) <= QTY_TOL:
                continue
            rows.append({
                "date": dt,
                "symbol": sym,
                "action": "buy" if dv > 0 else "sell",
                "quantity": round(abs(dv), 8),
                # 🔴 清仓当日快照里已没有该标的 ⇒ 价格记为 `None` ✗
                # （**不要**用昨日价冒充成交价 ✓ —— 那会造出一个不存在的数字 ✗）
                "price": (float(px.loc[dt, sym])
                          if px is not None and pd.notna(px.loc[dt, sym])
                          else None),
            })
        prev = cur
    return pd.DataFrame(rows, columns=["date", "symbol", "action",
                                       "quantity", "price"])


def audit(derived, logged, tol=1e-6):
    """与 `trade_log` 对账 ✓：找出「有成交但没记录」与「有记录但没成交」✗。

    :returns: `(unlogged, unmatched)` ✓
              `unlogged` = 反推出但 `trade_log` 无对应行 ✗
              `unmatched` = `trade_log` 有但反推不出 ✗（多为「同日买卖相抵」✓）
    """
    if logged is None or logged.empty:
        return derived.copy(), pd.DataFrame()
    lg = logged.copy()
    lg["date"] = pd.to_datetime(lg["date"]).dt.strftime("%Y-%m-%d")
    lg["key"] = lg["date"] + "|" + lg["symbol"].str.upper() + "|" + lg["action"]
    dr = derived.copy()
    dr["key"] = dr["date"] + "|" + dr["symbol"].str.upper() + "|" + dr["action"]
    unlogged = dr[~dr["key"].isin(set(lg["key"]))].drop(columns=["key"])
    unmatched = lg[~lg["key"].isin(set(dr["key"]))].drop(columns=["key"])
    return unlogged.reset_index(drop=True), unmatched.reset_index(drop=True)


def reconcile(derived=None):
    """MT-72②：反推 vs **权威合并视图**(futu>manual，derived 不参与) 双向比对 ✓。

    只打印差异清单（标的/日期/数量），**不写入、不自动补、不发告警** ✗。
    - 反推有、合并无 ⇒ 经 `merge_trades.classify_miss` 分 exempt/advisory/pending
      （verified=1 公司行动豁免 / verified=0 未核实提示 / 无匹配=疑似漏单待人工）✓
    - 合并有、反推无 ⇒ 正常（快照盲区/同日买卖相抵）✓，仅计数不列全 ✓
    """
    import importlib.util
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "merge_trades", os.path.join(here, "scripts", "merge_trades.py"))
    mt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mt)

    futu = _load("trade_log_futu.csv")
    manual = _load("trade_log.csv")
    merged = mt.merge(futu, manual)

    dr = derived if derived is not None else pd.DataFrame(
        columns=["date", "symbol", "action", "quantity", "price"])
    mkey = set(merged["date"] + "|" + merged["symbol"].str.upper()
               + "|" + merged["action"])
    d = dr.copy()
    d["key"] = (pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d") + "|"
                + d["symbol"].str.upper() + "|" + d["action"])
    der_keys = set(d["key"])
    miss = sorted(der_keys - mkey)
    extra = sorted(mkey - der_keys)
    exempt, advisory, pending = mt.classify_miss(miss)

    print("=== MT-72 reconcile：反推 vs 权威合并(futu>manual) ===")
    print("  合并 %d 笔 ｜ 反推 %d 笔" % (len(merged), len(dr)))
    print("  🟡 反推有、合并无：%d（豁免 %d / 未核实提示 %d / 待人工 %d）"
          % (len(miss), len(exempt), len(advisory), len(pending)))
    for k in exempt:
        print("     ✓ 已豁免(verified=1 公司行动) %s" % k)
    for k in advisory:
        print("     🟠 未核实(verified=0 仅提示) %s" % k)
    for k in pending:
        row = d[d["key"] == k].iloc[0]
        print("     ✗ 待人工确认 %s 数量=%s（不自动补 ✗）" % (k, row.get("quantity")))
    print("  🔵 合并有、反推无：%d 笔（正常：快照盲区/同日相抵 ✓，不列全）" % len(extra))
    return pending


def main(argv=None):
    ap = argparse.ArgumentParser(description="从持仓快照反推成交流水（不依赖手工记录 ✓）")
    ap.add_argument("--audit", action="store_true", help="与 trade_log 对账 ✗")
    ap.add_argument("--reconcile", action="store_true",
                    help="MT-72②：与**权威合并视图**(futu>manual)双向比对，输出差异"
                         "清单，只告警不写入 ✗")
    ap.add_argument("--write", action="store_true",
                    help="写 Data/trade_log_derived.csv（不覆盖 trade_log ✓）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args(argv)

    # MT-72② reconcile 独立分支：只对权威合并视图出差异清单，不依赖快照非空 ✓
    if args.reconcile:
        pos = _load("positions.csv")
        dr = derive(pos) if pos is not None and not pos.empty else None
        reconcile(dr)
        return 0

    pos = _load("positions.csv")
    if pos is None or pos.empty:
        sys.exit("❌ Data/positions.csv 不存在或为空 ✗（本机可能是旧快照 ✓）")

    dr = derive(pos)
    n_days = pos["date"].nunique()
    if dr.empty:
        print("⚠️ 反推出 0 笔成交 ✓")
        print("   快照天数 = %d ⇒ %s"
              % (n_days, "**只有 1 天，无从比较** ✗（首日只作基准 ✓）"
                 if n_days <= 1 else "持仓全程未变 ✓（这本身是个结论 ✓）"))
        return 0

    if args.json:
        print(json.dumps(dr.to_dict("records"), ensure_ascii=False, default=str))
        return 0

    print("反推成交 %d 笔（%s → %s）"
          % (len(dr), dr["date"].min(), dr["date"].max()))
    print("%-12s %-8s %-5s %12s" % ("日期", "标的", "方向", "数量"))
    for _, r in dr.iterrows():
        print("%-12s %-8s %-5s %12.6g"
              % (r["date"], r["symbol"], r["action"], r["quantity"]))

    if args.audit:
        logged = _load("trade_log.csv")
        unlogged, unmatched = audit(dr, logged)
        print("\n=== 与 trade_log 对账 ===")
        print("  trade_log 记录 %d 笔"
              % (0 if logged is None else len(logged)))
        print("  🔴 有成交但**没记录**：%d 笔 ✗" % len(unlogged))
        for _, r in unlogged.iterrows():
            print("     %-12s %-8s %-5s %12.6g"
                  % (r["date"], r["symbol"], r["action"], r["quantity"]))
        print("  🟡 有记录但反推不出：%d 笔（多为同日买卖相抵 ✓）"
              % len(unmatched))
        for _, r in unmatched.iterrows():
            print("     %-12s %-8s %-5s"
                  % (r["date"], r["symbol"], r.get("action", "")))

    if args.write:
        out = os.path.join(config.DATA_DIR, "trade_log_derived.csv")
        dr.to_csv(out, index=False, encoding="utf-8")
        print("\n✅ 已写 %s（**不覆盖** trade_log.csv ✓）" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
