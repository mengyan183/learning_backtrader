#!/usr/bin/env python3
"""fetch_trades_futu：从富途 FutuOpenD 拉全量美股成交流水，落盘 Data/trade_log_futu.csv。

MT-62（2026-10-23）：验证 history_deal_list_query 可用性后的正式落地。
背景：derive_trades.py 反推有盲区（同日买卖相抵/缺日累积/退市标的查不到时间），
富途流水是券商侧权威记录，能直接补齐「卖出没记录」的问题。

纪律（任务书）：
- 成交明细属账户隐私 ⇒ 只在 Mac 本地落盘，绝不进 sync_* 包（pack_many 已拒 Data/）。
- 输出字段：date, account, symbol, action, quantity, price, fee
  （futu deals 无 fee 列 ⇒ fee 留空，不编造）。
- 不覆盖手工 Data/trade_log.csv。

已知限制（2026-10-23 实测）：
- 单次查询跨度 ≤360 天（报错「单次查询的时间跨度不能超过 360 天」）⇒ 按月分段。
- 模拟账户（trd_env=SIMULATE）报「模拟交易不支持成交数据」⇒ 只拉 REAL。
- 部分交易日在券商侧可能延迟（9-10 月实测 0 笔，与 positions 快照存在差异）⇒
  对账差异如实上报，不强行对齐。

用法：
    .venv/bin/python scripts/fetch_trades_futu.py            # 拉全量并落盘
    .venv/bin/python scripts/fetch_trades_futu.py --quiet    # 只输出汇总一行
"""
import argparse
import datetime as dt
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

try:                                   # noqa: E402
    import futu                        # noqa: E402
except ImportError:
    futu = None

from fg_system import config  # noqa: E402

OUT = os.path.join(config.DATA_DIR, "trade_log_futu.csv")
START = dt.date(2025, 1, 1)          # 富途历史成交最早只到 2025-01-29 附近，早于此无数据
SEG_DAYS = 90                        # 分段 ≤360 天跨度限制；3 个月一段减少查询次数
RATE_LIMIT_SEC = 3.2                 # 富途限流：每 30 秒最多 10 次 ⇒ 每次 ≥3.0s
MAX_RETRY = 3


def _iter_ranges(start, end):
    """按 SEG_DAYS 切分 [start, end]，每段 ≤90 天。"""
    cur = start
    while cur <= end:
        seg_end = min(cur + dt.timedelta(days=SEG_DAYS - 1), end)
        yield cur.isoformat(), seg_end.isoformat()
        cur = seg_end + dt.timedelta(days=1)


def _query_retry(ctx, **kw):
    """带限速与重试的查询：频率错误时等待 30s 再试（最多 MAX_RETRY 次）。"""
    import time
    for attempt in range(1, MAX_RETRY + 1):
        time.sleep(RATE_LIMIT_SEC)     # 恒定节流，从源头避免触发限流
        ret, deals = ctx.history_deal_list_query(**kw)
        if ret == futu.RET_OK:
            return ret, deals
        msg = str(deals)
        if "频率太高" in msg or "frequency" in msg.lower():
            if attempt < MAX_RETRY:
                time.sleep(28)          # 已触发限流 ⇒ 补一次 30s 窗口
                continue
        return ret, deals
    return ret, deals


def fetch_all():
    """拉全部 REAL 账户成交流水，返回 DataFrame[date,account,symbol,action,quantity,price,fee]。
    """
    if futu is None:
        print("[futu] 未安装 futu-api，跳过（pip install futu-api）")
        return pd.DataFrame(columns=["date", "account", "symbol", "action",
                                     "quantity", "price", "fee"])
    ctx = futu.OpenSecTradeContext(filter_trdmarket=futu.TrdMarket.US,
                                   host="127.0.0.1", port=11111,
                                   security_firm=futu.SecurityFirm.FUTUSECURITIES)
    rows = []
    try:
        ret, accs = ctx.get_acc_list()
        if ret != futu.RET_OK:
            print(f"[futu] get_acc_list 失败: {accs}")
            return pd.DataFrame(columns=["date", "account", "symbol", "action",
                                         "quantity", "price", "fee"])
        today = dt.date.today()
        for _, a in accs.iterrows():
            acc_id = a["acc_id"]
            if a.get("trd_env", "REAL") != "REAL":
                continue                     # 模拟账户不支持成交数据
            for s, e in _iter_ranges(START, today):
                ret, deals = _query_retry(
                    ctx, start=s, end=e, acc_id=acc_id,
                    trd_env="REAL", deal_market="US")
                if ret != futu.RET_OK:
                    print(f"[futu] acc {acc_id} {s}~{e} 查询失败: {str(deals)[:120]}")
                    continue
                if deals is None or deals.empty:
                    continue
                sub = pd.DataFrame({
                    "date": pd.to_datetime(deals["create_time"]).dt.strftime("%Y-%m-%d"),
                    "account": acc_id,
                    "symbol": deals["code"].str.replace("^US\\.", "", regex=True),
                    "action": deals["trd_side"].str.lower(),
                    "quantity": deals["qty"],
                    "price": deals["price"],
                    "fee": "",               # futu deals 无 fee 列，留空不编造
                })
                rows.append(sub)
    finally:
        ctx.close()
    if not rows:
        return pd.DataFrame(columns=["date", "account", "symbol", "action",
                                     "quantity", "price", "fee"])
    out = pd.concat(rows, ignore_index=True)
    out = out.drop_duplicates()              # 月度边界重叠去重（理论上不会）
    out = out.sort_values(["date", "account"]).reset_index(drop=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只输出汇总一行")
    args = ap.parse_args()
    df = fetch_all()
    if df.empty:
        print("[futu] 无成交数据（连接失败或账户无成交）")
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, index=False)
    n = len(df)
    buys = int((df["action"] == "buy").sum())
    sells = int((df["action"] == "sell").sum())
    syms = len(df["symbol"].unique())
    print(f"✅ 已写 {OUT}（{n} 笔：buy {buys} / sell {sells}，标的 {syms} 个）")
    if not args.quiet:
        print(df.tail(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
