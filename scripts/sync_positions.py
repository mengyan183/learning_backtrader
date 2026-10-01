# -*- coding: utf-8 -*-
"""账户/持仓快照同步 —— 实盘数据运行时生成，不入库（数据层改造）。

模式（环境变量 FG_SYNC_MODE，**默认 static**）：
  static : 不调用任何外部 API。**公司电脑安全默认**：仅检查现有快照并打印状态，
           绝不触碰 Data/accounts.csv 与 Data/positions.csv。
  live   : 从富途(FutuOpenD)与 OKX(REST)动态拉取，**追加当日快照行**（保留历史行）。

依赖：
  富途 : 本机已运行 FutuOpenD（默认 127.0.0.1:11111）+ 已开通 API 交易权限。
   OKX : ~/.okx_credentials.json（chmod 600，绝不入库）：
         {"api_key": "...", "secret": "...", "passphrase": "...",
          "proxy": "http://127.0.0.1:7890"}   # 国际站被墙时需要

用法：
  python scripts/sync_positions.py --check      # 查看当前快照状态（任何模式安全）
  FG_SYNC_MODE=static python scripts/sync_positions.py   # 公司电脑 / 离线
  FG_SYNC_MODE=live   python scripts/sync_positions.py   # 家里 Mac 动态同步
"""
import argparse
import datetime as dt
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config  # noqa: E402

ACCOUNTS_HEADER = ["date", "account", "net_value", "securities_mv", "cash",
                   "unrealized_pnl", "day_pnl", "currency", "note"]
POSITIONS_HEADER = ["date", "account", "symbol", "name", "qty", "price",
                    "cost", "market_value", "notional", "margin", "bucket", "currency"]

OKX_CRED_PATH = os.path.expanduser("~/.okx_credentials.json")


def today():
    return dt.date.today().isoformat()


def load_existing():
    """读取现有快照；文件缺失时返回空 DataFrame（带表头）。"""
    a = pd.read_csv(config.ACCOUNTS_PATH) if os.path.exists(config.ACCOUNTS_PATH) \
        else pd.DataFrame(columns=ACCOUNTS_HEADER)
    p = pd.read_csv(config.POSITIONS_PATH) if os.path.exists(config.POSITIONS_PATH) \
        else pd.DataFrame(columns=POSITIONS_HEADER)
    return a, p


def write_snapshot(accounts, positions):
    """原子写（tmp + rename），追加当日行。"""
    tmp_a, tmp_p = config.ACCOUNTS_PATH + ".tmp", config.POSITIONS_PATH + ".tmp"
    accounts.to_csv(tmp_a, index=False)
    positions.to_csv(tmp_p, index=False)
    os.replace(tmp_a, config.ACCOUNTS_PATH)
    os.replace(tmp_p, config.POSITIONS_PATH)


# ---------------------------------------------------------------- 富途
def sync_futu(accounts, positions, date):
    """富途(FutuOpenD) → 股票账户快照行。OpenD 不可达时打印提示并跳过（不崩溃）。"""
    try:
        import futu
    except ImportError:
        print("[futu] 未安装 futu-api，跳过股票账户（pip install futu-api）")
        return accounts, positions
    try:
        ctx = futu.OpenSecTradeContext(filter_trdmarket=futu.TrdMarket.US,
                                       host="127.0.0.1", port=11111,
                                       security_firm=futu.SecurityFirm.FUTUSECURITIES)
    except Exception as e:
        print(f"[futu] 无法连接 FutuOpenD（127.0.0.1:11111）：{e}\n"
              f"       请先启动 FutuOpenD 并开通 API 权限，或忽略此项（公司电脑用 static 模式）")
        return accounts, positions

    ret, accs = ctx.get_acc_list()
    if ret != futu.RET_OK or not accs:
        print(f"[futu] get_acc_list 失败: {accs}")
        return accounts, positions
    # 富途返回 acc_list 为 dict；取 account_id
    acc_id = accs.get("account_id") if isinstance(accs, dict) else accs[0].get("account_id")
    if acc_id is None:
        # 兼容 list[dict] 形态
        acc_id = accs[0]["account_id"] if isinstance(accs, list) else None
    if acc_id is None:
        print(f"[futu] 未取得 account_id: {accs}")
        return accounts, positions

    # 资产（净值/现金/市值）
    ret, info = ctx.accinfo_query(acc_id=acc_id, currency="USD")
    if ret != futu.RET_OK:
        print(f"[futu] accinfo_query 失败: {info}")
        return accounts, positions
    net = float(info.get("net_assets", 0) or 0)
    cash = float(info.get("cash", 0) or 0)
    mv = float(info.get("market_val", 0) or 0)
    unrealized = float(info.get("unrealized_pl", 0) or 0) if "unrealized_pl" in info else ""
    note = "富途动态同步"
    if "power" in info:
        note += f"；购买力={info.get('power')}"
    accounts.loc[len(accounts)] = [date, "stock", round(net, 2), round(mv, 2),
                                   round(cash, 2), unrealized, "", "USD", note]

    # 持仓
    ret, poss = ctx.position_list_query(acc_id=acc_id, currency="USD")
    if ret != futu.RET_OK:
        print(f"[futu] position_list_query 失败: {poss}")
        return accounts, positions
    for pos in poss:
        code = pos.get("code", "")
        qty = float(pos.get("qty", 0) or 0)
        if qty == 0:
            continue
        cost = float(pos.get("cost_price", 0) or 0)
        price = float(pos.get("market_val", 0) or 0) / qty if qty else 0
        notional = float(pos.get("nominal_value", 0) or 0) or round(qty * price, 2)
        name = pos.get("stock_name", "") or code
        positions.loc[len(positions)] = [date, "stock", code, name, qty, round(price, 4),
                                         round(cost, 4), round(notional, 2), round(notional, 2),
                                         "", "system", "USD"]
    ctx.close()
    return accounts, positions


# ---------------------------------------------------------------- OKX
def _okx_creds():
    if not os.path.exists(OKX_CRED_PATH):
        return None
    with open(OKX_CRED_PATH) as f:
        return json.load(f)


def sync_okx(accounts, positions, date):
    """OKX REST → 加密账户快照行。凭据缺失/网络失败时打印提示并跳过。"""
    creds = _okx_creds()
    if not creds:
        print(f"[okx] 缺少凭据文件 {OKX_CRED_PATH}，跳过加密账户。\n"
              f"       格式: {{\"api_key\":\"..\",\"secret\":\"..\",\"passphrase\":\"..\","
              f"\"proxy\":\"http://127.0.0.1:7890\"(可选)}}，chmod 600")
        return accounts, positions
    try:
        from okx.api.account import Account
    except ImportError:
        print("[okx] 未安装 okx 包，跳过加密账户（pip install okx）")
        return accounts, positions

    proxies = {}
    proxy_host = None
    if creds.get("proxy"):
        proxies = {"http": creds["proxy"], "https": creds["proxy"]}
        proxy_host = creds["proxy"]
    try:
        api = Account(key=creds["api_key"], secret=creds["secret"],
                      passphrase=creds["passphrase"], flag="0",
                      proxies=proxies, proxy_host=proxy_host)
    except Exception as e:
        print(f"[okx] Account 初始化失败: {e}")
        return accounts, positions

    try:
        bal = api.get_balance()
    except Exception as e:
        print(f"[okx] get_balance 失败: {e}")
        return accounts, positions
    if bal.get("code") != "0":
        print(f"[okx] get_balance 错误: code={bal.get('code')} msg={bal.get('msg')}")
        return accounts, positions
    data = (bal.get("data") or [{}])[0]
    total_eq = float(data.get("totalEq", 0) or 0)
    cash = float(data.get("cash", 0) or 0)
    accounts.loc[len(accounts)] = [date, "crypto", round(total_eq, 2), "", round(cash, 2),
                                   "", "", "USDT", "OKX 动态同步"]

    try:
        poss = api.get_positions()
    except Exception as e:
        print(f"[okx] get_positions 失败: {e}")
        return accounts, positions
    if poss.get("code") != "0":
        print(f"[okx] get_positions 错误: code={poss.get('code')} msg={poss.get('msg')}")
        return accounts, positions
    for pos in poss.get("data") or []:
        inst = pos.get("instId", "")
        qty = float(pos.get("pos", 0) or 0)
        if qty == 0:
            continue
        cost = float(pos.get("avgPx", 0) or 0)
        price = float(pos.get("markPx", 0) or 0)
        notional = float(pos.get("notionalUsd", 0) or 0) or round(qty * price, 2)
        name = {"BTC-USDT": "BTC现货杠杆(借USDT买入)", "BTC-USDT-SWAP": "BTC永续"}.get(inst, inst)
        positions.loc[len(positions)] = [date, "crypto", inst, name, qty, round(price, 4),
                                         round(cost, 4), round(notional, 2), round(notional, 2),
                                         "", "system", "USDT"]
    return accounts, positions


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="账户/持仓快照同步（实盘数据运行时生成）")
    ap.add_argument("--check", action="store_true", help="仅查看当前快照状态，不执行任何同步")
    args = ap.parse_args()

    mode = os.environ.get("FG_SYNC_MODE", "static").strip().lower()

    if args.check:
        a, p = load_existing()
        print("当前快照状态：")
        if a.empty:
            print("  accounts.csv 为空或不存在")
        else:
            print("  accounts.csv 最新日期:", a["date"].max(), "| 行数:", len(a))
            print(a.tail(3).to_string(index=False))
        if p.empty:
            print("  positions.csv 为空或不存在")
        else:
            print("  positions.csv 最新日期:", p["date"].max(), "| 行数:", len(p))
        return

    if mode == "static":
        a, p = load_existing()
        print("[sync] FG_SYNC_MODE=static：不调用任何外部 API（公司电脑模式）。")
        print(f"[sync] 现有快照保持原样：accounts {len(a)} 行 / positions {len(p)} 行。")
        print("[sync] 如需在家动态同步：FG_SYNC_MODE=live python scripts/sync_positions.py")
        return

    if mode != "live":
        print(f"[sync] 未知 FG_SYNC_MODE={mode!r}，取 static 行为（安全默认）。")
        return

    print(f"[sync] FG_SYNC_MODE=live：动态同步 {today()}")
    accounts, positions = load_existing()
    accounts, positions = sync_futu(accounts, positions, today())
    accounts, positions = sync_okx(accounts, positions, today())
    write_snapshot(accounts, positions)
    print(f"[sync] 已写入：accounts {len(accounts)} 行 / positions {len(positions)} 行"
          f"（含当日新增）")


if __name__ == "__main__":
    main()
