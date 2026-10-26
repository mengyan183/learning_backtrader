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

【asset_type（MT-75 ✓）】
每行透传 `asset_type`（`stock` / `option` ✓）✓ —— 期权 1 张=100 股 ✗，
下游统计/浮亏**必须按类型分流** ✗，本视图只负责把类型列带出来 ✗。

【用法】
    py -3.10 scripts/merge_trades.py                 # 打印合并结果
    py -3.10 scripts/merge_trades.py --write         # 写 trade_log_merged.csv
    py -3.10 scripts/merge_trades.py --audit         # 与 derived 对账 ✗
    py -3.10 scripts/merge_trades.py --audit --alert  # 待查非零 ⇒ 飞书告警 + 退出码1 ✗
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
from fg_system.data import asset_type                      # noqa: E402

#: 源文件与优先级（**数字小 = 权威** ✓）
SOURCES = (
    ("futu", "trade_log_futu.csv", 1),
    ("manual", "trade_log.csv", 2),
)
#: 仅用于对账 ✗，**不参与合并** ✗
DERIVED = "trade_log_derived.csv"

#: 公司行动清单（MT-65 ✓）：`Data/raw/splits.csv`（`symbol,date,ratio,source,verified`）✓。
#: 不再硬编码具体合股 ✓ —— 由 `fetch_corporate_actions.py`（yfinance，verified=0）
#: 与人工核实（manual，verified=1）共同维护 ✓。
SPLITS_CSV = os.path.join("raw", "splits.csv")
#: 合股日前后 ±N 个工作日内出现的「反推有、合并无」视为邻近公司行动 ✓
SPLIT_WINDOW_BD = 3


def load_splits(path=None):
    """读公司行动清单；文件缺失/为空 ⇒ 空表 ✓（不阻断对账 ✗）。"""
    p = path or os.path.join(config.DATA_DIR, SPLITS_CSV)
    if not os.path.exists(p):
        return pd.DataFrame(columns=["symbol", "date", "ratio", "source", "verified"])
    df = pd.read_csv(p, dtype=str)
    for c in ("symbol", "date", "ratio", "source", "verified"):
        if c not in df.columns:
            df[c] = None
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["verified"] = pd.to_numeric(df["verified"], errors="coerce").fillna(0).astype(int)
    return df[["symbol", "date", "ratio", "source", "verified"]]


def _nearby_split(miss_date, symbol, splits):
    """在清单里找同 symbol、日期 ±SPLIT_WINDOW_BD 工作日内的 split 行 ✓。

    :returns: 匹配行（verified 最大者优先），无匹配 ⇒ None ✓
    """
    sub = splits[splits["symbol"] == symbol]
    if sub.empty:
        return None
    md = pd.Timestamp(miss_date)
    best = None
    for _, row in sub.iterrows():
        try:
            sd = pd.Timestamp(row["date"])
        except (ValueError, TypeError):
            continue
        # ±N 工作日窗口（bdate_range 含端点 ✓）
        window = pd.bdate_range(sd - pd.Timedelta(days=SPLIT_WINDOW_BD * 2 + 1),
                                 sd + pd.Timedelta(days=SPLIT_WINDOW_BD * 2 + 1))
        if md.normalize() in [d.normalize() for d in window]:
            if best is None or int(row["verified"]) > int(best["verified"]):
                best = row
    return best


def classify_miss(miss_keys, splits=None):
    """把「反推有、合并无」分成三类 ✓（MT-65 ✓）。

    :param miss_keys: `date|SYMBOL|action` 可迭代 ✓
    :param splits: `load_splits()` 结果（可注入，便于测试 ✓）
    :returns: `(exempt, advisory, pending)` 三个 key 列表 ✓
        - **exempt**：verified=1 邻近 split ⇒ 自动豁免（人工已核实公司行动 ✓）
        - **advisory**：verified=0 邻近 split ⇒ **只提示**（yfinance 未核实 ✗，
          不静默豁免 ✗、也不当漏单告警 ✗）
        - **pending**：清单无匹配 ⇒ 真疑似券商漏单 ✗（告警 ✓）
    """
    if splits is None:
        splits = load_splits()
    exempt, advisory, pending = [], [], []
    for key in miss_keys:
        parts = key.split("|")
        if len(parts) < 3:
            pending.append(key)
            continue
        date, symbol, _action = parts[0], parts[1].upper(), parts[2]
        hit = _nearby_split(date, symbol, splits)
        if hit is None:
            pending.append(key)
        elif int(hit["verified"]) == 1:
            exempt.append(key)
        else:
            advisory.append(key)  # verified=0 未核实 ⇒ 仅提示 ✗
    return sorted(exempt), sorted(advisory), sorted(pending)

COLUMNS = ["date", "symbol", "action", "quantity", "price",
           "asset_type", "source"]


def _load(name):
    p = os.path.join(config.DATA_DIR, name)
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, dtype={"symbol": str})


def _norm(df, source):
    """统一列名与格式 ✓（缺列补 `None` ✗）；并打 `asset_type` ✓。"""
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    d["symbol"] = d["symbol"].astype(str).str.upper()
    d["action"] = d["action"].astype(str).str.lower()
    if "quantity" not in d.columns:
        d["quantity"] = None
    if "price" not in d.columns:
        d["price"] = None
    d["source"] = source
    # 🔴 MT-75：期权 1 张=100 股 ✗ ⇒ 下游统计/浮亏必须按 asset_type 分流 ✗
    d = asset_type.classify_df(d)
    return d[COLUMNS]


def merge(futu=None, manual=None):
    """合并 `futu` + `manual` ✓（**同 key 取 futu** ✗）。

    :returns: `DataFrame[date, symbol, action, quantity, price, asset_type, source]` ✓
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
                          "source": g["source"].iloc[0],
                          # 🔴 必须透传 ✓ —— groupby 后只剩 `_agg` 回传的列 ✓
                          "asset_type": g["asset_type"].iloc[0]})

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
    ap.add_argument("--alert", action="store_true",
                    help="待查（反推有、合并无且非公司行动）非零 ⇒ 推飞书并以退出码 1 结束 ✗")
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

    pending = []
    if args.audit:
        der = _load(DERIVED)
        print("\n=== 与反推（%s）对账 ✗ ===" % DERIVED)
        if der is None:
            print("  ⚠️ 反推文件不存在 ✗ ⇒ 先跑 `derive_trades.py --write` ✓")
        else:
            d = _norm(der, "derived")
            k1 = set(out["date"] + "|" + out["symbol"] + "|" + out["action"])
            k2 = set(d["date"] + "|" + d["symbol"] + "|" + d["action"])
            miss = k2 - k1
            # MT-65 ✓：读 splits.csv 分类 —— verified=1 豁免 / verified=0 仅提示 /
            # 无匹配才是疑似漏单 ✗（不再硬编码具体合股 ✓）
            exempt, advisory, pending = classify_miss(miss, load_splits())
            print("  合并 %d 笔 ｜ 反推 %d 笔" % (len(out), len(d)))
            print("  🔴 合并有、反推无：%d 笔 ✓（正常 ✓ —— 同日买卖相抵 ✗）"
                  % len(k1 - k2))
            print("  🟡 反推有、合并无：%d 笔（待查 %d / 已豁免 %d / 未核实提示 %d）"
                  % (len(miss), len(pending), len(exempt), len(advisory)))
            for k in exempt:
                print("     ✓ 已豁免（verified=1 公司行动，非交易）%s" % k)
            for k in advisory:
                print("     🟠 未核实（yfinance verified=0，仅提示不豁免）%s" % k)
            for k in pending[:20]:
                print("     ✗ %s" % k)

    if args.alert and pending:
        try:
            from scripts.invest_research import push_feishu
            push_feishu(
                "⚠️ [成交对账 MT-63] 反推有、合并无 %d 笔 ✗（疑似券商流水漏单 ✗）：\n"
                % len(pending) + "\n".join("  • " + k for k in pending[:20]))
            print("\n🔔 已就 %d 笔待查向飞书告警 ✓" % len(pending))
        except Exception as e:  # 告警失败不阻断合并写盘 ✗
            print("  ⚠️ 飞书告警发送失败：%s" % e)
        return 1

    if args.write:
        p = os.path.join(config.DATA_DIR, "trade_log_merged.csv")
        out.to_csv(p, index=False, encoding="utf-8")
        print("\n✅ 已写 %s（**原始三表只读** ✓）" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
