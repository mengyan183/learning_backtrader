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


def _f(x, default=0.0):
    """安全转 float：'N/A'/空/None 等异常值 → default。"""
    try:
        v = float(x)
        return v
    except (TypeError, ValueError):
        return default


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
def _opend_alive(host="127.0.0.1", port=11111, timeout=2.0):
    """快速探测 FutuOpenD 是否可达（避免无 OpenD 时连接挂起数十秒）。"""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def sync_futu(accounts, positions, date):
    """富途(FutuOpenD) → 股票账户快照行。OpenD 不可达时打印提示并跳过（不崩溃）。"""
    if not _opend_alive():
        print("[futu] FutuOpenD 未运行（127.0.0.1:11111 不可达），跳过股票账户。\n"
              "       家里 Mac 首次使用：下载 FutuOpenD 并开通 API 权限后重试；"
              "公司电脑用 static 模式")
        return accounts, positions
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
    if ret != futu.RET_OK or (hasattr(accs, "empty") and accs.empty):
        print(f"[futu] get_acc_list 失败: {accs}")
        return accounts, positions
    # futu 10.x 返回 DataFrame；优先取 REAL + ACTIVE 的保证金账户
    if hasattr(accs, "iloc"):
        df = accs
        if "trd_env" in df.columns and "acc_status" in df.columns:
            df = df[(df["trd_env"] == "REAL") & (df["acc_status"] == "ACTIVE")]
            if df.empty:
                df = accs[accs["trd_env"] == "REAL"]
        if df.empty:
            print(f"[futu] 无可用真实账户: {accs}")
            return accounts, positions
        acc_id = int(df.iloc[0]["acc_id"])
    else:
        acc_id = int(accs[0]["acc_id"])
    print(f"[futu] 使用账户 acc_id={acc_id}")

    # 资产（净值/现金/市值）——DataFrame 单行
    ret, info = ctx.accinfo_query(acc_id=acc_id, currency="USD")
    if ret != futu.RET_OK:
        print(f"[futu] accinfo_query 失败: {info}")
        return accounts, positions
    if hasattr(info, "iloc") and not info.empty:
        r = info.iloc[0]
        net = _f(r.get("total_assets", 0))
        cash = _f(r.get("cash", 0))
        mv = _f(r.get("market_val", 0))
        unrealized = _f(r.get("unrealized_pl", 0))
        note = "富途动态同步"
        if "net_cash_power" in info.columns:
            note += f"；净购买力={r.get('net_cash_power')}"
        accounts.loc[len(accounts)] = [date, "stock", round(net, 2), round(mv, 2),
                                       round(cash, 2), round(unrealized, 2), "", "USD", note]
    else:
        print(f"[futu] accinfo 返回异常: {info}")
        return accounts, positions

    # 持仓——DataFrame 多行；code 去除 "US." 前缀
    ret, poss = ctx.position_list_query(acc_id=acc_id, currency="USD")
    if ret != futu.RET_OK:
        print(f"[futu] position_list_query 失败: {poss}")
        return accounts, positions
    if hasattr(poss, "iterrows"):
        for _, pos in poss.iterrows():
            code = str(pos.get("code", "") or "").replace("US.", "", 1)
            qty = _f(pos.get("qty", 0))
            if qty == 0:
                continue
            cost = _f(pos.get("cost_price", 0))
            price = _f(pos.get("nominal_price", 0))
            notional = _f(pos.get("market_val", 0)) or round(qty * price, 2)
            name = str(pos.get("stock_name", "") or "") or code
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


def _okx_request(creds, path):
    """OKX V5 REST 请求（curl 签名，与 scripts/okx_monitor.py 同法；走代理）。"""
    import base64
    import hashlib
    import hmac
    import subprocess
    import tempfile
    import datetime

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    sig = base64.b64encode(
        hmac.new(creds["secret"].encode(),
                 (ts + "GET" + path).encode(), hashlib.sha256).digest()
    ).decode()
    # G-5（WT-12 审查）：凭据**不得**出现在 curl 的 argv 里 —— 同机任意进程
    # （`ps aux` / 任务管理器）都能读到 api_key / 签名 / passphrase，等于把
    # 密钥文件 0600 的保护整个绕开。改用 `--config` 临时文件（0600，用完即删）；
    # argv 里只留 `-x` 代理（无凭据）。
    def _q(v):
        return str(v).replace("\\", "\\\\").replace('"', '\\"')

    cfg_lines = ['header = "OK-ACCESS-KEY: %s"' % _q(creds["api_key"]),
                 'header = "OK-ACCESS-SIGN: %s"' % _q(sig),
                 'header = "OK-ACCESS-TIMESTAMP: %s"' % _q(ts),
                 'header = "OK-ACCESS-PASSPHRASE: %s"' % _q(creds["passphrase"]),
                 'header = "Content-Type: application/json"']
    fd, cfg = tempfile.mkstemp(prefix="okx_curl_", suffix=".cfg")
    try:
        os.chmod(cfg, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(cfg_lines) + "\n")
        cmd = ["curl", "-s", "-m", "30", "--config", cfg,
               "https://www.okx.com" + path]
        if creds.get("proxy"):
            cmd[1:1] = ["-x", creds["proxy"]]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    finally:
        os.remove(cfg)
    if r.returncode != 0:
        raise RuntimeError(f"curl 失败: {r.stderr[:150]}")
    return json.loads(r.stdout or "{}")


def sync_okx(accounts, positions, date):
    """OKX REST → 加密账户快照行。凭据缺失/网络失败时打印提示并跳过。"""
    creds = _okx_creds()
    if not creds:
        print(f"[okx] 缺少凭据文件 {OKX_CRED_PATH}，跳过加密账户。\n"
              f"       格式: {{\"api_key\":\"..\",\"secret\":\"..\",\"passphrase\":\"..\","
              f"\"proxy\":\"http://127.0.0.1:7890\"(可选)}}，chmod 600")
        return accounts, positions

    try:
        bal = _okx_request(creds, "/api/v5/account/balance")
    except Exception as e:
        print(f"[okx] get_balance 失败: {e}")
        return accounts, positions
    if bal.get("code") != "0":
        print(f"[okx] get_balance 错误: code={bal.get('code')} msg={bal.get('msg')}")
        return accounts, positions
    data = (bal.get("data") or [{}])[0]
    total_eq = _f(data.get("totalEq", 0))
    cash = _f(data.get("cash", 0))
    accounts.loc[len(accounts)] = [date, "crypto", round(total_eq, 2), "", round(cash, 2),
                                   "", "", "USDT", "OKX 动态同步"]

    try:
        poss = _okx_request(creds, "/api/v5/account/positions")
    except Exception as e:
        print(f"[okx] get_positions 失败: {e}")
        return accounts, positions
    if poss.get("code") != "0":
        print(f"[okx] get_positions 错误: code={poss.get('code')} msg={poss.get('msg')}")
        return accounts, positions
    for pos in poss.get("data") or []:
        inst = pos.get("instId", "")
        qty = _f(pos.get("pos", 0))
        if qty == 0:
            continue
        cost = _f(pos.get("avgPx", 0))
        price = _f(pos.get("markPx", 0))
        notional = _f(pos.get("notionalUsd", 0)) or round(qty * price, 2)
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
    # 当日覆盖写：同一交易日已有快照行时先剔除，避免重复追加导致下游重复计入
    accounts = accounts[accounts["date"] != today()].reset_index(drop=True)
    positions = positions[positions["date"] != today()].reset_index(drop=True)
    accounts, positions = sync_futu(accounts, positions, today())
    accounts, positions = sync_okx(accounts, positions, today())
    write_snapshot(accounts, positions)
    print(f"[sync] 已写入：accounts {len(accounts)} 行 / positions {len(positions)} 行"
          f"（含当日新增）")


if __name__ == "__main__":
    main()
